import asyncio
import base64
import json
from collections.abc import AsyncIterator

import numpy as np
import pytest

from callbot.transports.livekit.settings import LiveKitSettings
from inference.asr import ASRGateway, create_asr_gateway
from inference.asr.config import GeminiLiveASRConfig
from inference.asr.providers.gemini_live import LIVE_WS_URL, GeminiLiveASR
from speech.asr.pipeline import STTPipeline
from speech.asr.recognizer import SpeechRecognizer
from speech.asr.stream_context import ASRStreamContext
from speech.asr.vad.async_stream import AsyncStreamingVAD
from speech.asr.vad.energy import EnergyFrameClassifier
from speech.turn.controller import TurnController
from speech.types import AsrSegmentEnd

_VOICE = b"\x00\x10" * 480  # 30 ms @ 16 kHz
_SILENCE = b"\x00\x00" * 480


class _Socket:
    def __init__(self, *, text="không đồng ý", final_gate=None, setup_error=None):
        self.messages = []
        self.replies = asyncio.Queue()
        self.ended = asyncio.Event()
        self.closed = False
        self.text = text
        self.final_gate = final_gate
        self.setup_error = setup_error
        self.final_task = None
        self.partial_sent = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True
        if self.final_task is not None:
            self.final_task.cancel()
            await asyncio.gather(self.final_task, return_exceptions=True)

    async def recv(self):
        return json.dumps(await self.replies.get())

    async def send(self, raw):
        message = json.loads(raw)
        self.messages.append(message)
        if "setup" in message:
            self.replies.put_nowait(self.setup_error or {"setupComplete": {}})
        realtime = message.get("realtimeInput", {})
        if "audio" in realtime and not self.partial_sent:
            self.partial_sent = True
            self.replies.put_nowait(
                {"serverContent": {"interimInputTranscription": {"text": "đồng ý"}}}
            )
        if "activityEnd" in realtime:
            self.ended.set()
            self.final_task = asyncio.create_task(self._final())

    async def _final(self):
        if self.final_gate is not None:
            await self.final_gate.wait()
        reply = {"serverContent": {"inputTranscription": {"text": self.text}}}
        self.replies.put_nowait(reply)
        self.replies.put_nowait(reply)  # Duplicate callbacks must not duplicate engine turns.

    @property
    def audio(self):
        return b"".join(
            base64.b64decode(message["realtimeInput"]["audio"]["data"])
            for message in self.messages
            if "audio" in message.get("realtimeInput", {})
        )


class _Connector:
    def __init__(self, *sockets):
        self.sockets = list(sockets)
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.sockets[len(self.calls) - 1]


def _provider(*sockets, **config):
    connector = _Connector(*sockets)
    provider = GeminiLiveASR(
        GeminiLiveASRConfig(api_key="test-key", _env_file=None, **config), connect=connector
    )
    return provider, connector


async def _frames(items) -> AsyncIterator:
    for item in items:
        yield item
        await asyncio.sleep(0)


async def _collect(iterator):
    return [item async for item in iterator]


async def test_stream_preserves_final_equal_to_partial_and_repeated_turns():
    first, second = _Socket(text="đồng ý"), _Socket(text="đồng ý")
    provider, connector = _provider(first, second)
    events = await _collect(
        provider.stream(
            _frames([_VOICE] * 5 + [_SILENCE] * 2 + [_VOICE] * 5 + [_SILENCE] * 2),
            end_silence_ms=60,
        )
    )
    assert [(event.text, event.is_final) for event in events] == [
        ("đồng ý", False),
        ("đồng ý", True),
        ("đồng ý", False),
        ("đồng ý", True),
    ]
    assert [event.segment_id for event in events] == [1, 1, 2, 2]
    assert all(event.confidence is None for event in events)
    assert all(socket.closed for socket in (first, second))
    url, kwargs = connector.calls[0]
    assert url == LIVE_WS_URL and "test-key" not in url
    assert kwargs["additional_headers"] == {"x-goog-api-key": "test-key"}
    setup = first.messages[0]["setup"]
    assert setup["model"] == "models/gemini-3.5-transcribe-live"
    assert setup["generationConfig"]["responseModalities"] == ["TEXT"]
    assert setup["inputAudioTranscription"] == {"languageCodes": ["vi-VN"], "mode": "VERBATIM"}
    assert setup["realtimeInputConfig"]["automaticActivityDetection"]["disabled"] is True


async def test_short_turn_and_onset_audio_are_not_truncated():
    class _LateOnset:
        def is_speech(self, frame):
            return frame is _VOICE

    prefix = b"\x10\x00" * 480
    socket = _Socket(text="không")
    provider, _ = _provider(socket)
    events = await _collect(
        provider.stream(
            _frames([prefix] * 4 + [_VOICE]),
            silence_classifier=_LateOnset(),
        )
    )
    assert socket.audio == prefix * 4 + _VOICE
    assert events[-1].is_final and events[-1].text == "không"


async def test_stateful_8k_resampling_keeps_all_samples_and_flushes_remainder():
    socket = _Socket()
    provider, _ = _provider(socket)
    source = (np.sin(np.arange(2160) * 2 * np.pi * 440 / 8000) * 10000).astype("<i2")
    frames = [source[index : index + 240].tobytes() for index in range(0, len(source), 240)]
    await _collect(provider.stream(_frames(frames), audio_sample_rate=8000))
    result = np.frombuffer(socket.audio, dtype="<i2")
    assert len(result) == len(source) * 2
    # The phase must remain continuous across 30 ms input and 100 ms network chunks.
    expected = np.sin(np.arange(len(result)) * 2 * np.pi * 440 / 16000) * 10000
    assert np.mean(np.abs(result[100:-100] - expected[100:-100])) < 5
    assert all(
        message["realtimeInput"]["audio"]["mimeType"] == "audio/pcm;rate=16000"
        for message in socket.messages
        if "audio" in message.get("realtimeInput", {})
    )


async def test_discard_closes_old_socket_and_never_commits_its_audio():
    first, second = _Socket(text="hủy lịch"), _Socket(text="giữ lịch")
    provider, _ = _provider(first, second)
    events = await _collect(
        provider.stream(_frames([_VOICE] * 4 + [AsrSegmentEnd.DISCARD] + [_VOICE] * 4))
    )
    assert all(event.text != "hủy lịch" for event in events)
    assert [(event.text, event.is_final) for event in events if event.is_final] == [
        ("giữ lịch", True)
    ]
    assert not first.ended.is_set() and first.closed
    assert second.ended.is_set() and second.closed


async def test_noise_only_does_not_open_paid_session():
    provider, connector = _provider()
    assert await _collect(provider.stream(_frames([_SILENCE] * 30))) == []
    assert connector.calls == []


async def test_missing_final_raises_instead_of_committing_partial():
    socket = _Socket(final_gate=asyncio.Event())
    provider, _ = _provider(socket, final_timeout_s=0.01)
    with pytest.raises(RuntimeError, match="timed out waiting for final"):
        await _collect(provider.stream(_frames([_VOICE] * 4)))
    assert socket.closed


async def test_setup_rejection_is_explicit_and_does_not_leak_payload():
    socket = _Socket(setup_error={"error": {"code": 404, "message": "secret caller text"}})
    provider, _ = _provider(socket)
    with pytest.raises(RuntimeError, match="code=404") as error:
        await _collect(provider.stream(_frames([_VOICE])))
    assert "secret caller text" not in str(error.value)
    assert socket.closed


async def test_cancellation_while_waiting_final_closes_socket_and_pending_state():
    socket = _Socket(final_gate=asyncio.Event())
    provider, _ = _provider(socket)
    context = ASRStreamContext()
    task = asyncio.create_task(
        _collect(provider.stream(_frames([_VOICE] * 4), stream_context=context))
    )
    await asyncio.wait_for(socket.ended.wait(), timeout=1)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert socket.closed and not context.pending


def _pipeline(provider):
    recognizer = SpeechRecognizer(ASRGateway(provider, provider_name="gemini_live"))
    return STTPipeline(
        recognizer,
        AsyncStreamingVAD(EnergyFrameClassifier(), end_silence_ms=60),
        sample_rate=16000,
        queue_max_frames=50,
        asr_queue_max_frames=1000,
        barge_in_preroll_frames=17,
        asr_stream_options={"audio_sample_rate": 16000, "end_silence_ms": 60},
    )


async def test_pipeline_waits_for_remote_final_after_local_queue_is_empty():
    release_final, release_input = asyncio.Event(), asyncio.Event()
    socket = _Socket(final_gate=release_final)
    provider, _ = _provider(socket)
    controller = TurnController(
        min_speech_ms=0,
        post_bot_guard_ms=0,
        max_wait_after_vad_end_ms=1,
    )

    async def input_frames():
        async for frame in _frames([_VOICE] * 5 + [_SILENCE] * 2):
            yield frame
        await release_input.wait()

    stream = _pipeline(provider).stream(input_frames(), turn_controller=controller)
    next_turn = asyncio.create_task(anext(stream))
    try:
        await asyncio.wait_for(socket.ended.wait(), timeout=1)
        await asyncio.sleep(0.02)
        assert not next_turn.done()
        assert controller._asr_pending() is True
        release_final.set()
        turn = await asyncio.wait_for(next_turn, timeout=1)
        assert turn.text == "không đồng ý" and turn.confidence is None
        release_input.set()
        assert await _collect(stream) == []
    finally:
        next_turn.cancel()
        await asyncio.gather(next_turn, return_exceptions=True)
        await stream.aclose()


async def test_late_final_cannot_be_attached_to_next_vad_segment():
    release = asyncio.Event()
    first, second = _Socket(text="hủy lịch", final_gate=release), _Socket(text="tôi giữ lịch")
    provider, _ = _provider(first, second)
    controller = TurnController(min_speech_ms=0, post_bot_guard_ms=0)

    async def input_frames():
        async for frame in _frames([_VOICE] * 5 + [_SILENCE] * 2):
            yield frame
        await first.ended.wait()
        async for frame in _frames([_VOICE] * 5):
            yield frame
        release.set()
        async for frame in _frames([_SILENCE] * 2):
            yield frame

    turns = await asyncio.wait_for(
        _collect(_pipeline(provider).stream(input_frames(), turn_controller=controller)), timeout=2
    )
    assert [turn.text for turn in turns] == ["tôi giữ lịch"]


def test_factory_and_livekit_override_keep_batch_provider_separate(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("LIVEKIT_ASR_PROVIDER", "gemini_live")
    settings = LiveKitSettings(_env_file=None)
    assert settings.asr_provider == "gemini_live"
    gateway = create_asr_gateway(settings.asr_provider)
    assert gateway.model == "gemini-3.5-transcribe-live"
    assert SpeechRecognizer(gateway).supports_stream_context is True
    with pytest.raises(NotImplementedError, match="LIVEKIT_ASR_PROVIDER"):
        gateway.transcribe(_VOICE, 16000)
    monkeypatch.setenv("LIVEKIT_ASR_PROVIDER", "")
    assert LiveKitSettings(_env_file=None).asr_provider is None


def test_missing_key_fails_before_streaming():
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        GeminiLiveASR(GeminiLiveASRConfig(api_key="", _env_file=None))


async def test_bot_start_invalidates_remote_commit_without_waiting_for_its_final():
    first = _Socket(text="hủy lịch", final_gate=asyncio.Event())
    second = _Socket(text="tôi giữ lịch")
    provider, _ = _provider(first, second, final_timeout_s=2)
    controller = TurnController(min_speech_ms=0, post_bot_guard_ms=0)

    async def input_frames():
        async for frame in _frames([_VOICE] * 5 + [_SILENCE] * 2):
            yield frame
        await first.ended.wait()
        controller.on_bot_speaking_changed(True)
        yield _SILENCE
        # Fanout sends DISCARD and invalidates the pending server commit here.
        controller.on_bot_speaking_changed(False)
        async for frame in _frames([_VOICE] * 5 + [_SILENCE] * 2):
            yield frame

    turns = await asyncio.wait_for(
        _collect(_pipeline(provider).stream(input_frames(), turn_controller=controller)), timeout=1
    )
    assert [turn.text for turn in turns] == ["tôi giữ lịch"]
    assert first.closed and second.closed


async def test_connection_check_uploads_no_audio():
    socket = _Socket()
    provider, _ = _provider(socket)
    await provider.check_connection()
    assert socket.closed and socket.audio == b""


async def test_bundle_uses_main_streaming_configuration(monkeypatch):
    from speech import bundle as speech_bundle
    from speech.settings import SpeechSettings

    socket = _Socket(text="không")
    provider, _ = _provider(socket)
    recognizer = SpeechRecognizer(ASRGateway(provider, provider_name="gemini_live"))
    monkeypatch.setattr(speech_bundle, "create_tts_gateway", lambda *args, **kwargs: object())
    settings = SpeechSettings(
        asr_provider="gemini_live",
        vad_provider="energy",
        turn_validator_enabled=False,
        turn_min_speech_ms=0,
        turn_post_bot_guard_ms=0,
        _env_file=None,
    )
    livekit = LiveKitSettings(_env_file=None)
    bundle = speech_bundle.build_streaming_bundle(
        settings,
        asr=recognizer,
        sample_rate=16000,
        frame_ms=livekit.frame_ms,
        input_queue_ms=livekit.input_queue_ms,
        asr_queue_ms=livekit.asr_queue_ms,
        barge_in_preroll_ms=livekit.barge_in_preroll_ms,
    )
    assert bundle.stt_pipeline.provider_name == "gemini_live"
    assert bundle.stt_pipeline.model == "gemini-3.5-transcribe-live"
    turns = await _collect(
        bundle.stt_pipeline.stream(
            _frames([_VOICE] * 5 + [_SILENCE] * 20),
            turn_controller=bundle.turn_controller,
        )
    )
    assert [turn.text for turn in turns] == ["không"]


def test_livekit_prewarm_uses_override_without_batch_call(monkeypatch):
    from types import SimpleNamespace

    from callbot.transports.livekit import worker

    monkeypatch.setenv("ASR_PROVIDER", "zipformer")
    monkeypatch.setenv("LIVEKIT_ASR_PROVIDER", "gemini_live")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    proc = SimpleNamespace(userdata={})
    worker.prewarm(proc)
    recognizer = proc.userdata[worker._PREWARMED_ASR]
    assert recognizer.name == "gemini_live"
    assert recognizer.model == "gemini-3.5-transcribe-live"


async def test_prepaid_credit_error_is_actionable_without_leaking_upstream_reason():
    from websockets.exceptions import ConnectionClosedError
    from websockets.frames import Close

    class _NoCredits(_Socket):
        async def recv(self):
            raise ConnectionClosedError(
                Close(1011, "Your prepayment credits are depleted. test-key"), None
            )

    socket = _NoCredits()
    provider, _ = _provider(socket)
    with pytest.raises(RuntimeError, match="prepayment credits are depleted") as error:
        await provider.check_connection()
    assert "test-key" not in str(error.value)
    assert socket.closed
