"""Nhiều CallBridge chạy đồng thời trong 1 process không được leak state giữa các call.
Dùng lại fake object từ test_call_bridge_mapping qua import trực tiếp thay vì định nghĩa
lại — cùng contract, tránh 2 bản lệch nhau.
"""

import asyncio

import pytest
from tests.transports.livekit_support import require_livekit

require_livekit()

from tests.transports.livekit.bridge_factory import make_call_bridge  # noqa: E402
from tests.transports.livekit.test_call_bridge_mapping import (  # noqa: E402
    _FakeAudioSource,
    _FakeOrchestrator,
    _FakeRoom,
    _FakeSTTPipeline,
    _FakeTTS,
)

from callbot.engine.types import BotAction  # noqa: E402
from callbot.tracing import Tracer  # noqa: E402
from callbot.tracing.pseudonym import CallKeyFactory  # noqa: E402
from speech.turn.events import UserTurnCompleted  # noqa: E402


@pytest.fixture(autouse=True)
def _run_fake_orchestrator_inline(monkeypatch):
    async def inline(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", inline)


async def _run_one_call(room_name: str, user_text: str) -> tuple[str, list[str]]:
    """Trả (call_id nhận được ở handle_turn_with_details, danh sách text bot đã nói) cho 1 call —
    dùng để assert không lẫn dữ liệu giữa các call chạy song song."""
    opening = BotAction(utterance=f"Chào {room_name}", state="AWAITING_INTENT", ended=False)
    closing = BotAction(
        utterance=f"Tạm biệt {room_name}", state="ENDED", ended=True, outcome="TRANSFERRED"
    )
    orchestrator = _FakeOrchestrator(opening=opening, turn_actions=[closing])
    stt_pipeline = _FakeSTTPipeline([UserTurnCompleted(text=user_text)])
    tts = _FakeTTS()
    room = _FakeRoom(room_name)

    bridge = make_call_bridge(room, orchestrator, stt_pipeline, tts)
    bridge._audio_source = _FakeAudioSource()
    bridge._publish_tts_track = _noop_publish

    await bridge.run()

    call_id, caller = orchestrator.handled_turns[0]
    assert caller.text == user_text  # sanity: fake của chính call này không bị ai ghi đè
    return call_id, tts.spoken


async def _noop_publish() -> None:
    return None


async def test_multiple_call_bridges_do_not_leak_state_across_calls() -> None:
    calls = [
        ("web-room-a", "tôi muốn đặt lịch khám"),
        ("web-room-b", "tôi muốn huỷ lịch hẹn"),
        ("web-room-c", "cho tôi hỏi giờ mở cửa"),
    ]

    results = await asyncio.gather(*(_run_one_call(name, text) for name, text in calls))

    by_room = dict(zip([c[0] for c in calls], results, strict=True))
    for room_name, _user_text in calls:
        call_id, spoken = by_room[room_name]
        assert call_id == room_name
        assert spoken == [f"Chào {room_name}", f"Tạm biệt {room_name}"]
        # Không câu chào/tạm biệt của room khác lọt vào transcript của room này.
        for other_name, _ in calls:
            if other_name != room_name:
                assert other_name not in " ".join(spoken)


async def test_turn_controller_and_interruption_are_distinct_instances_per_bridge() -> None:
    """Audit trực tiếp: mỗi CallBridge phải tự tạo TurnController/InterruptionController
    riêng (constructor, không phải class-level default) — 2 instance không được is nhau."""
    opening = BotAction(utterance="chào", state="AWAITING_INTENT", ended=True)
    orchestrator_a = _FakeOrchestrator(opening=opening, turn_actions=[])
    orchestrator_b = _FakeOrchestrator(opening=opening, turn_actions=[])
    stt_pipeline = _FakeSTTPipeline([])

    bridge_a = make_call_bridge(_FakeRoom("room-a"), orchestrator_a, stt_pipeline, _FakeTTS())
    bridge_b = make_call_bridge(_FakeRoom("room-b"), orchestrator_b, stt_pipeline, _FakeTTS())

    assert bridge_a._turn_controller is not bridge_b._turn_controller
    assert bridge_a._interruption is not bridge_b._interruption
    assert bridge_a._frame_queue is not bridge_b._frame_queue


async def test_livekit_parallel_calls_keep_separate_trace_trees() -> None:
    class Sink:
        def __init__(self):
            self.records = []

        def emit(self, record):
            self.records.append(record)

    sink = Sink()
    keys = CallKeyFactory("livekit-parallel-tracing-key-000000", version="v1", environment="test")

    async def run(room_name: str) -> None:
        opening = BotAction(utterance="chào", state="AWAITING_INTENT", ended=False)
        closing = BotAction(utterance="tạm biệt", state="ENDED", ended=True, outcome="TRANSFERRED")
        orchestrator = _FakeOrchestrator(opening, [closing])
        orchestrator.tracer = Tracer(sink, keys)
        bridge = make_call_bridge(
            _FakeRoom(room_name),
            orchestrator,
            _FakeSTTPipeline([UserTurnCompleted(text="xin chào", confidence=0.8)]),
            _FakeTTS(),
        )
        bridge._audio_source = _FakeAudioSource()
        bridge._publish_tts_track = _noop_publish
        await bridge.run()

    await asyncio.gather(run("room-a"), run("room-b"))
    roots = [item for item in sink.records if item.component == "TURN"]
    assert len(roots) == 4
    assert len({item.call_key for item in roots}) == 2
    for call_key in {item.call_key for item in roots}:
        this_call = [item for item in sink.records if item.call_key == call_key]
        assert {item.turn for item in this_call if item.component == "TURN"} == {0, 1}
        for root in (item for item in this_call if item.component == "TURN"):
            children = [item for item in this_call if item.parent_span_id == root.span_id]
            assert {item.component for item in children} == (
                {"TTS"} if root.turn == 0 else {"STT", "TTS"}
            )
            assert all(item.trace_id == root.trace_id for item in children)
    assert all(item.status == "OK" for item in roots)  # TRANSFERRED is a business outcome.


if __name__ == "__main__":
    pytest.main([__file__])
