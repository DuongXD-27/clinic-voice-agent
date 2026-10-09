import asyncio
import base64
import json
from collections.abc import AsyncIterator
from types import SimpleNamespace

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
    def __init__(
        self, *, text="không đồng ý", final_gate=None, setup_error=None, activity_end=False
    ):
        self.messages = []
        self.replies = asyncio.Queue()
        self.ended = asyncio.Event()
        self.closed = False
        self.text = text
        self.final_gate = final_gate
        self.setup_error = setup_error
        # transcribe-live thật: không có turnComplete; text=None là đoạn không có lời.
        self.activity_end = activity_end
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
        end = {"voiceActivity": {"type": "ACTIVITY_END"}}
        if self.text is not None:
            reply = {"serverContent": {"inputTranscription": {"text": self.text}}}
            if self.activity_end:
                reply = {**reply, **end}
            self.replies.put_nowait(reply)
            self.replies.put_nowait(reply)  # Duplicate callbacks must not duplicate engine turns.
        elif self.activity_end:
            self.replies.put_nowait(end)

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
        # Socket mở sẵn cho đoạn sau cùng không bao giờ được dùng.
        return (
            self.sockets[len(self.calls) - 1] if len(self.calls) <= len(self.sockets) else _Socket()
        )


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


async def test_transport_preroll_is_not_trimmed_before_remote_speech_onset():
    from speech.asr.stream_context import StreamingFrame

    socket = _Socket()
    provider, _ = _provider(socket)
    prefix = [bytes((marker, 0)) * 480 for marker in range(1, 17)]
    items = [StreamingFrame(pcm, 0, 0, is_preroll=True) for pcm in prefix]
    items += [_SILENCE] * 8 + [_VOICE] * 5
    events = await _collect(provider.stream(_frames(items)))

    assert events[-1].is_final
    assert socket.audio == b"".join(prefix + [_SILENCE] * 8 + [_VOICE] * 5)


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


async def test_noise_only_sends_no_audio_and_closes_prewarmed_socket():
    spare = _Socket()
    provider, _ = _provider(spare)
    assert await _collect(provider.stream(_frames([_SILENCE] * 30))) == []
    assert all("realtimeInput" not in message for message in spare.messages)
    assert spare.closed


@pytest.fixture
def zipformer_loads(monkeypatch):
    """Mọi lần dựng ZipFormer: chọn Gemini thì không được nạp hay gọi model khác."""
    created = []

    class _RecordingZipFormer:
        def __init__(self, *args, **kwargs) -> None:
            created.append(args)

    monkeypatch.setattr("inference.asr.providers.zipformer.ZipFormerASR", _RecordingZipFormer)
    return created


async def test_segment_without_words_settles_on_activity_end():
    socket = _Socket(text=None, activity_end=True)
    provider, _ = _provider(socket, final_timeout_s=30)

    events = await asyncio.wait_for(_collect(provider.stream(_frames([_VOICE] * 4))), 1)

    assert [(event.text, event.is_final) for event in events][-1] == ("", True)
    assert socket.closed


async def test_final_sharing_a_message_with_activity_end_is_kept_once():
    socket = _Socket(text="đồng ý", activity_end=True)
    provider, _ = _provider(socket)

    events = await _collect(provider.stream(_frames([_VOICE] * 4)))

    assert [event.text for event in events if event.is_final] == ["đồng ý"]


async def test_socket_is_set_up_before_the_caller_starts_speaking():
    socket = _Socket(text="đồng ý")
    provider, _ = _provider(socket)
    setup_before_speech = []

    async def frames():
        for _ in range(5):
            yield _SILENCE
            await asyncio.sleep(0)
        setup_before_speech.append(any("setup" in message for message in socket.messages))
        for _ in range(4):
            yield _VOICE

    events = await _collect(provider.stream(frames()))

    assert setup_before_speech == [True]
    assert events[-1].text == "đồng ý" and events[-1].is_final


async def test_idle_prewarmed_socket_is_replaced_before_server_drops_it(monkeypatch):
    from inference.asr.providers import gemini_live

    monkeypatch.setattr(gemini_live, "_SPARE_MAX_AGE_S", 0.05)
    stale, fresh = _Socket(text="cũ"), _Socket(text="đồng ý")
    provider, _ = _provider(stale, fresh)

    async def frames():
        yield _SILENCE
        await asyncio.sleep(0.1)
        yield _SILENCE  # quá tuổi: thay socket trong lúc im lặng
        for _ in range(4):
            yield _VOICE

    events = await _collect(provider.stream(frames()))

    assert stale.closed and all("realtimeInput" not in m for m in stale.messages)
    assert [event.text for event in events if event.is_final] == ["đồng ý"]


async def test_missing_final_drops_only_that_segment_instead_of_committing_partial():
    socket = _Socket(final_gate=asyncio.Event())
    provider, _ = _provider(socket, final_timeout_s=0.01)

    events = await _collect(provider.stream(_frames([_VOICE] * 4)))

    assert [event.text for event in events if event.is_final] == [""]
    assert socket.closed


async def test_gemini_final_landing_as_the_segment_times_out_is_the_only_final(monkeypatch):
    """Final của Gemini tới đúng lúc đoạn hết hạn chờ: giữ final đó, không phát thêm final rỗng."""
    from inference.asr.providers import gemini_live

    gate = asyncio.Event()
    stop_receiving = gemini_live._LiveTurn.stop_receiving

    async def final_lands_first(self):
        gate.set()
        for _ in range(10):
            await asyncio.sleep(0)  # luồng nhận kịp phát final trước khi bị dừng
        await stop_receiving(self)

    monkeypatch.setattr(gemini_live._LiveTurn, "stop_receiving", final_lands_first)
    provider, _ = _provider(_Socket(text="bản gemini", final_gate=gate), final_timeout_s=0.01)

    events = await _collect(provider.stream(_frames([_VOICE] * 4)))

    assert [event.text for event in events if event.is_final] == ["bản gemini"]


async def test_failed_segment_is_dropped_and_next_segment_uses_gemini_again(zipformer_loads):
    rejected = _Socket(setup_error={"error": {"code": 503}})
    healthy = _Socket(text="đồng ý")
    provider, connector = _provider(rejected, healthy)
    frames = _frames([_VOICE] * 4 + [_SILENCE] * 3 + [_VOICE] * 4 + [_SILENCE] * 3)

    events = await _collect(provider.stream(frames, end_silence_ms=60))

    assert [event.text for event in events if event.is_final] == ["", "đồng ý"]
    assert len(connector.calls) == 3  # + socket mở sẵn cho đoạn sau
    assert rejected.closed and healthy.closed
    assert zipformer_loads == []


async def test_gemini_failing_segment_after_segment_stops_with_a_safe_error():
    """Gemini không dùng được (sai key/model, hết credit): đủ `_MAX_FAILED_SEGMENTS` đoạn lỗi
    liên tiếp thì dừng luồng STT, lỗi không lộ payload của server."""
    from inference.asr.providers.gemini_live import _MAX_FAILED_SEGMENTS

    rejected = [
        _Socket(setup_error={"error": {"code": 404, "message": "secret caller text"}})
        for _ in range(_MAX_FAILED_SEGMENTS)
    ]
    provider, _ = _provider(*rejected)
    frames = _frames(([_VOICE] * 4 + [_SILENCE] * 3) * _MAX_FAILED_SEGMENTS)
    finals = []

    with pytest.raises(RuntimeError, match="code=404") as error:
        async for event in provider.stream(frames, end_silence_ms=60):
            if event.is_final:
                finals.append(event.text)

    assert finals == [""] * _MAX_FAILED_SEGMENTS  # mỗi đoạn lỗi vẫn được chốt, lượt không treo
    assert "secret caller text" not in str(error.value)
    assert all(socket.closed for socket in rejected)


def test_warm_up_neither_calls_gemini_nor_loads_another_model(zipformer_loads):
    from speech.bundle import warm_up

    provider, connector = _provider()

    warm_up(SpeechRecognizer(ASRGateway(provider, provider_name="gemini_live")))

    assert connector.calls == []
    assert zipformer_loads == []


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


async def test_late_final_of_previous_segment_stays_in_the_same_turn():
    """Đoạn sau bắt đầu trước khi final của đoạn trước tới: final đó vẫn thuộc lượt, đứng
    trước đoạn sau (bug 06/10: bỏ final này làm mất tên người gọi)."""
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
    assert [turn.text for turn in turns] == ["hủy lịch tôi giữ lịch"]


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
    # TTS không dùng trong test này; bundle chỉ cần biết tên provider (cache TTS tĩnh của main).
    fake_tts = SimpleNamespace(provider_name="fake")
    monkeypatch.setattr(speech_bundle, "create_tts_gateway", lambda *args, **kwargs: fake_tts)
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


def test_livekit_prewarm_uses_override_without_batch_call(monkeypatch, zipformer_loads):
    from callbot.transports.livekit import worker

    monkeypatch.setenv("ASR_PROVIDER", "zipformer")
    monkeypatch.setenv("LIVEKIT_ASR_PROVIDER", "gemini_live")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    proc = SimpleNamespace(userdata={})
    worker.prewarm(proc)
    recognizer = proc.userdata[worker._PREWARMED_ASR]
    assert recognizer.name == "gemini_live"
    assert recognizer.model == "gemini-3.5-transcribe-live"
    assert zipformer_loads == []  # worker chạy Gemini thì không nạp ZipFormer


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


async def test_sentence_split_at_max_length_keeps_the_first_part():
    """Câu dài bị tách ở max_turn_speech_ms: phần sau cùng segment_id, final của nó từng ghi
    đè phần trước — lượt chỉ còn "phần hai"."""
    provider, _ = _provider(
        _Socket(text="phần một"), _Socket(text="phần hai"), max_turn_speech_ms=90
    )

    events = await _collect(
        provider.stream(_frames([_VOICE] * 5 + [_SILENCE] * 3), end_silence_ms=60)
    )

    assert [(event.text, event.segment_id) for event in events if event.is_final] == [
        ("phần một phần hai", 1)
    ]
    assert {event.segment_id for event in events} == {1}


async def test_caller_stopping_right_at_the_split_still_gets_a_final():
    provider, _ = _provider(
        _Socket(text="phần một"), _Socket(text=None, activity_end=True), max_turn_speech_ms=90
    )

    events = await _collect(provider.stream(_frames([_VOICE] * 3)))

    assert [event.text for event in events if event.is_final] == ["phần một"]
