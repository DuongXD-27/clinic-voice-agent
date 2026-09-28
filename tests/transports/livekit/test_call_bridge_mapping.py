import asyncio
import json
import logging

import pytest

pytest.importorskip("livekit", reason="cần extra [livekit] cài livekit-agents/livekit-api")

from callbot.engine.types import BotAction, CallerInput, CallStart  # noqa: E402
from callbot.transports.livekit.call_bridge import (  # noqa: E402
    TRANSCRIPT_TOPIC,
    CallBridge,
    call_start_from_room,
    caller_input_from_turn,
)
from speech.turn.events import UserTurnCompleted  # noqa: E402
from speech.types import AudioSegment  # noqa: E402


@pytest.fixture(autouse=True)
def _run_fake_orchestrator_inline(monkeypatch):
    """Sandbox CI không phải lúc nào cũng cho tạo thread; orchestrator ở module này
    là fake đồng bộ nên chạy inline giúp test chỉ tập trung vào CallBridge wiring."""

    async def inline(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", inline)


def test_call_start_from_room_uses_room_name_as_call_id() -> None:
    call_start = call_start_from_room("web-abc123", "web-participant-1")

    assert call_start == CallStart(
        call_id="web-abc123", direction="inbound", caller_number=None, locale="vi-VN"
    )


def test_call_start_from_room_passes_through_caller_number() -> None:
    """caller_number giả lập (từ participant attribute, xem worker.py) phải đi thẳng
    vào CallStart — nếu None thì engine đi nhánh NO_PHONE và transfer ngay lượt đầu
    (đúng chính sách), đây chính là bug thật đã gặp: demo luôn None nên luôn transfer
    ngay dù user chưa kịp nói gì."""
    call_start = call_start_from_room("web-abc123", "web-participant-1", caller_number="0912345600")

    assert call_start == CallStart(
        call_id="web-abc123",
        direction="inbound",
        caller_number="0912345600",
        locale="vi-VN",
    )


def test_call_start_from_room_outbound_carries_appointment_id() -> None:
    call_start = call_start_from_room(
        "web-abc123", "web-participant-1", direction="outbound", appointment_id="apt_00417"
    )

    assert call_start == CallStart(
        call_id="web-abc123",
        direction="outbound",
        appointment_id="apt_00417",
        locale="vi-VN",
    )


def test_caller_input_from_turn_carries_text_and_confidence() -> None:
    turn = UserTurnCompleted(text="tôi muốn đổi lịch", confidence=0.87)

    caller = caller_input_from_turn(3, turn)

    assert caller == CallerInput(
        turn=3, text="tôi muốn đổi lịch", silence_ms=0, audio_url=None, asr_confidence=0.87
    )
    assert caller.is_silence is False
    assert caller.transcript == "tôi muốn đổi lịch"


class _FakeOrchestrator:
    def __init__(self, opening: BotAction, turn_actions: list[BotAction]) -> None:
        self._opening = opening
        self._turn_actions = turn_actions
        self.started_calls: list[CallStart] = []
        self.handled_turns: list[tuple[str, CallerInput]] = []

    def start_call(self, call: CallStart) -> BotAction:
        self.started_calls.append(call)
        return self._opening

    def handle_turn(self, call_id: str, caller: CallerInput) -> BotAction:
        self.handled_turns.append((call_id, caller))
        return self._turn_actions[len(self.handled_turns) - 1]


class _FakeSTTPipeline:
    def __init__(self, turns: list[UserTurnCompleted]) -> None:
        self._turns = turns

    async def stream(
        self,
        frames,
        turn_controller=None,
        interruption=None,
        evidence_tracker=None,
        noise_tracker=None,
        noise_classifier=None,
    ):
        for turn in self._turns:
            yield turn


class _FakeTTS:
    stream_sample_rate = 24000

    def __init__(self) -> None:
        self.spoken: list[str] = []
        self.cancel_calls = 0

    def synthesize(self, text: str):
        self.spoken.append(text)
        return AudioSegment(pcm=b"\x00\x10" * 10, sample_rate=24000)

    async def synthesize_stream(self, text: str):
        self.spoken.append(text)
        yield b"\x00\x10" * 10

    async def cancel(self) -> None:
        self.cancel_calls += 1


class _FakeAudioSource:
    def __init__(self) -> None:
        self.captured_frames: list[object] = []
        self.closed = False
        self.clear_queue_calls = 0
        self.wait_for_playout_calls = 0

    async def capture_frame(self, frame) -> None:
        self.captured_frames.append(frame)

    def clear_queue(self) -> None:
        self.clear_queue_calls += 1

    async def wait_for_playout(self) -> None:
        self.wait_for_playout_calls += 1

    async def aclose(self) -> None:
        self.closed = True


class _FakeLocalParticipant:
    identity = "web-bot"

    def __init__(self) -> None:
        self.published: list[tuple[object, object]] = []
        self.data: list[tuple[dict, str, bool]] = []

    async def publish_track(self, track, options) -> None:
        self.published.append((track, options))

    async def publish_data(self, payload, *, reliable: bool = True, topic: str = "") -> None:
        self.data.append((json.loads(payload), topic, reliable))


class _FakeRoom:
    def __init__(self, name: str) -> None:
        self.name = name
        self.local_participant = _FakeLocalParticipant()
        self.remote_participants: dict[str, object] = {}
        self._handlers: dict[str, object] = {}

    def on(self, event: str, callback) -> None:
        self._handlers[event] = callback


async def test_call_bridge_run_ends_call_after_orchestrator_reports_ended(monkeypatch) -> None:
    """Kịch bản tối giản: opening không ended, 1 turn khiến orchestrator báo ended=True
    -> CallBridge phải dừng vòng lặp và cleanup, không cần LiveKit thật để test wiring."""
    opening = BotAction(utterance="Xin chào", state="AWAITING_INTENT", ended=False)
    closing = BotAction(utterance="Tạm biệt", state="ENDED", ended=True, outcome="TRANSFERRED")
    orchestrator = _FakeOrchestrator(opening=opening, turn_actions=[closing])
    stt_pipeline = _FakeSTTPipeline([UserTurnCompleted(text="tôi muốn gặp bác sĩ")])
    tts = _FakeTTS()
    room = _FakeRoom("web-test-room")

    bridge = CallBridge(room, orchestrator, stt_pipeline, tts)
    fake_source = _FakeAudioSource()

    async def _fake_publish_tts_track():
        bridge._audio_source = fake_source

    monkeypatch.setattr(bridge, "_publish_tts_track", _fake_publish_tts_track)

    await asyncio.wait_for(bridge.run(), timeout=2.0)

    assert orchestrator.started_calls == [
        CallStart(call_id="web-test-room", direction="inbound", caller_number=None, locale="vi-VN")
    ]
    assert len(orchestrator.handled_turns) == 1
    call_id, caller = orchestrator.handled_turns[0]
    assert call_id == "web-test-room"
    assert caller.text == "tôi muốn gặp bác sĩ"
    assert tts.spoken == ["Xin chào", "Tạm biệt"]
    assert len(fake_source.captured_frames) == 2
    assert fake_source.closed is True
    assert fake_source.wait_for_playout_calls == 2


async def test_call_bridge_publishes_transcript_for_each_line(monkeypatch) -> None:
    """Trang /ui/livekit hiện lời thoại từ data channel: câu chào (lượt 0), lời người gọi
    kèm độ tin cậy ASR, câu bot kèm state/outcome — theo đúng thứ tự, trước khi phát audio."""
    opening = BotAction(utterance="Xin chào", state="AWAITING_IDENTITY", ended=False)
    closing = BotAction(utterance="Tạm biệt", state="ENDED", ended=True, outcome="TRANSFERRED")
    orchestrator = _FakeOrchestrator(opening=opening, turn_actions=[closing])
    stt_pipeline = _FakeSTTPipeline([UserTurnCompleted(text="tôi là An", confidence=0.91)])
    room = _FakeRoom("web-transcript-room")
    bridge = CallBridge(room, orchestrator, stt_pipeline, _FakeTTS())

    async def _fake_publish_tts_track():
        bridge._audio_source = _FakeAudioSource()

    monkeypatch.setattr(bridge, "_publish_tts_track", _fake_publish_tts_track)

    await asyncio.wait_for(bridge.run(), timeout=2.0)

    assert [topic for _, topic, _ in room.local_participant.data] == [TRANSCRIPT_TOPIC] * 3
    assert all(reliable for _, _, reliable in room.local_participant.data)
    assert [payload for payload, _, _ in room.local_participant.data] == [
        {
            "type": "transcript",
            "role": "bot",
            "turn": 0,
            "text": "Xin chào",
            "state": "AWAITING_IDENTITY",
            "ended": False,
            "outcome": None,
        },
        {
            "type": "transcript",
            "role": "caller",
            "turn": 1,
            "text": "tôi là An",
            "confidence": 0.91,
        },
        {
            "type": "transcript",
            "role": "bot",
            "turn": 1,
            "text": "Tạm biệt",
            "state": "ENDED",
            "ended": True,
            "outcome": "TRANSFERRED",
        },
    ]


async def test_transcript_publish_failure_does_not_break_call(monkeypatch, caplog) -> None:
    class _BrokenDataParticipant(_FakeLocalParticipant):
        async def publish_data(self, payload, *, reliable: bool = True, topic: str = "") -> None:
            raise ConnectionError("tôi là An")  # nội dung lỗi có thể chứa PII: không được log

    opening = BotAction(utterance="Xin chào", state="AWAITING_INTENT", ended=False)
    closing = BotAction(utterance="Tạm biệt", state="ENDED", ended=True, outcome="TRANSFERRED")
    orchestrator = _FakeOrchestrator(opening=opening, turn_actions=[closing])
    tts = _FakeTTS()
    room = _FakeRoom("web-broken-data-room")
    room.local_participant = _BrokenDataParticipant()
    bridge = CallBridge(room, orchestrator, _FakeSTTPipeline([UserTurnCompleted(text="x")]), tts)

    async def _fake_publish_tts_track():
        bridge._audio_source = _FakeAudioSource()

    monkeypatch.setattr(bridge, "_publish_tts_track", _fake_publish_tts_track)

    with caplog.at_level(logging.WARNING, logger="callbot.transports.livekit.call_bridge"):
        await asyncio.wait_for(bridge.run(), timeout=2.0)

    assert tts.spoken == ["Xin chào", "Tạm biệt"]
    assert "ConnectionError" in caplog.text
    assert "tôi là An" not in caplog.text


async def test_speak_buffers_odd_byte_chunks_into_valid_pcm16_frames(monkeypatch) -> None:
    """TTS streaming cắt chunk theo byte HTTP tuỳ ý, có thể để lẻ giữa 1 sample PCM16
    (2 byte). rtc.AudioFrame thật (không phải fake) raise ValueError nếu len(data) lẻ —
    bug từng làm job LiveKit crash thật khi test qua trình duyệt. _speak() phải giữ byte
    lẻ lại cho chunk kế tiếp, không publish frame không hợp lệ."""
    pytest.importorskip("livekit", reason="cần extra [livekit] cài livekit-agents/rtc")
    from livekit import rtc

    class _OddByteTTS(_FakeTTS):
        async def synthesize_stream(self, text: str):
            self.spoken.append(text)
            yield b"\x01\x02\x03"  # 3 byte lẻ — sample thứ 2 chưa đủ byte cao
            yield b"\x04\x05\x06\x07"  # byte đầu (\x04) ghép với \x03 còn lại ở trên

    opening = BotAction(utterance="câu có byte lẻ", state="AWAITING_INTENT", ended=False)
    orchestrator = _FakeOrchestrator(opening=opening, turn_actions=[])
    stt_pipeline = _FakeSTTPipeline([])
    tts = _OddByteTTS()
    room = _FakeRoom("web-odd-byte-room")

    bridge = CallBridge(room, orchestrator, stt_pipeline, tts)
    real_source = rtc.AudioSource(sample_rate=24000, num_channels=1)
    bridge._audio_source = real_source

    # Không raise ValueError là điều kiện chính cần xác nhận (SDK thật validate strict).
    await bridge._speak(opening.utterance)

    await real_source.aclose()


async def test_speak_stops_publishing_and_clears_queue_when_interrupted(monkeypatch) -> None:
    """Barge-in giữa chừng _speak(): interruption chuyển INTERRUPTED sau chunk đầu tiên
    -> CallBridge phải dừng publish chunk còn lại VÀ gọi clear_queue()."""
    from speech.turn.interruption import InterruptionState

    class _MultiChunkTTS(_FakeTTS):
        async def synthesize_stream(self, text: str):
            self.spoken.append(text)
            yield b"\x00\x10" * 10
            yield b"\x00\x20" * 10
            yield b"\x00\x30" * 10

    opening = BotAction(utterance="Câu chào dài nhiều chunk", state="AWAITING_INTENT", ended=False)
    orchestrator = _FakeOrchestrator(opening=opening, turn_actions=[])
    stt_pipeline = _FakeSTTPipeline([])
    tts = _MultiChunkTTS()
    room = _FakeRoom("web-barge-in-room")

    bridge = CallBridge(room, orchestrator, stt_pipeline, tts)
    fake_source = _FakeAudioSource()
    bridge._audio_source = fake_source

    original_capture = fake_source.capture_frame

    async def _capture_then_interrupt(frame):
        await original_capture(frame)
        if len(fake_source.captured_frames) == 1:
            bridge._interruption._state = InterruptionState.INTERRUPTED

    monkeypatch.setattr(fake_source, "capture_frame", _capture_then_interrupt)

    await bridge._speak(opening.utterance)

    assert len(fake_source.captured_frames) == 1  # chỉ chunk đầu, 2 chunk sau bị bỏ qua
    assert fake_source.clear_queue_calls == 1


async def test_speak_times_out_instead_of_hanging_forever_on_wait_for_playout(monkeypatch) -> None:
    """Bug thật đã gặp qua LiveKit: track TTS không được browser subscribe/consume (mất
    kết nối, tab đóng đột ngột) khiến AudioSource.wait_for_playout() không bao giờ
    resolve — cuộc gọi bị khoá vô thời hạn (quan sát: 56s im lặng rồi room mới tự
    ngắt). _speak() phải luôn tự giải phóng sau _PLAYOUT_TIMEOUT_S, không chờ mãi."""
    import callbot.transports.livekit.call_bridge as call_bridge_module

    monkeypatch.setattr(call_bridge_module, "_PLAYOUT_TIMEOUT_S", 0.05)

    class _HangingAudioSource(_FakeAudioSource):
        async def wait_for_playout(self) -> None:
            self.wait_for_playout_calls += 1
            await asyncio.Future()  # không bao giờ resolve — giả lập treo vô hạn thật

    opening = BotAction(utterance="Câu chào", state="AWAITING_INTENT", ended=False)
    orchestrator = _FakeOrchestrator(opening=opening, turn_actions=[])
    stt_pipeline = _FakeSTTPipeline([])
    tts = _FakeTTS()
    room = _FakeRoom("web-hanging-playout-room")

    bridge = CallBridge(room, orchestrator, stt_pipeline, tts)
    fake_source = _HangingAudioSource()
    bridge._audio_source = fake_source

    await asyncio.wait_for(bridge._speak(opening.utterance), timeout=2.0)

    assert fake_source.wait_for_playout_calls == 1


async def test_call_bridge_stops_immediately_if_opening_already_ends_call(monkeypatch) -> None:
    opening = BotAction(utterance="Xin lỗi, hệ thống bận", state="ENDED", ended=True)
    orchestrator = _FakeOrchestrator(opening=opening, turn_actions=[])
    stt_pipeline = _FakeSTTPipeline([UserTurnCompleted(text="không nên xử lý turn này")])
    tts = _FakeTTS()
    room = _FakeRoom("web-busy-room")

    bridge = CallBridge(room, orchestrator, stt_pipeline, tts)
    fake_source = _FakeAudioSource()

    async def _fake_publish_tts_track():
        bridge._audio_source = fake_source

    monkeypatch.setattr(bridge, "_publish_tts_track", _fake_publish_tts_track)

    await asyncio.wait_for(bridge.run(), timeout=2.0)

    assert orchestrator.handled_turns == []
    assert tts.spoken == ["Xin lỗi, hệ thống bận"]


if __name__ == "__main__":
    pytest.main([__file__])


# --- R-01: cùng Output Guard với HTTP ------------------------------------------------------


def _real_bridge(monkeypatch, room_name: str, lines: list[str]):
    from callbot.engine import create_orchestrator
    from clinic_mock_sim import FakeClinicAPI

    clinic = FakeClinicAPI()
    orchestrator = create_orchestrator(clinic)
    tts = _FakeTTS()
    bridge = CallBridge(
        _FakeRoom(room_name),
        orchestrator,
        _FakeSTTPipeline([UserTurnCompleted(text=line) for line in lines]),
        tts,
        direction="outbound",
        appointment_id="apt_00417",
    )

    async def _fake_publish_tts_track():
        bridge._audio_source = _FakeAudioSource()

    monkeypatch.setattr(bridge, "_publish_tts_track", _fake_publish_tts_track)
    return bridge, orchestrator, clinic, tts


async def test_blocked_opening_is_never_spoken(monkeypatch) -> None:
    from callbot.engine.dialogue import outbound
    from callbot.engine.errors import CallStartBlocked

    monkeypatch.setattr(
        outbound,
        "opening",
        lambda ctx, verifier: BotAction(
            "Lịch khám của anh chị lúc 9 giờ sáng", "AWAITING_IDENTITY"
        ),
    )
    bridge, orchestrator, clinic, tts = _real_bridge(monkeypatch, "web-r01-open", [])
    spoken: list[str] = []

    async def _speak(text: str) -> None:
        spoken.append(text)

    monkeypatch.setattr(bridge, "_speak", _speak)

    with pytest.raises(CallStartBlocked):
        await asyncio.wait_for(bridge.run(), timeout=2.0)
    assert spoken == [] and tts.spoken == []
    assert orchestrator.sessions.store.get_session("web-r01-open") is None
    assert clinic.writes == []


async def test_in_turn_violation_speaks_the_guarded_utterance(monkeypatch) -> None:
    """Parity với HTTP (test_calls): TTS nhận đúng câu an toàn mà HTTP trả về."""
    from callbot.engine.dialogue import templates as t

    monkeypatch.setattr(
        t, "confirmed", lambda ctx, appointment: "Dạ, em đã xác nhận lịch khoa Tim mạch ạ."
    )
    bridge, _, clinic, tts = _real_bridge(
        monkeypatch, "web-r01-parity", ["Nguyễn Văn A", "14/03/1978", "vâng"]
    )

    await asyncio.wait_for(bridge.run(), timeout=2.0)

    assert tts.spoken[0] == t.GREETING_OUTBOUND
    assert tts.spoken[-1] == t.DONE_SAFE["CONFIRMED"]
    assert clinic.writes == [("apt_00417", "CONFIRMED", {})]
