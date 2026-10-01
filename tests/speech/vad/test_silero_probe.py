"""Silero chạy song song chỉ để lấy xác suất (speech/asr/vad/silero_probe.py)."""

import wave
from pathlib import Path

import pytest

pytest.importorskip("onnxruntime", reason="cần extra [vad-silero] cài onnxruntime")

from speech.asr.vad.silero_probe import SileroProbe, build_probe  # noqa: E402
from speech.asr.vad.streaming import split_frames  # noqa: E402

_ROOT = Path(__file__).resolve().parents[3]
_MODEL_PATH = _ROOT / "src/speech/asr/vad/assets/silero_vad.onnx"

pytestmark = pytest.mark.skipif(
    not _MODEL_PATH.exists(),
    reason="silero_vad.onnx chưa tải — xem silero_vad_model_path trong config/speech.yaml",
)


def _speech() -> tuple[list[bytes], int]:
    with wave.open(str(_ROOT / "eval/stt-bench/audio-8k/STT_ID_02.wav"), "rb") as w:
        pcm, rate = w.readframes(w.getnframes()), w.getframerate()
    return list(split_frames(pcm, rate)), rate


def test_speech_scores_higher_than_silence() -> None:
    frames, rate = _speech()
    probe = SileroProbe(str(_MODEL_PATH), sample_rate=rate)
    speech = [probe.probability(f) for f in frames]
    silent = SileroProbe(str(_MODEL_PATH), sample_rate=rate)
    silence = [silent.probability(b"\x00\x00" * (len(frames[0]) // 2)) for _ in frames]

    assert max(p for p in speech if p is not None) > 0.8
    assert max(p for p in silence if p is not None) < 0.2


def test_first_frame_shorter_than_a_window_has_no_probability_yet() -> None:
    probe = SileroProbe(str(_MODEL_PATH), sample_rate=16_000)

    assert probe.probability(b"\x00\x00" * 480) is None  # 30 ms < cửa sổ 32 ms
    assert probe.probability(b"\x00\x00" * 480) is not None


def test_missing_model_gives_no_probe() -> None:
    assert build_probe(None, 16_000) is None
    assert build_probe(str(_ROOT / "does-not-exist.onnx"), 16_000) is None
