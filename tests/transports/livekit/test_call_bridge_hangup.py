"""R-36 trên LiveKit: khách rời cuộc gọi thì bot dừng nói, không gửi lượt nào cho Core, đóng phiên.

Phase 0 (12/10): trước bản sửa, khách đóng tab thì bridge không biết, tiếp tục gửi lượt im lặng cho
Core tới khi LiveKit đóng phòng (~25-30 s) — đủ lâu là tới lượt im lặng thứ 3 và ghi UNREACHABLE.
"""

import asyncio
from types import SimpleNamespace

import pytest
from tests.transports.livekit_support import require_livekit

require_livekit()

from tests.transports.livekit.bridge_factory import make_call_bridge  # noqa: E402
from tests.transports.livekit.test_call_bridge_mapping import (  # noqa: E402
    _FakeAudioSource,
    _FakeOrchestrator,
    _FakeRoom,
    _FakeTTS,
    _WholeSentenceTTS,
)

from callbot.engine.errors import CallEnded  # noqa: E402
from callbot.engine.types import BotAction  # noqa: E402
from speech.turn.events import UserTurnCompleted  # noqa: E402

ROOM = "web-hangup-room"
CALLER = SimpleNamespace(identity="caller-1")
OPENING = BotAction(utterance="Dạ, Vinmec xin nghe", state="AWAITING_IDENTITY")


@pytest.fixture(autouse=True)
def _run_fake_orchestrator_inline(monkeypatch):
    async def inline(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", inline)


class _ListeningPipeline:
    """Trả các lượt có sẵn rồi nghe tiếp tới khi hết audio (như STT thật khi khách im)."""

    def __init__(self, turns=()) -> None:
        self._turns = list(turns)

    async def stream(self, frames, turn_controller=None, interruption=None):
        for turn in self._turns:
            yield turn
        async for _ in frames:
            pass


class _RecordingAudioSource(_FakeAudioSource):
    def __init__(self, log: list[str]) -> None:
        super().__init__()
        self._log = log

    async def wait_for_playout(self) -> None:
        await super().wait_for_playout()
        self._log.append("playout")


class _RecordingOrchestrator(_FakeOrchestrator):
    def __init__(self, opening, turn_actions, log: list[str]) -> None:
        super().__init__(opening, turn_actions)
        self._log = log

    def close_call(self, call_id: str) -> bool:
        self._log.append("close")
        return super().close_call(call_id)


def _bridge(orchestrator, pipeline, tts, source, **overrides):
    bridge = make_call_bridge(
        _FakeRoom(ROOM), orchestrator, pipeline, tts, caller_identity="caller-1", **overrides
    )

    async def publish() -> None:
        bridge._audio_source = source

    bridge._publish_tts_track = publish
    return bridge


def _leave(bridge, participant=CALLER) -> None:
    """Như SDK: callback chạy trên event loop, ngoài task đang phát."""
    asyncio.get_running_loop().call_soon(
        bridge._room._handlers["participant_disconnected"], participant
    )


async def test_caller_leaving_mid_sentence_stops_speech_and_closes_the_session() -> None:
    orchestrator = _FakeOrchestrator(OPENING, turn_actions=[])
    tts = _WholeSentenceTTS()
    source = _FakeAudioSource()
    bridge = _bridge(orchestrator, _ListeningPipeline(), tts, source)
    play = source.capture_frame

    async def play_then_leave(frame) -> None:
        await play(frame)
        if len(source.captured_frames) == 10:  # 200 ms vào lời chào
            _leave(bridge)
        await asyncio.sleep(0)  # AudioSource thật nhường event loop khi đẩy frame

    source.capture_frame = play_then_leave

    await asyncio.wait_for(bridge.run(), timeout=2.0)

    assert len(source.captured_frames) <= 11  # dừng ngay, không đọc nốt 3 s
    assert orchestrator.handled_turns == []
    assert orchestrator.close_requests == [ROOM]
    assert orchestrator.closed_calls == [ROOM]
    assert tts.cancel_calls >= 1  # request TTS đóng hẳn
    assert source.closed


async def test_no_silence_turn_reaches_core_after_the_caller_left() -> None:
    """Đúng lỗi của Phase 0: khách rời mà bridge vẫn đếm là im lặng."""
    orchestrator = _FakeOrchestrator(OPENING, turn_actions=[])
    bridge = _bridge(
        orchestrator,
        _ListeningPipeline(),
        _FakeTTS(),
        _FakeAudioSource(),
        silence_timeout_ms=300,
    )
    run = asyncio.ensure_future(bridge.run())
    await asyncio.sleep(0.05)  # lời chào xong, hẹn giờ im lặng đang chạy

    _leave(bridge)
    await asyncio.wait_for(run, timeout=1.0)
    await asyncio.sleep(0.4)  # quá hạn im lặng: không lượt nào được gửi

    assert orchestrator.handled_turns == []
    assert orchestrator.closed_calls == [ROOM]


async def test_core_turn_finishing_after_the_caller_left_is_not_spoken() -> None:
    reply = BotAction(utterance="Dạ, em đã ghi nhận", state="AWAITING_IDENTITY")
    orchestrator = _FakeOrchestrator(OPENING, turn_actions=[reply])
    tts = _FakeTTS()
    pipeline = _ListeningPipeline([UserTurnCompleted(text="Nguyễn Văn A", confidence=0.9)])
    bridge = _bridge(orchestrator, pipeline, tts, _FakeAudioSource())
    handle_turn = orchestrator.handle_turn

    def leave_while_core_runs(call_id, caller):
        bridge._room._handlers["participant_disconnected"](CALLER)
        return handle_turn(call_id, caller)

    orchestrator.handle_turn = leave_while_core_runs

    await asyncio.wait_for(bridge.run(), timeout=2.0)

    assert len(orchestrator.handled_turns) == 1  # lượt đang chạy được chạy xong, không bỏ ngang
    assert tts.spoken == [OPENING.utterance]  # nhưng câu trả lời không được phát
    assert orchestrator.closed_calls == [ROOM]


async def test_core_refusing_a_turn_after_the_caller_left_is_not_an_error() -> None:
    """Cổng ghi chặn lệnh chưa gửi -> Core ném CallEnded; bridge kết thúc êm, không crash job."""
    orchestrator = _FakeOrchestrator(OPENING, turn_actions=[])
    pipeline = _ListeningPipeline([UserTurnCompleted(text="Hủy giúp tôi", confidence=0.9)])
    bridge = _bridge(orchestrator, pipeline, _FakeTTS(), _FakeAudioSource())

    def blocked_by_hangup(call_id, caller):
        bridge._room._handlers["participant_disconnected"](CALLER)
        raise CallEnded(call_id)

    orchestrator.handle_turn = blocked_by_hangup

    await asyncio.wait_for(bridge.run(), timeout=2.0)

    assert orchestrator.closed_calls == [ROOM]


async def test_call_ended_while_the_caller_is_still_there_still_fails_loudly() -> None:
    orchestrator = _FakeOrchestrator(OPENING, turn_actions=[])
    pipeline = _ListeningPipeline([UserTurnCompleted(text="alo", confidence=0.9)])
    bridge = _bridge(orchestrator, pipeline, _FakeTTS(), _FakeAudioSource())

    def ended(call_id, caller):
        raise CallEnded(call_id)

    orchestrator.handle_turn = ended

    with pytest.raises(CallEnded):
        await asyncio.wait_for(bridge.run(), timeout=2.0)


async def test_another_participant_leaving_does_not_end_the_call() -> None:
    closing = BotAction(
        utterance="Dạ, em chào anh chị", state="ENDED", ended=True, outcome="CONFIRMED"
    )
    orchestrator = _FakeOrchestrator(OPENING, turn_actions=[closing])
    pipeline = _ListeningPipeline([UserTurnCompleted(text="vâng", confidence=0.9)])
    tts = _FakeTTS()
    bridge = _bridge(orchestrator, pipeline, tts, _FakeAudioSource())
    handle_turn = orchestrator.handle_turn

    def other_leaves(call_id, caller):
        bridge._room._handlers["participant_disconnected"](SimpleNamespace(identity="someone-else"))
        return handle_turn(call_id, caller)

    orchestrator.handle_turn = other_leaves

    await asyncio.wait_for(bridge.run(), timeout=2.0)

    assert tts.spoken == [OPENING.utterance, closing.utterance]
    assert orchestrator.close_requests == []
    assert orchestrator.closed_calls == [ROOM]  # kết thúc bình thường vẫn đóng phiên


async def test_normal_end_plays_the_last_sentence_fully_before_closing_the_session() -> None:
    log: list[str] = []
    transfer = BotAction(
        utterance="Em xin chuyển máy tới nhân viên để hỗ trợ anh chị ạ.",
        state="ENDED",
        ended=True,
        outcome="TRANSFERRED",
    )
    orchestrator = _RecordingOrchestrator(OPENING, [transfer], log)
    pipeline = _ListeningPipeline([UserTurnCompleted(text="gặp nhân viên", confidence=0.9)])
    bridge = _bridge(orchestrator, pipeline, _FakeTTS(), _RecordingAudioSource(log))

    await asyncio.wait_for(bridge.run(), timeout=2.0)

    assert log == ["playout", "playout", "close"]  # lời chào, câu chuyển máy, rồi mới đóng phiên


async def test_room_disconnect_is_a_fallback_hangup_signal() -> None:
    orchestrator = _FakeOrchestrator(OPENING, turn_actions=[])
    bridge = _bridge(orchestrator, _ListeningPipeline(), _FakeTTS(), _FakeAudioSource())
    run = asyncio.ensure_future(bridge.run())
    await asyncio.sleep(0.05)

    bridge._room._handlers["disconnected"]()
    await asyncio.wait_for(run, timeout=1.0)

    assert orchestrator.handled_turns == []
    assert orchestrator.closed_calls == [ROOM]
