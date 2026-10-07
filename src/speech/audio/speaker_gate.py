"""THỬ NGHIỆM: cổng giọng người gọi — bỏ lượt dài không phải giọng người gọi (người bên cạnh, TV).

Giọng mẫu lấy ngay trong cuộc gọi: lượt dài đầu tiên (>= `min_speech_ms` tiếng nói) là người gọi,
các lượt dài sau đó so độ giống (cosine của speaker embedding, sherpa-onnx) với giọng mẫu.
Lượt ngắn không bao giờ bị chặn: embedding của đoạn < 1 s không tin cậy (đo 07/10, EER 16–25%).

Đo 07/10 (giọng mẫu và câu thử cùng một cuộc gọi, TitaNet-small): đoạn 2 s có EER 7% (kênh
điện thoại) / 0,9% (web); ngưỡng 0,2 giữ khoảng 98% câu thật, chặn 97–98% câu người khác.
docs/evidence/stt-phone-echo-speaker-2026-10-07.md
"""

import logging
from typing import Callable, Optional

import numpy as np

logger = logging.getLogger(__name__)

Embed = Callable[[np.ndarray, int], np.ndarray]
# Giọng mẫu cập nhật dần bằng lượt dài được chấp nhận: giữ chừng này của giọng mẫu cũ.
_KEEP = 0.8


def _trim(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """Bỏ khoảng lặng hai đầu (khung 30 ms nhỏ hơn khung to nhất quá 30 dB)."""
    frame = sample_rate * 30 // 1000
    levels = np.array(
        [
            np.sqrt(np.mean(np.square(samples[i : i + frame], dtype=np.float64)))
            for i in range(0, len(samples) - frame + 1, frame)
        ]
    )
    if not levels.size or levels.max() == 0:
        return samples
    active = np.flatnonzero(levels >= levels.max() * 10 ** (-30 / 20))
    return samples[active[0] * frame : (active[-1] + 1) * frame]


class SpeakerGate:
    """Một instance cho một cuộc gọi (giữ giọng mẫu)."""

    def __init__(
        self, embed: Embed, *, enforce: bool, threshold: float, min_speech_ms: int
    ) -> None:
        """`enforce=False`: chỉ ghi log, không chặn."""
        self._embed = embed
        self._enforce = enforce
        self._threshold = threshold
        self._min_speech_ms = min_speech_ms
        self._voice: Optional[np.ndarray] = None

    @classmethod
    def from_model(cls, model_path: str, **kwargs) -> "SpeakerGate":
        import sherpa_onnx

        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=model_path, num_threads=1)
        extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)

        def embed(samples: np.ndarray, sample_rate: int) -> np.ndarray:
            stream = extractor.create_stream()
            stream.accept_waveform(
                sample_rate=sample_rate, waveform=(samples / 32768.0).astype(np.float32)
            )
            stream.input_finished()
            vector = np.array(extractor.compute(stream), dtype=np.float32)
            return vector / max(float(np.linalg.norm(vector)), 1e-9)

        return cls(embed, **kwargs)

    def allows(self, pcm: bytes, sample_rate: int, speech_ms: Optional[float]) -> bool:
        """False = bỏ lượt (chỉ khi `enforce`). Chặn CPU — gọi trong thread."""
        if speech_ms is None or speech_ms < self._min_speech_ms or not pcm:
            return True
        samples = _trim(np.frombuffer(pcm, dtype=np.int16).astype(np.float32), sample_rate)
        vector = self._embed(samples, sample_rate)
        if self._voice is None:
            self._voice = vector
            logger.info("speaker_gate: enroll speech_ms=%.0f", speech_ms)
            return True
        similarity = float(vector @ self._voice)
        caller = similarity >= self._threshold
        logger.info(
            "speaker_gate: similarity=%.2f speech_ms=%.0f decision=%s",
            similarity,
            speech_ms,
            "pass" if caller else ("block" if self._enforce else "would_block"),
        )
        if caller:
            mean = _KEEP * self._voice + (1 - _KEEP) * vector
            self._voice = mean / max(float(np.linalg.norm(mean)), 1e-9)
        return caller or not self._enforce
