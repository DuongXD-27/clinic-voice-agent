"""Nhiều CallBridge chạy đồng thời trong 1 process không được leak state giữa các call.
Dùng lại fake object từ test_call_bridge_mapping qua import trực tiếp thay vì định nghĩa
lại — cùng contract, tránh 2 bản lệch nhau.
"""

import asyncio

import pytest

pytest.importorskip("livekit", reason="cần extra [livekit] cài livekit-agents/livekit-api")

from tests.transports.livekit.test_call_bridge_mapping import (  # noqa: E402
    _FakeAudioSource,
    _FakeOrchestrator,
    _FakeRoom,
    _FakeSTTPipeline,
    _FakeTTS,
)

from callbot.engine.types import BotAction  # noqa: E402
from callbot.transports.livekit.call_bridge import CallBridge  # noqa: E402
from speech.turn.events import UserTurnCompleted  # noqa: E402


@pytest.fixture(autouse=True)
def _run_fake_orchestrator_inline(monkeypatch):
    async def inline(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", inline)


async def _run_one_call(room_name: str, user_text: str) -> tuple[str, list[str]]:
    """Trả (call_id nhận được ở handle_turn, danh sách text bot đã nói) cho 1 call —
    dùng để assert không lẫn dữ liệu giữa các call chạy song song."""
    opening = BotAction(utterance=f"Chào {room_name}", state="AWAITING_INTENT", ended=False)
    closing = BotAction(
        utterance=f"Tạm biệt {room_name}", state="ENDED", ended=True, outcome="TRANSFERRED"
    )
    orchestrator = _FakeOrchestrator(opening=opening, turn_actions=[closing])
    stt_pipeline = _FakeSTTPipeline([UserTurnCompleted(text=user_text)])
    tts = _FakeTTS()
    room = _FakeRoom(room_name)

    bridge = CallBridge(room, orchestrator, stt_pipeline, tts)
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

    bridge_a = CallBridge(_FakeRoom("room-a"), orchestrator_a, stt_pipeline, _FakeTTS())
    bridge_b = CallBridge(_FakeRoom("room-b"), orchestrator_b, stt_pipeline, _FakeTTS())

    assert bridge_a._turn_controller is not bridge_b._turn_controller
    assert bridge_a._interruption is not bridge_b._interruption
    assert bridge_a._frame_queue is not bridge_b._frame_queue


if __name__ == "__main__":
    pytest.main([__file__])
