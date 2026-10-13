"""R-39 trên LiveKit: TTS lỗi giữa cuộc gọi thì bot phát câu chuyển máy ghi sẵn (giọng Vbee đã duyệt)
và chuyển nhân viên SYSTEM_ERROR, thay vì im lặng rồi rớt máy.

Trước bản sửa: lỗi trước chunk đầu làm `_speak` ném lỗi, job chết, khách nghe im rồi mất máy; lỗi giữa
câu thì cuộc gọi chạy tiếp với câu bị cụt. Phía Clinic (bảng 2.2) test ở
tests/engine/session/test_system_error.py; ở đây chỉ kiểm phía khách nghe và tín hiệu chuyển máy.
"""

import asyncio
import json
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
)

from callbot.engine.dialogue import templates as t  # noqa: E402
from callbot.engine.errors import CallEnded  # noqa: E402
from callbot.engine.types import BotAction, TTSRecovery  # noqa: E402
from callbot.transports.livekit.call_bridge import TRANSCRIPT_TOPIC  # noqa: E402
from callbot.transports.livekit.status import STATUS_TOPIC  # noqa: E402
from speech.turn.events import UserTurnCompleted  # noqa: E402
from speech.turn.interruption import InterruptionState  # noqa: E402

ROOM = "web-tts-error-room"
OPENING = BotAction(utterance="Dạ, Vinmec xin nghe", state="AWAITING_IDENTITY")
REPLY = BotAction(utterance="Anh chị cho em xin ngày sinh ạ?", state="AWAITING_IDENTITY")
HANDED_OFF = BotAction(
    t.TRANSFER, "ENDED", ended=True, outcome="TRANSFERRED", transfer_reason="SYSTEM_ERROR"
)
# assets/tts/static/2026-10-08-v1/073_TRANSFER_*.wav: 21 768 mẫu 8 kHz (2,72 s) = 137 frame 20 ms
TRANSFER_FRAMES = 137


@pytest.fixture(autouse=True)
def _run_fake_orchestrator_inline(monkeypatch):
    async def inline(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", inline)


class _ListeningPipeline:
    def __init__(self, turns=()) -> None:
        self._turns = list(turns)

    async def stream(self, frames, turn_controller=None, interruption=None):
        for turn in self._turns:
            yield turn
        async for _ in frames:
            pass


class _BrokenTTS(_FakeTTS):
    """Như gateway Vbee với token sai: câu trong `fail_before_audio` lỗi trước chunk đầu (không có
    dự phòng); câu trong `cut_mid_sentence` phát một phần rồi dừng êm kèm `error_code`."""

    stream_sample_rate = 8000

    def __init__(self, fail_before_audio=(), cut_mid_sentence=()) -> None:
        super().__init__()
        self._fail = set(fail_before_audio)
        self._cut = set(cut_mid_sentence)
        self.last_stream_result = None

    async def synthesize_stream(self, text: str):
        self.spoken.append(text)
        self.last_stream_result = SimpleNamespace(
            provider_actual="vbee",
            voice="vbee-voice",
            error_code="connection_failed" if text in self._cut else None,
        )
        if text in self._fail:
            raise RuntimeError("401 Unauthorized token=secret")
        yield b"\x00\x10" * 160


class _RecoveringOrchestrator(_FakeOrchestrator):
    def __init__(self, opening, turn_actions, recovery=None, error=None) -> None:
        super().__init__(opening, turn_actions)
        self._recovery = recovery or TTSRecovery(t.TRANSFER, action=HANDED_OFF)
        self._error = error
        self.tts_errors: list[str] = []

    def handle_tts_error(self, call_id: str) -> TTSRecovery:
        self.tts_errors.append(call_id)
        if self._error is not None:
            raise self._error
        return self._recovery


def _bridge(orchestrator, tts, turns=(), source=None):
    bridge = make_call_bridge(
        _FakeRoom(ROOM), orchestrator, _ListeningPipeline(turns), tts, caller_identity="caller-1"
    )
    source = source or _FakeAudioSource()

    async def publish() -> None:
        bridge._audio_source = source

    bridge._publish_tts_track = publish
    return bridge, source


def _status(bridge) -> list[dict]:
    return [data for data, topic, _ in bridge._room.local_participant.data if topic == STATUS_TOPIC]


def _bot_lines(bridge) -> list[str]:
    return [
        data["text"]
        for data, topic, _ in bridge._room.local_participant.data
        if topic == TRANSCRIPT_TOPIC and data["role"] == "bot"
    ]


async def test_greeting_failing_before_audio_plays_the_recorded_transfer_and_hands_off() -> None:
    orchestrator = _RecoveringOrchestrator(OPENING, turn_actions=[])
    bridge, source = _bridge(orchestrator, _BrokenTTS(fail_before_audio=[OPENING.utterance]))

    await asyncio.wait_for(bridge.run(), timeout=2.0)

    assert orchestrator.tts_errors == [ROOM]
    assert len(source.captured_frames) == TRANSFER_FRAMES  # câu ghi sẵn phát trọn
    assert _bot_lines(bridge) == [OPENING.utterance, t.TRANSFER]
    (handoff,) = _status(bridge)
    assert handoff["code"] == "HANDOFF_REQUESTED"
    assert handoff["transfer_reason"] == "SYSTEM_ERROR"
    assert (handoff["preserve_business_outcome"], handoff["reconciliation_required"]) == (
        False,
        False,
    )
    assert "secret" not in json.dumps(handoff)  # không lộ message gốc của provider
    assert orchestrator.handled_turns == []
    assert orchestrator.closed_calls == [ROOM]


async def test_reply_failing_before_audio_after_a_normal_greeting_recovers() -> None:
    """Ca E local: lời chào phát được (cache), câu động đầu tiên Vbee trả 401, không có dự phòng."""
    orchestrator = _RecoveringOrchestrator(OPENING, turn_actions=[REPLY])
    tts = _BrokenTTS(fail_before_audio=[REPLY.utterance])
    turns = [UserTurnCompleted(text="14/03/1978", confidence=0.9)]
    bridge, source = _bridge(orchestrator, tts, turns)

    await asyncio.wait_for(bridge.run(), timeout=2.0)

    assert len(orchestrator.handled_turns) == 1
    assert orchestrator.tts_errors == [ROOM]
    assert len(source.captured_frames) == 1 + TRANSFER_FRAMES  # lời chào + câu ghi sẵn
    assert _bot_lines(bridge) == [OPENING.utterance, REPLY.utterance, t.TRANSFER]
    assert [status["code"] for status in _status(bridge)] == ["HANDOFF_REQUESTED"]
    assert orchestrator.closed_calls == [ROOM]


async def test_reply_cut_mid_sentence_also_recovers() -> None:
    orchestrator = _RecoveringOrchestrator(OPENING, turn_actions=[REPLY])
    tts = _BrokenTTS(cut_mid_sentence=[REPLY.utterance])
    turns = [UserTurnCompleted(text="Nguyễn Văn A", confidence=0.9)]
    bridge, source = _bridge(orchestrator, tts, turns)

    await asyncio.wait_for(bridge.run(), timeout=2.0)

    assert tts.spoken == [OPENING.utterance, REPLY.utterance]  # không gọi TTS cho câu chuyển máy
    assert orchestrator.tts_errors == [ROOM]
    # lời chào + phần câu bị cắt (mỗi câu 1 frame) + câu ghi sẵn
    assert len(source.captured_frames) == 2 + TRANSFER_FRAMES
    assert [status["code"] for status in _status(bridge)] == ["HANDOFF_REQUESTED"]
    assert orchestrator.closed_calls == [ROOM]


@pytest.mark.parametrize(
    "recovery, flags",
    [
        (TTSRecovery(t.TRANSFER, preserve_business_outcome=True), (True, False)),
        (TTSRecovery(t.TRANSFER, reconciliation_required=True), (False, True)),
    ],
)
async def test_handoff_carries_what_clinic_already_has(recovery, flags) -> None:
    """Đã ghi xong / còn lệnh chờ đối soát: khách nghe y như nhau, chỉ cờ cho nhân viên khác."""
    orchestrator = _RecoveringOrchestrator(OPENING, turn_actions=[], recovery=recovery)
    bridge, source = _bridge(orchestrator, _BrokenTTS(fail_before_audio=[OPENING.utterance]))

    await asyncio.wait_for(bridge.run(), timeout=2.0)

    assert len(source.captured_frames) == TRANSFER_FRAMES
    (handoff,) = _status(bridge)
    assert (handoff["preserve_business_outcome"], handoff["reconciliation_required"]) == flags


async def test_caller_gone_before_recovery_hears_nothing_and_gets_no_handoff() -> None:
    orchestrator = _RecoveringOrchestrator(OPENING, turn_actions=[])
    bridge, source = _bridge(orchestrator, _BrokenTTS(fail_before_audio=[OPENING.utterance]))

    def gone(call_id):
        bridge._room._handlers["participant_disconnected"](SimpleNamespace(identity="caller-1"))
        raise CallEnded(call_id)

    orchestrator.handle_tts_error = gone

    await asyncio.wait_for(bridge.run(), timeout=2.0)

    assert source.captured_frames == []
    assert _status(bridge) == []
    assert orchestrator.closed_calls == [ROOM]


async def test_missing_recorded_audio_still_hands_off(monkeypatch) -> None:
    monkeypatch.setattr(
        "callbot.transports.livekit.call_bridge.fixed_utterance_pcm", lambda text, rate: None
    )
    orchestrator = _RecoveringOrchestrator(OPENING, turn_actions=[])
    bridge, source = _bridge(orchestrator, _BrokenTTS(fail_before_audio=[OPENING.utterance]))

    await asyncio.wait_for(bridge.run(), timeout=2.0)

    assert source.captured_frames == []
    assert [status["code"] for status in _status(bridge)] == ["HANDOFF_REQUESTED"]
    assert orchestrator.closed_calls == [ROOM]


async def test_core_failure_still_hands_off_flagged_for_reconciliation() -> None:
    orchestrator = _RecoveringOrchestrator(OPENING, turn_actions=[], error=TimeoutError())
    bridge, source = _bridge(orchestrator, _BrokenTTS(fail_before_audio=[OPENING.utterance]))

    await asyncio.wait_for(bridge.run(), timeout=2.0)

    assert len(source.captured_frames) == TRANSFER_FRAMES
    (handoff,) = _status(bridge)
    assert handoff["reconciliation_required"] is True


async def test_recorded_audio_is_resampled_to_a_24khz_track() -> None:
    """Track tạo theo provider chính (OpenAI 24 kHz); asset 8 kHz phải đúng thời lượng."""

    class _Broken24k(_BrokenTTS):
        stream_sample_rate = 24000

    orchestrator = _RecoveringOrchestrator(OPENING, turn_actions=[])
    bridge, source = _bridge(orchestrator, _Broken24k(fail_before_audio=[OPENING.utterance]))

    await asyncio.wait_for(bridge.run(), timeout=2.0)

    frames = source.captured_frames
    assert len(frames) == TRANSFER_FRAMES
    assert {frame.sample_rate for frame in frames} == {24000}
    samples = sum(frame.samples_per_channel for frame in frames)
    assert abs(samples / 24000 - 21768 / 8000) < 0.01


async def test_recovery_runs_at_most_once_per_call() -> None:
    orchestrator = _RecoveringOrchestrator(OPENING, turn_actions=[])
    bridge, source = _bridge(orchestrator, _BrokenTTS())
    bridge._audio_source = source

    await bridge._recover_tts_error()
    await bridge._recover_tts_error()

    assert orchestrator.tts_errors == [ROOM]
    assert len(_status(bridge)) == 1


async def test_barge_in_is_not_a_tts_error() -> None:
    """Khách nói chen làm stream dừng giữa chừng — không được coi là TTS lỗi."""

    class _InterruptedTTS(_BrokenTTS):
        async def synthesize_stream(self, text: str):
            yield b"\x00\x10" * 160
            bridge._interruption._state = InterruptionState.INTERRUPTED
            raise RuntimeError("stream closed by cancel")

    orchestrator = _RecoveringOrchestrator(OPENING, turn_actions=[])
    bridge, _source = _bridge(orchestrator, _InterruptedTTS())
    bridge._audio_source = _source

    await bridge._speak("một câu bị ngắt lời")  # không ném TTSPlaybackError

    assert orchestrator.tts_errors == []


async def test_tts_failure_is_logged_with_its_location_but_not_the_provider_message(
    caplog,
) -> None:
    """`_speak` bắt mọi lỗi thành TTS lỗi; log phải chỉ được chỗ hỏng (để phân biệt bug code với
    provider lỗi) nhưng không chép message gốc (token, text câu nói)."""
    orchestrator = _RecoveringOrchestrator(OPENING, turn_actions=[])
    bridge, _source = _bridge(orchestrator, _BrokenTTS(fail_before_audio=[OPENING.utterance]))

    with caplog.at_level("ERROR", logger="callbot.transports.livekit.call_bridge"):
        await asyncio.wait_for(bridge.run(), timeout=2.0)

    (failed,) = [r for r in caplog.records if "TTS stream failed" in r.getMessage()]
    assert "RuntimeError" in failed.getMessage()
    assert "test_call_bridge_tts_recovery.py" in failed.getMessage()  # vị trí synthesize_stream
    assert all("secret" not in record.getMessage() for record in caplog.records)
    assert all(record.exc_info is None for record in caplog.records)


async def test_core_failure_is_logged_with_its_location(caplog) -> None:
    orchestrator = _RecoveringOrchestrator(
        OPENING, turn_actions=[], error=TimeoutError("lock call=secret")
    )
    bridge, _source = _bridge(orchestrator, _BrokenTTS(fail_before_audio=[OPENING.utterance]))

    with caplog.at_level("ERROR", logger="callbot.transports.livekit.call_bridge"):
        await asyncio.wait_for(bridge.run(), timeout=2.0)

    (failed,) = [r for r in caplog.records if "Core không xử lý được lỗi TTS" in r.getMessage()]
    assert "TimeoutError" in failed.getMessage()
    assert "test_call_bridge_tts_recovery.py" in failed.getMessage()
    assert all("secret" not in record.getMessage() for record in caplog.records)


async def test_recorded_audio_failing_to_load_still_hands_off(monkeypatch) -> None:
    """Đọc/resample asset ném lỗi bất ngờ: như thiếu audio, vẫn gửi HANDOFF_REQUESTED."""

    def broken(text, rate):
        raise OSError("disk")

    monkeypatch.setattr("callbot.transports.livekit.call_bridge.fixed_utterance_pcm", broken)
    orchestrator = _RecoveringOrchestrator(OPENING, turn_actions=[])
    bridge, source = _bridge(orchestrator, _BrokenTTS(fail_before_audio=[OPENING.utterance]))

    await asyncio.wait_for(bridge.run(), timeout=2.0)

    assert source.captured_frames == []
    assert [status["code"] for status in _status(bridge)] == ["HANDOFF_REQUESTED"]
    assert orchestrator.closed_calls == [ROOM]
