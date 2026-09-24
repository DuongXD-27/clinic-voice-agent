import pytest

from inference.asr import ASRGateway, ASRResult, create_asr_gateway
from inference.asr.config import GeminiASRConfig, ZipFormerConfig
from inference.asr.providers.zipformer import ZipFormerASR
from inference.common.errors import UnsupportedProviderError
from inference.tts import TTSGateway, TTSResult, create_tts_gateway
from inference.tts.config import ElevenLabsTTSConfig
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
    assert gateway.model == "csukuangfj/sherpa-onnx-zipformer-vi-int8-2025-04-20"
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
