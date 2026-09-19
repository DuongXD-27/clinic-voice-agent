from callbot.speech.asr.zipformer import ZipFormerASR
from callbot.speech.types import WIDEBAND_RATE, AudioSegment


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


def _paths() -> dict[str, str]:
    return {
        "encoder_path": "encoder.onnx",
        "decoder_path": "decoder.onnx",
        "joiner_path": "joiner.onnx",
        "tokens_path": "tokens.txt",
    }


def test_transcribe_uses_injected_recognizer_and_resamples() -> None:
    fake = _FakeRecognizer(text="xin chào")
    asr = ZipFormerASR(**_paths(), recognizer=fake)
    # 8kHz đầu vào (băng hẹp điện thoại) — provider phải tự resample lên 16kHz.
    segment = AudioSegment(pcm=b"\x00\x00" * 800, sample_rate=8000)

    transcript = asr.transcribe(segment)

    assert transcript.text == "xin chào"
    assert transcript.is_silence is False
    assert len(fake.decoded) == 1
    sample_rate, _samples = fake.decoded[0].accepted
    assert sample_rate == WIDEBAND_RATE


def test_transcribe_empty_segment_is_silence_without_calling_recognizer() -> None:
    fake = _FakeRecognizer()
    asr = ZipFormerASR(**_paths(), recognizer=fake)

    transcript = asr.transcribe(AudioSegment(pcm=b"", sample_rate=WIDEBAND_RATE))

    assert transcript.is_silence is True
    assert transcript.text == ""
    assert fake.decoded == []


def test_transcribe_blank_result_is_silence() -> None:
    fake = _FakeRecognizer(text="   ")
    asr = ZipFormerASR(**_paths(), recognizer=fake)
    segment = AudioSegment(pcm=b"\x00\x00" * 1600, sample_rate=WIDEBAND_RATE)

    transcript = asr.transcribe(segment)

    assert transcript.is_silence is True
    assert transcript.text == ""


def test_name_and_input_sample_rate() -> None:
    asr = ZipFormerASR(**_paths(), recognizer=_FakeRecognizer())
    assert asr.name == "zipformer"
    assert asr.input_sample_rate == WIDEBAND_RATE
