import math

import httpx
import pytest

from inference.asr import ASRGateway, ASRResult, create_asr_gateway
from inference.asr.config import GeminiASRConfig, ZipFormerConfig
from inference.asr.providers.zipformer import ZipFormerASR
from inference.common.errors import UnsupportedProviderError
from inference.tts import TTSGateway, TTSResult, create_tts_gateway
from inference.tts.config import ElevenLabsTTSConfig, VbeeTTSConfig
from inference.tts.providers.vbee import VbeeTTS
from speech.asr.recognizer import SpeechRecognizer
from speech.bundle import SpeechSynthesizer
from speech.types import WIDEBAND_RATE, AudioSegment


class _FakeStream:
    def __init__(self, text: str) -> None:
        self.result = type("Result", (), {"text": text})()
        self.accepted: tuple[int, object] | None = None

    def accept_waveform(self, sample_rate: int, samples: object) -> None:
        self.accepted = (sample_rate, samples)


class _FakeRecognizer:
    def __init__(self, text: str = "xin chào") -> None:
        self._text = text
        self.decoded: list[_FakeStream] = []

    def create_stream(self) -> _FakeStream:
        return _FakeStream(self._text)

    def decode_stream(self, stream: _FakeStream) -> None:
        self.decoded.append(stream)


def _zipformer(fake: _FakeRecognizer) -> ASRGateway:
    config = ZipFormerConfig(
        encoder_path="encoder.onnx",
        decoder_path="decoder.onnx",
        joiner_path="joiner.onnx",
        tokens_path="tokens.txt",
        _env_file=None,
    )
    return ASRGateway(ZipFormerASR(config, recognizer=fake), provider_name="zipformer")


def test_zipformer_gateway_exposes_provider_and_model() -> None:
    gateway = _zipformer(_FakeRecognizer())
    assert gateway.provider_name == "zipformer"
    assert gateway.model == "g-group-ai-lab/gipformer1.5-68M-rnnt"
    assert gateway.input_sample_rate == WIDEBAND_RATE


def test_gateway_rejects_audio_at_wrong_sample_rate() -> None:
    fake = _FakeRecognizer()
    with pytest.raises(ValueError):
        _zipformer(fake).transcribe(b"\x00\x00" * 800, 8000)
    assert fake.decoded == []


def test_gateway_skips_provider_for_empty_audio() -> None:
    fake = _FakeRecognizer()
    assert _zipformer(fake).transcribe(b"", WIDEBAND_RATE) == ASRResult(text="")
    assert fake.decoded == []


def test_recognizer_resamples_to_model_rate() -> None:
    pytest.importorskip("numpy")
    fake = _FakeRecognizer(text="xin chào")
    recognizer = SpeechRecognizer(_zipformer(fake))

    transcript = recognizer.transcribe(AudioSegment(pcm=b"\x00\x00" * 800, sample_rate=8000))

    assert transcript.text == "xin chào"
    assert transcript.is_silence is False
    sample_rate, _samples = fake.decoded[0].accepted
    assert sample_rate == WIDEBAND_RATE


def test_zipformer_transcribe_returns_token_confidence() -> None:
    pytest.importorskip("numpy")
    fake = _FakeRecognizer(text="có")
    fake.create_stream = lambda: _ScoredStream("có", [math.log(0.8), math.log(0.5)])

    result = _zipformer(fake).transcribe(b"\x00\x00" * 1600, WIDEBAND_RATE)

    assert result.text == "có"
    assert result.confidence == pytest.approx(math.sqrt(0.8 * 0.5))


class _ScoredStream(_FakeStream):
    def __init__(self, text: str, log_probs: list[float]) -> None:
        super().__init__(text)
        self.result.ys_log_probs = log_probs


def test_recognizer_blank_result_is_silence() -> None:
    pytest.importorskip("numpy")
    recognizer = SpeechRecognizer(_zipformer(_FakeRecognizer(text="   ")))

    transcript = recognizer.transcribe(
        AudioSegment(pcm=b"\x00\x00" * 1600, sample_rate=WIDEBAND_RATE)
    )

    assert transcript.is_silence is True
    assert transcript.text == ""


def test_create_asr_gateway_reads_provider_config() -> None:
    gateway = create_asr_gateway(
        "gemini", config=GeminiASRConfig(model="gemini-test", _env_file=None)
    )
    assert (gateway.provider_name, gateway.model) == ("gemini", "gemini-test")


def test_create_asr_gateway_rejects_mismatched_config_and_unknown_provider() -> None:
    with pytest.raises(ValueError):
        create_asr_gateway("zipformer", config=GeminiASRConfig(_env_file=None))
    with pytest.raises(UnsupportedProviderError):
        create_asr_gateway("whisper")  # type: ignore[arg-type]


class _FakeTTS:
    model = "fake-tts"

    def __init__(self) -> None:
        self.spoken: list[str] = []

    def synthesize(self, text: str) -> TTSResult:
        self.spoken.append(text)
        return TTSResult(pcm=b"\x00\x00" * 10, sample_rate=24_000)


def test_tts_gateway_skips_blank_text_and_synthesizer_wraps_pcm() -> None:
    provider = _FakeTTS()
    synthesizer = SpeechSynthesizer(TTSGateway(provider, provider_name="openai"))

    assert synthesizer.synthesize("   ") is None
    segment = synthesizer.synthesize(" xin chào ")

    assert provider.spoken == ["xin chào"]
    assert segment == AudioSegment(pcm=b"\x00\x00" * 10, sample_rate=24_000)
    assert (synthesizer.name, synthesizer.model) == ("openai", "fake-tts")


@pytest.mark.asyncio
async def test_sync_tts_stream_uses_gateway_fallback_at_track_rate() -> None:
    class FailedVbee:
        model = "vbee"
        stream_sample_rate = 8000

        def synthesize(self, text: str) -> TTSResult:
            raise RuntimeError("provider unavailable")

    class BackupTTS:
        model = "backup"

        def synthesize(self, text: str) -> TTSResult:
            assert text == "xin chào"
            return TTSResult(pcm=b"\x01\x00" * 10, sample_rate=8000)

    gateway = TTSGateway(
        FailedVbee(),
        provider_name="vbee",
        fallback=TTSGateway(BackupTTS(), provider_name="elevenlabs"),
    )
    synthesizer = SpeechSynthesizer(gateway)

    assert synthesizer.stream_sample_rate == 8000
    assert [chunk async for chunk in synthesizer.synthesize_stream("xin chào")] == [
        b"\x01\x00" * 10
    ]


@pytest.mark.asyncio
async def test_vbee_stream_reaches_synthesizer_chunk_by_chunk_and_cancel_closes_it() -> None:
    parts = [b"\x01\x00" * 100, b"\x02\x00" * 100, b"\x03\x00" * 100]
    clients: list[httpx.AsyncClient] = []

    def handler(request: httpx.Request) -> httpx.Response:
        async def body():
            for part in parts:
                yield part

        return httpx.Response(200, content=body(), headers={"content-type": "audio/pcm"})

    def async_client() -> httpx.AsyncClient:
        clients.append(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        return clients[-1]

    vbee = VbeeTTS(
        VbeeTTSConfig(api_token="t", app_id="a", _env_file=None),
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
        async_client_factory=async_client,
    )
    synthesizer = SpeechSynthesizer(TTSGateway(vbee, provider_name="vbee"))

    # Phát từng chunk ngay khi về, không gom cả câu thành một khối như đường fallback sync
    assert synthesizer.stream_sample_rate == 8000
    assert [chunk async for chunk in synthesizer.synthesize_stream("xin chào")] == parts

    stream = synthesizer.synthesize_stream("xin chào")
    assert await anext(stream) == parts[0]
    await synthesizer.cancel()
    assert [chunk async for chunk in stream] == []

    await synthesizer.aclose()
    assert clients[0].is_closed


class _StreamTTS:
    def __init__(self, model: str, chunks: list[bytes], rate: int = 8000, fail: bool = False):
        self.model = model
        self.voice = f"{model}-voice"
        self.stream_sample_rate = rate
        self._chunks = chunks
        self._fail = fail

    def synthesize(self, text: str) -> TTSResult:  # pragma: no cover - chỉ dùng stream
        raise AssertionError

    async def synthesize_stream(self, text: str):
        if self._fail:
            raise RuntimeError("provider unavailable")
        for chunk in self._chunks:
            yield chunk


def _stream_synthesizer(primary: _StreamTTS, backup: _StreamTTS) -> SpeechSynthesizer:
    return SpeechSynthesizer(
        TTSGateway(
            primary,
            provider_name="vbee",
            fallback=TTSGateway(backup, provider_name="elevenlabs"),
        )
    )


@pytest.mark.asyncio
async def test_stream_falls_back_through_gateway_and_reports_actual_provider() -> None:
    synthesizer = _stream_synthesizer(
        _StreamTTS("vbee", [], fail=True), _StreamTTS("eleven", [b"\x01\x00" * 4] * 2)
    )

    assert [chunk async for chunk in synthesizer.synthesize_stream("xin chào")] == [
        b"\x01\x00" * 4
    ] * 2
    # CallBridge đọc các trường này cho span speech.tts.synthesize (voice để tính cost)
    info = synthesizer.last_stream_result
    assert (info.provider_actual, info.voice, info.fallback_used) == (
        "elevenlabs",
        "eleven-voice",
        True,
    )


@pytest.mark.asyncio
async def test_stream_fallback_at_other_rate_is_resampled_once_to_track_rate() -> None:
    pytest.importorskip("soxr")
    backup_pcm = [b"\x10\x00" * 800, b"\x20\x00" * 800]  # 16 kHz, 0,1 s
    synthesizer = _stream_synthesizer(
        _StreamTTS("vbee", [], fail=True), _StreamTTS("eleven", backup_pcm, rate=16_000)
    )

    chunks = [chunk async for chunk in synthesizer.synthesize_stream("xin chào")]

    assert synthesizer.stream_sample_rate == 8000
    assert len(chunks) == 1
    assert len(chunks[0]) == pytest.approx(len(b"".join(backup_pcm)) // 2, abs=4)


def test_create_tts_gateway_rejects_unknown_provider() -> None:
    with pytest.raises(UnsupportedProviderError):
        create_tts_gateway("none")  # type: ignore[arg-type]


def test_create_tts_gateway_builds_elevenlabs_provider() -> None:
    gateway = create_tts_gateway(
        "elevenlabs",
        config=ElevenLabsTTSConfig(
            api_key="sk_x", voice_id="v1", model="eleven_flash_v2_5", _env_file=None
        ),
    )
    assert (gateway.provider_name, gateway.model) == ("elevenlabs", "eleven_flash_v2_5")


def test_create_tts_gateway_rejects_mismatched_config() -> None:
    with pytest.raises(ValueError):
        create_tts_gateway("openai", config=ElevenLabsTTSConfig(_env_file=None))
