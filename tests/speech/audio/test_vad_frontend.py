"""Front-end của bộ phân loại tiếng nói: Silero nghe bản đã khử nhiễu, ASR vẫn nghe frame gốc."""

import asyncio
import logging
from pathlib import Path

import numpy as np
import pytest

from speech.asr.vad.async_stream import AsyncStreamingVAD
from speech.asr.vad.energy import EnergyFrameClassifier
from speech.asr.vad.shared import SharedSpeechDetector
from speech.audio.vad_frontend import VadFrontend, build_vad_frontend
from speech.turn.controller import TurnController

_RATE = 16_000
_FRAME = 480  # 30 ms
_GTCRN = Path("src/speech/asr/vad/assets/gtcrn_simple.onnx")


def _noise(dbfs: float, samples: int = _FRAME, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    x = rng.normal(0.0, 1.0, samples)
    x *= 32768 * 10 ** (dbfs / 20) / np.sqrt(np.mean(x**2))
    return np.clip(np.round(x), -32768, 32767).astype(np.int16)


def _dbfs(pcm: np.ndarray) -> float:
    power = float(np.mean(pcm.astype(np.float64) ** 2))
    return 10 * np.log10(power / 32768**2) if power > 0 else -120.0


class _Silencer:
    """Bộ khử nhiễu giả: xoá sạch mọi thứ, nhả theo bước 512 mẫu như GTCRN."""

    def __init__(self) -> None:
        self._pending = 0

    def process(self, samples: np.ndarray) -> np.ndarray:
        self._pending += len(samples)
        ready = self._pending - self._pending % 512
        self._pending -= ready
        return np.zeros(ready, dtype=np.int16)


class _Passthrough:
    def process(self, samples: np.ndarray) -> np.ndarray:
        return samples


class _RecordingClassifier:
    def __init__(self, inner) -> None:
        self._inner = inner
        self.heard: list[bytes] = []

    def is_speech(self, frame: bytes) -> bool:
        self.heard.append(frame)
        return self._inner.is_speech(frame)


def test_detector_classifies_the_analysis_audio_but_files_the_result_under_the_frame() -> None:
    classifier = _RecordingClassifier(EnergyFrameClassifier(500.0))
    detector = SharedSpeechDetector(classifier, capacity=8)
    loud = _noise(-20.0).tobytes()

    assert detector.classify(loud, analysis=b"") is False  # front-end chưa nhả mẫu nào
    assert classifier.heard == [b""]  # không lấy frame gốc thay cho bản phân tích rỗng
    assert detector.view().is_speech(loud) is False
    other = _noise(-20.0, seed=1).tobytes()
    assert detector.classify(other) is True  # không có front-end: nghe chính frame
    assert detector.view().is_speech(other) is True


def test_frontend_gain_applies_only_to_what_the_classifier_hears() -> None:
    frontend = VadFrontend(_Passthrough(), gain_db=12.0)
    frame = _noise(-50.0)

    out = np.frombuffer(frontend.process(frame.tobytes()), dtype=np.int16)

    assert _dbfs(out) == pytest.approx(-38.0, abs=0.2)
    assert _dbfs(frame) == pytest.approx(-50.0, abs=0.2)  # frame gốc không đổi


def test_floor_means_the_classifier_never_hears_digital_silence() -> None:
    """Sau khử nhiễu, đoạn im lặng tuyệt đối làm Silero tự bật cờ (ASR bịa "Ừ" sau câu — đo 12/10);
    nền nhiễu trắng nhỏ ở mức cố định thay cho im lặng tuyệt đối."""
    frontend = VadFrontend(_Silencer(), floor_dbfs=-70.0)
    silence = np.zeros(_FRAME, dtype=np.int16).tobytes()

    out = np.frombuffer(b"".join(frontend.process(silence) for _ in range(100)), dtype=np.int16)

    assert np.count_nonzero(out) > 0.9 * out.size
    assert _dbfs(out) == pytest.approx(-70.0, abs=1.0)


def test_off_builds_nothing_and_a_missing_model_falls_back_to_plain_vad(caplog) -> None:
    assert build_vad_frontend("off", sample_rate=_RATE) is None
    with caplog.at_level(logging.WARNING):
        assert build_vad_frontend("gtcrn", sample_rate=_RATE, model_path="/khong/co.onnx") is None
    assert "không thấy model" in caplog.text


async def test_pipeline_sends_original_frames_to_asr_while_vad_hears_the_frontend() -> None:
    """Nhiễu to (energy classifier gắn cờ nếu nghe trực tiếp) mà front-end xoá sạch: không có
    tiếng nói, không có lượt — nhưng ASR vẫn nhận đúng từng frame gốc, đúng thứ tự."""
    from tests.speech.pipeline_factory import make_stt_pipeline

    class _RecordingASR:
        name = "fake"
        input_sample_rate = _RATE

        def __init__(self, view) -> None:
            self._view = view
            self.frames: list[bytes] = []
            self.flags: list[bool] = []

        def transcribe(self, segment):
            raise NotImplementedError

        async def stream(self, frames, **_kwargs):
            async for item in frames:
                if isinstance(item, bytes):
                    self.frames.append(item)
                    self.flags.append(self._view.is_speech(item))
            return
            yield  # async generator không phát event nào

    classifier = _RecordingClassifier(EnergyFrameClassifier(500.0))
    detector = SharedSpeechDetector(classifier, capacity=2000)
    asr = _RecordingASR(detector.view())
    pipeline = make_stt_pipeline(
        asr=asr,
        vad=AsyncStreamingVAD(detector.view(), end_silence_ms=600, frame_ms=30),
        detector=detector,
        sample_rate=_RATE,
        vad_frontend=VadFrontend(_Silencer()),
    )
    frames = [_noise(-20.0, seed=i).tobytes() for i in range(60)]

    async def source():
        for frame in frames:
            yield frame
            await asyncio.sleep(0)

    turns = [turn async for turn in pipeline.stream(source(), turn_controller=TurnController())]

    assert turns == []
    assert asr.frames == frames
    assert not any(asr.flags)
    assert all(not np.frombuffer(heard, dtype=np.int16).any() for heard in classifier.heard)
    assert sum(len(h) for h in classifier.heard) == 60 * _FRAME * 2 - (60 * _FRAME) % 512 * 2


@pytest.mark.skipif(not _GTCRN.is_file(), reason="chưa tải gtcrn_simple.onnx (config/speech.yaml)")
def test_gtcrn_frontend_removes_steady_noise_without_delaying_the_stream() -> None:
    pytest.importorskip("sherpa_onnx")
    frontend = build_vad_frontend("gtcrn", sample_rate=_RATE, model_path=str(_GTCRN))
    noise = _noise(-40.0, samples=_FRAME * 100, seed=3)

    out = [frontend.process(noise[i : i + _FRAME].tobytes()) for i in range(0, len(noise), _FRAME)]
    cleaned = np.frombuffer(b"".join(out), dtype=np.int16)

    # Nhả theo bước 256 mẫu, không giữ quá một frame.
    assert len(noise) - len(cleaned) <= _FRAME
    assert _dbfs(cleaned[len(cleaned) // 2 :]) < _dbfs(noise) - 10


@pytest.mark.parametrize("kind", ["webrtc", "webrtc_agc"])
def test_webrtc_frontend_keeps_frame_length(kind: str) -> None:
    pytest.importorskip("livekit.rtc")
    frontend = build_vad_frontend(kind, sample_rate=_RATE)

    lengths = {len(frontend.process(_noise(-40.0, seed=i).tobytes())) for i in range(20)}

    assert lengths == {_FRAME * 2}  # 30 ms = 3 khúc 10 ms, không tồn mẫu
