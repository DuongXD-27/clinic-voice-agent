"""CallBridge phía đầu vào: chỉ nghe mic người gọi, gửi lượt im lặng cho core khi người dùng
im quá lâu. Dùng lại fake của test_call_bridge_mapping (cùng contract)."""

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("livekit", reason="cần extra [livekit] cài livekit-agents/livekit-api")

from livekit import rtc  # noqa: E402
from tests.transports.livekit.test_call_bridge_mapping import (  # noqa: E402
    _FakeAudioSource,
    _FakeOrchestrator,
    _FakeRoom,
    _FakeTTS,
)

from callbot.engine.types import BotAction, CallerInput  # noqa: E402
from callbot.transports.livekit.call_bridge import (  # noqa: E402
    CallBridge,
    _SilenceTimeout,
    caller_input_from_turn,
)
from speech.asr.vad.base import VadEvent  # noqa: E402
from speech.turn.controller import TurnController  # noqa: E402
from speech.turn.events import UserTurnCompleted  # noqa: E402


@pytest.fixture(autouse=True)
def _run_fake_orchestrator_inline(monkeypatch):
    async def inline(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", inline)


class _ScriptedPipeline:
    """Phát các turn cho trước rồi giữ cuộc gọi mở (như mic vẫn đang stream, không ai nói)."""

    def __init__(self, turns: list[UserTurnCompleted] | None = None, on_start=None) -> None:
        self._turns = turns or []
        self._on_start = on_start

    async def stream(self, frames, turn_controller=None, **_kwargs):
        if self._on_start is not None:
            await self._on_start(turn_controller)
        for turn in self._turns:
            yield turn
        await asyncio.Event().wait()


def _bridge(orchestrator, pipeline, *, silence_timeout_ms: int, controller=None) -> CallBridge:
    bridge = CallBridge(
        _FakeRoom("web-input-room"),
        orchestrator,
        pipeline,
        _FakeTTS(),
        turn_controller=controller,
        silence_timeout_ms=silence_timeout_ms,
    )

    async def _fake_publish():
        bridge._audio_source = _FakeAudioSource()

    bridge._publish_tts_track = _fake_publish
    return bridge


def test_silent_turn_maps_to_core_silence_contract() -> None:
    """Core xác định im lặng bằng silence_ms > 0 (Phụ lục A), không bằng text rỗng."""
    caller = caller_input_from_turn(2, UserTurnCompleted(text="", silence_ms=8000))

    assert caller == CallerInput(turn=2, text=None, silence_ms=8000)
    assert caller.is_silence is True


async def test_silence_after_bot_speaks_sends_silent_turn() -> None:
    opening = BotAction(utterance="Xin chào", state="AWAITING_INTENT")
    closing = BotAction(utterance="Tạm biệt", state="ENDED", ended=True, outcome="UNREACHABLE")
    orchestrator = _FakeOrchestrator(opening=opening, turn_actions=[closing])
    bridge = _bridge(orchestrator, _ScriptedPipeline(), silence_timeout_ms=50)

    await asyncio.wait_for(bridge.run(), timeout=2.0)

    ((_, caller),) = orchestrator.handled_turns
    assert caller.text is None
    assert caller.silence_ms >= 50


async def test_silent_turn_publishes_no_empty_caller_line() -> None:
    """Lượt im lặng không có lời: UI không được hiện một bong bóng "caller" rỗng."""
    opening = BotAction(utterance="Xin chào", state="AWAITING_INTENT")
    closing = BotAction(utterance="Tạm biệt", state="ENDED", ended=True, outcome="UNREACHABLE")
    orchestrator = _FakeOrchestrator(opening=opening, turn_actions=[closing])
    bridge = _bridge(orchestrator, _ScriptedPipeline(), silence_timeout_ms=50)

    await asyncio.wait_for(bridge.run(), timeout=2.0)

    lines = [payload for payload, _, _ in bridge._room.local_participant.data]
    assert [(line["role"], line["text"]) for line in lines] == [
        ("bot", "Xin chào"),
        ("bot", "Tạm biệt"),
    ]


async def test_timer_restarts_after_each_bot_reply() -> None:
    """Lượt thật -> bot trả lời -> người dùng im: lượt thứ hai là lượt im lặng."""
    opening = BotAction(utterance="Xin chào", state="AWAITING_INTENT")
    reply = BotAction(utterance="Anh chị cần gì ạ", state="AWAITING_INTENT")
    closing = BotAction(utterance="Tạm biệt", state="ENDED", ended=True)
    orchestrator = _FakeOrchestrator(opening=opening, turn_actions=[reply, closing])
    pipeline = _ScriptedPipeline([UserTurnCompleted(text="alo")])
    bridge = _bridge(orchestrator, pipeline, silence_timeout_ms=50)

    await asyncio.wait_for(bridge.run(), timeout=2.0)

    assert [c.text for _, c in orchestrator.handled_turns] == ["alo", None]
    assert orchestrator.handled_turns[1][1].silence_ms >= 50


async def test_no_silent_turn_while_user_is_still_speaking() -> None:
    """VAD đã speech_start nhưng câu chưa chốt: người dùng đang nói, không được coi là im."""
    controller = TurnController()

    async def start_speaking(turn_controller) -> None:
        await asyncio.sleep(0.01)
        await turn_controller.on_vad_event(VadEvent("speech_start"))

    opening = BotAction(utterance="Xin chào", state="AWAITING_INTENT")
    orchestrator = _FakeOrchestrator(opening=opening, turn_actions=[])
    bridge = _bridge(
        orchestrator,
        _ScriptedPipeline(on_start=start_speaking),
        silence_timeout_ms=50,
        controller=controller,
    )

    run = asyncio.ensure_future(bridge.run())
    await asyncio.sleep(0.3)

    assert orchestrator.handled_turns == []
    run.cancel()
    await asyncio.gather(run, return_exceptions=True)


async def test_silence_disabled_by_default() -> None:
    opening = BotAction(utterance="Xin chào", state="AWAITING_INTENT")
    orchestrator = _FakeOrchestrator(opening=opening, turn_actions=[])
    bridge = _bridge(orchestrator, _ScriptedPipeline(), silence_timeout_ms=0)

    run = asyncio.ensure_future(bridge.run())
    await asyncio.sleep(0.2)

    assert orchestrator.handled_turns == []
    run.cancel()
    await asyncio.gather(run, return_exceptions=True)


async def test_stale_silence_timeout_is_ignored() -> None:
    """Hẹn giờ đã hết nhưng một lượt khác được xử lý trước: lượt im lặng cũ bị bỏ."""
    opening = BotAction(utterance="Xin chào", state="AWAITING_INTENT")
    closing = BotAction(utterance="Tạm biệt", state="ENDED", ended=True)
    orchestrator = _FakeOrchestrator(opening=opening, turn_actions=[closing])
    bridge = _bridge(orchestrator, _ScriptedPipeline(), silence_timeout_ms=0)
    stale = _SilenceTimeout(generation=bridge._silence_generation - 1, silence_ms=9000)
    await bridge._turn_queue.put(stale)
    await bridge._turn_queue.put(UserTurnCompleted(text="đặt lịch"))

    await asyncio.wait_for(bridge.run(), timeout=2.0)

    assert [c.text for _, c in orchestrator.handled_turns] == ["đặt lịch"]


def _track_bridge(monkeypatch, caller_identity: str | None) -> tuple[CallBridge, list]:
    bridge = CallBridge(
        _FakeRoom("web-track-room"),
        _FakeOrchestrator(
            opening=BotAction(utterance="", state="AWAITING_INTENT"), turn_actions=[]
        ),
        _ScriptedPipeline(),
        _FakeTTS(),
        caller_identity=caller_identity,
    )
    pumped: list = []

    async def fake_pump(track) -> None:
        pumped.append(track)
        await asyncio.Event().wait()

    monkeypatch.setattr(bridge, "_pump_track", fake_pump)
    return bridge, pumped


def _audio(name: str) -> SimpleNamespace:
    return SimpleNamespace(kind=rtc.TrackKind.KIND_AUDIO, name=name)


def _publication(source=rtc.TrackSource.SOURCE_MICROPHONE) -> SimpleNamespace:
    return SimpleNamespace(source=source)


async def test_only_caller_microphone_is_pumped(monkeypatch) -> None:
    bridge, pumped = _track_bridge(monkeypatch, caller_identity="web-caller")
    caller, other = SimpleNamespace(identity="web-caller"), SimpleNamespace(identity="web-other")
    mic, other_mic = _audio("mic"), _audio("other-mic")
    screen = _audio("screen-audio")

    bridge._on_track_subscribed(other_mic, _publication(), other)
    bridge._on_track_subscribed(
        screen, _publication(rtc.TrackSource.SOURCE_SCREENSHARE_AUDIO), caller
    )
    bridge._on_track_subscribed(mic, _publication(), caller)
    await asyncio.sleep(0)

    assert pumped == [mic]
    await bridge.aclose()


async def test_first_participant_becomes_caller_when_identity_unknown(monkeypatch) -> None:
    bridge, pumped = _track_bridge(monkeypatch, caller_identity=None)
    first, second = SimpleNamespace(identity="a"), SimpleNamespace(identity="b")
    mic_a, mic_b = _audio("a"), _audio("b")

    bridge._on_track_subscribed(mic_a, _publication(), first)
    bridge._on_track_subscribed(mic_b, _publication(), second)
    await asyncio.sleep(0)

    assert pumped == [mic_a]
    await bridge.aclose()


async def test_republished_caller_mic_replaces_previous_stream(monkeypatch) -> None:
    """Đổi thiết bị mic: luồng cũ phải dừng, không để hai luồng PCM xen kẽ vào ASR."""
    bridge, pumped = _track_bridge(monkeypatch, caller_identity="web-caller")
    caller = SimpleNamespace(identity="web-caller")
    old_mic, new_mic = _audio("old"), _audio("new")

    bridge._on_track_subscribed(old_mic, _publication(), caller)
    await asyncio.sleep(0)
    first_task = bridge._pump_task
    bridge._on_track_subscribed(new_mic, _publication(), caller)
    await asyncio.sleep(0)

    assert pumped == [old_mic, new_mic]
    assert first_task.cancelled()
    await bridge.aclose()


async def test_ingress_log_names_kind_but_never_sip_identity(monkeypatch, caplog) -> None:
    """Identity của SIP participant có thể chứa số điện thoại — log chỉ ghi loại participant
    và cờ xử lý âm thanh của trình duyệt (attribute audio.settings)."""
    bridge, _ = _track_bridge(monkeypatch, caller_identity=None)
    caller = SimpleNamespace(
        identity="sip_+84912345678",
        kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
        attributes={"audio.settings": '{"echoCancellation": true}'},
    )
    frame = SimpleNamespace(sample_rate=48_000, num_channels=1)
    segment = SimpleNamespace(pcm=b"\x10\x00" * 480, sample_rate=16_000)

    with caplog.at_level("INFO", logger="callbot.transports.livekit.call_bridge"):
        bridge._on_track_subscribed(_audio("mic"), _publication(), caller)
        bridge._observe_ingress(frame, segment)
        bridge._log_ingress_summary()

    text = caplog.text
    assert "kind=SIP" in text
    assert "source=MICROPHONE" in text
    assert 'audio_settings={"echoCancellation":true}' in text
    assert "source_rate=48000" in text
    assert "AUDIO_INGRESS_SUMMARY" in text
    assert "84912345678" not in text
    await bridge.aclose()


async def test_diagnostics_reach_pipeline_only_when_enabled() -> None:
    """Fake pipeline cũ không nhận `diagnostics` — chỉ truyền khi worker bật chẩn đoán."""
    from speech.diagnostics import SpeechDiagnostics

    seen: list[dict] = []

    class _Recording:
        async def stream(self, frames, **kwargs):
            seen.append(kwargs)
            if False:
                yield None

    for diagnostics in (None, SpeechDiagnostics()):
        bridge = CallBridge(
            _FakeRoom("web-diag"),
            _FakeOrchestrator(opening=BotAction(utterance="", state="X"), turn_actions=[]),
            _Recording(),
            _FakeTTS(),
            diagnostics=diagnostics,
        )
        await bridge._consume_turns()

    assert "diagnostics" not in seen[0]
    assert isinstance(seen[1]["diagnostics"], SpeechDiagnostics)


async def test_late_audio_settings_from_caller_are_logged(monkeypatch, caplog) -> None:
    bridge, _ = _track_bridge(monkeypatch, caller_identity=None)
    caller = SimpleNamespace(identity="web-a", kind=0, attributes={})
    other = SimpleNamespace(identity="web-b", kind=0, attributes={"audio.settings": "{}"})
    bridge._on_track_subscribed(_audio("mic"), _publication(), caller)
    caller.attributes = {"audio.settings": '{"voiceIsolation": false}'}

    with caplog.at_level("INFO", logger="callbot.transports.livekit.call_bridge"):
        bridge._on_attributes_changed({"audio.settings": "x"}, other)
        bridge._on_attributes_changed({"direction": "inbound"}, caller)
        bridge._on_attributes_changed({"audio.settings": "x"}, caller)

    lines = [r.getMessage() for r in caplog.records if "audio_settings" in r.getMessage()]
    assert lines == [
        'AUDIO_INGRESS room=web-track-room kind=STANDARD audio_settings={"voiceIsolation":false}'
    ]
    await bridge.aclose()


if __name__ == "__main__":
    pytest.main([__file__])
