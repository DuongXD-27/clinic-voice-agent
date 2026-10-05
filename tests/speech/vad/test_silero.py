from pathlib import Path

import pytest

pytest.importorskip("sherpa_onnx", reason="cần extra [speech-zipformer] cài sherpa-onnx")

from speech.asr.vad.silero import SileroVadClassifier  # noqa: E402
from speech.asr.vad.streaming import FRAME_MS, split_frames  # noqa: E402

_MODEL_PATH = Path(__file__).resolve().parents[3] / "src/speech/asr/vad/assets/silero_vad.onnx"
_SAMPLE_RATE = 8_000
_FRAME_BYTES = int(_SAMPLE_RATE * FRAME_MS / 1000) * 2

pytestmark = pytest.mark.skipif(
    not _MODEL_PATH.exists(),
    reason="silero_vad.onnx chưa tải — xem silero_vad_model_path trong config/speech.yaml",
)


def _silence() -> bytes:
    return b"\x00\x00" * (_FRAME_BYTES // 2)


def _real_speech_frames() -> list[bytes]:
    """Silero được train để phân biệt giọng nói người thật với tone tổng hợp — khác
    WebRTC VAD (dễ bị "lừa" bởi tone sin thuần, xem test_webrtc.py::_tone). Dùng 1 case
    có sẵn trong golden audio suite thay vì tự sinh tone, để test có ý nghĩa thật."""
    import wave

    audio_path = Path(__file__).resolve().parents[3] / "eval/stt-bench/audio-8k/STT_ID_02.wav"
    with wave.open(str(audio_path), "rb") as w:
        pcm = w.readframes(w.getnframes())
        rate = w.getframerate()
    return list(split_frames(pcm, rate))


def test_silence_is_not_speech() -> None:
    classifier = SileroVadClassifier(str(_MODEL_PATH), sample_rate=_SAMPLE_RATE)
    results = [classifier.is_speech(_silence()) for _ in range(20)]
    assert not any(results)


def test_real_speech_is_detected() -> None:
    classifier = SileroVadClassifier(str(_MODEL_PATH), sample_rate=_SAMPLE_RATE)
    results = [classifier.is_speech(frame) for frame in _real_speech_frames()]
    assert any(results)


def test_empty_frame_is_not_speech() -> None:
    classifier = SileroVadClassifier(str(_MODEL_PATH), sample_rate=_SAMPLE_RATE)
    assert classifier.is_speech(b"") is False


if __name__ == "__main__":
    pytest.main([__file__])
