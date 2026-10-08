"""THỬ NGHIỆM: cổng giọng người gọi — bỏ giọng người khác (người bên cạnh, TV, điện thoại phát gần
mic) khỏi lượt của người gọi.

Chấm theo ĐOẠN CON `window_ms` của lượt, không theo cả lượt (cosine của speaker embedding,
sherpa-onnx, với giọng mẫu):
- Giọng mẫu lấy trong cuộc gọi, từ lượt dài (>= `min_speech_ms` tiếng nói) đầu tiên mà mọi đoạn
  con là CÙNG một giọng. Lượt lẫn giọng khác thì chưa lấy (cuộc gọi 08/10: lượt dài đầu tiên là
  tin tức từ điện thoại phát gần mic lẫn câu "Alo tôi tên là…" — lấy cả lượt làm giọng mẫu rồi chặn
  đúng giọng người gọi, similarity 0,12).
- Lượt có đầu/cuối là giọng khác: giữ phần của người gọi (`trim`, pipeline decode lại phần đó).
  Toàn giọng khác: bỏ lượt (`block`). Đoạn chưa chắc (giữa hai ngưỡng) tính là người gọi.
- Lượt ngắn không bao giờ bị chặn: embedding đoạn ngắn không tin cậy (07/10: đoạn 1 s EER 16%,
  2 s 7% điện thoại / 0,9% web, giọng mẫu cùng cuộc gọi). Giọng nói chồng lên nhau thì không tách
  được ở đây.

docs/evidence/stt-phone-echo-speaker-2026-10-07.md, stt-livekit-overlap-onset-filler-2026-10-08.md
"""

import logging
from dataclasses import dataclass
from typing import Callable, Literal, Optional

import numpy as np

logger = logging.getLogger(__name__)

Embed = Callable[[np.ndarray, int], np.ndarray]
Decision = Literal["skip", "enroll", "defer", "pass", "trim", "block"]
# Giọng mẫu cập nhật dần bằng lượt được chấp nhận mà mọi đoạn đều rõ là người gọi.
_KEEP = 0.8
_WINDOW_MS = 1500
# Lượt ngắn hơn một đoạn nhưng chừng này trở lên vẫn chấm như một đoạn.
_MIN_WINDOW_MS = 1000
# Giọng mẫu: mọi CẶP đoạn phải giống nhau ít nhất chừng này (cùng một người nói). So với trung
# bình của lượt thì không đủ: lượt nửa này nửa kia vẫn giống trung bình ~0,7. Hai giọng khác nhau
# thường < 0,3 (07/10, TitaNet).
_ENROLL_CONSISTENCY = 0.3
# Lượt là giọng khác khi trung bình các đoạn dưới mức này (và không đoạn nào tới `threshold`); cắt
# đoạn đầu/cuối dưới `_TRIM_THRESHOLD` khi phần còn lại trung bình >= `threshold`. Cuộc gọi thật
# 08/10 (giọng mẫu cùng cuộc gọi, CAM++): đoạn người gọi 0,54-0,74, điện thoại phát cạnh mic
# 0,12-0,16. Khác cuộc gọi (bộ web, xấu nhất): người gọi p5 0,26, người khác (VIVOS) p95 0,21.
_OTHER_THRESHOLD = 0.25
_TRIM_THRESHOLD = 0.25
# Đã có giọng mẫu: lượt ngắn (>= `_MIN_WINDOW_MS`, một đoạn) cũng được chấm, chỉ chặn khi dưới mức
# này ("BẰNG QUY NHÁ" 1,6 s từ điện thoại lọt qua vì lượt < 2 s không được chấm).
_SHORT_BLOCK_THRESHOLD = 0.2


@dataclass(frozen=True)
class SpeakerVerdict:
    decision: Decision
    similarities: tuple[float, ...] = ()
    # `trim`: khoảng mẫu (start, end) của `pcm` đầu vào cần giữ.
    keep: Optional[tuple[int, int]] = None


def _active_span(samples: np.ndarray, sample_rate: int) -> tuple[int, int]:
    """Khoảng có tiếng (khung 30 ms không nhỏ hơn khung to nhất quá 30 dB)."""
    frame = sample_rate * 30 // 1000
    levels = np.array(
        [
            np.sqrt(np.mean(np.square(samples[i : i + frame], dtype=np.float64)))
            for i in range(0, len(samples) - frame + 1, frame)
        ]
    )
    if not levels.size or levels.max() == 0:
        return 0, len(samples)
    active = np.flatnonzero(levels >= levels.max() * 10 ** (-30 / 20))
    return int(active[0] * frame), int((active[-1] + 1) * frame)


def _windows(start: int, end: int, size: int, minimum: int) -> list[tuple[int, int]]:
    """Các đoạn liền nhau dài `size`, đoạn cuối căn theo cuối khoảng (có thể chồng đoạn trước)."""
    length = end - start
    if length < minimum:
        return []
    if length <= size:
        return [(start, end)]
    spans = [(begin, begin + size) for begin in range(start, end - size + 1, size)]
    if spans[-1][1] < end:
        spans.append((end - size, end))
    return spans


class SpeakerGate:
    """Một instance cho một cuộc gọi (giữ giọng mẫu)."""

    def __init__(
        self,
        embed: Embed,
        *,
        enforce: bool,
        threshold: float,
        min_speech_ms: int,
        other_threshold: float = _OTHER_THRESHOLD,
        window_ms: int = _WINDOW_MS,
    ) -> None:
        """`enforce=False`: chỉ ghi log, không chặn. Đoạn có similarity >= `threshold` rõ là người
        gọi; lượt có trung bình < `other_threshold` là giọng khác."""
        self._embed = embed
        self.enforce = enforce
        self._threshold = threshold
        self._other_threshold = other_threshold
        self._min_speech_ms = min_speech_ms
        self._window_ms = window_ms
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

    @property
    def enrolled(self) -> bool:
        return self._voice is not None

    def allows(self, pcm: bytes, sample_rate: int, speech_ms: Optional[float]) -> bool:
        """False = bỏ cả lượt (chỉ khi `enforce`). Chặn CPU — gọi trong thread."""
        return self.assess(pcm, sample_rate, speech_ms).decision != "block" or not self.enforce

    def assess(self, pcm: bytes, sample_rate: int, speech_ms: Optional[float]) -> SpeakerVerdict:
        """Chấm một lượt. Không tự chặn: pipeline làm theo `decision` khi `enforce`. Chặn CPU —
        gọi trong thread."""
        min_speech_ms = self._min_speech_ms if self._voice is None else _MIN_WINDOW_MS
        if speech_ms is None or speech_ms < min_speech_ms or not pcm:
            logger.info(
                "speaker_gate: skip short turn speech_ms=%s audio_ms=%.0f",
                None if speech_ms is None else round(speech_ms),
                len(pcm) / 2 / sample_rate * 1000,
            )
            return SpeakerVerdict("skip")
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
        start, end = _active_span(samples, sample_rate)
        spans = _windows(
            start,
            end,
            sample_rate * self._window_ms // 1000,
            sample_rate * _MIN_WINDOW_MS // 1000,
        )
        if not spans:
            logger.info("speaker_gate: skip, active audio < %d ms", _MIN_WINDOW_MS)
            return SpeakerVerdict("skip")
        vectors = [self._embed(samples[a:b], sample_rate) for a, b in spans]
        if self._voice is None:
            return self._enroll(vectors, speech_ms)
        similarities = tuple(round(float(vector @ self._voice), 3) for vector in vectors)
        others = [similarity < _TRIM_THRESHOLD for similarity in similarities]
        kept = [s for s, other in zip(similarities, others, strict=False) if not other]
        if len(similarities) == 1:
            single = similarities[0] < _SHORT_BLOCK_THRESHOLD
            verdict = SpeakerVerdict("block" if single else "pass", similarities)
        elif (
            float(np.mean(similarities)) < self._other_threshold
            and max(similarities) < self._threshold
        ):
            verdict = SpeakerVerdict("block", similarities)
        elif (others[0] or others[-1]) and kept and float(np.mean(kept)) >= self._threshold:
            first = others.index(False)
            last = len(others) - 1 - others[::-1].index(False)
            verdict = SpeakerVerdict("trim", similarities, (spans[first][0], spans[last][1]))
        else:
            verdict = SpeakerVerdict("pass", similarities)
            if all(similarity >= self._threshold for similarity in similarities):
                mean = _KEEP * self._voice + (1 - _KEEP) * _unit(np.mean(vectors, axis=0))
                self._voice = _unit(mean)
        logger.info(
            "speaker_gate: decision=%s%s similarities=%s speech_ms=%.0f",
            verdict.decision,
            "" if self.enforce else " (log only)",
            ",".join(f"{similarity:.2f}" for similarity in similarities),
            speech_ms,
        )
        return verdict

    def _enroll(self, vectors: list[np.ndarray], speech_ms: float) -> SpeakerVerdict:
        consistency = tuple(
            round(float(vectors[i] @ vectors[j]), 3)
            for i in range(len(vectors))
            for j in range(i + 1, len(vectors))
        )
        if len(vectors) == 1 or min(consistency) < _ENROLL_CONSISTENCY:
            # Một đoạn không đủ biết lượt chỉ có một giọng; lẫn giọng khác thì chờ lượt sau.
            logger.info(
                "speaker_gate: defer enroll consistency=%s speech_ms=%.0f",
                ",".join(f"{value:.2f}" for value in consistency),
                speech_ms,
            )
            return SpeakerVerdict("defer", consistency)
        self._voice = _unit(np.mean(vectors, axis=0))
        logger.info(
            "speaker_gate: enroll windows=%d consistency=%.2f speech_ms=%.0f",
            len(vectors),
            min(consistency),
            speech_ms,
        )
        return SpeakerVerdict("enroll", consistency)


def _unit(vector: np.ndarray) -> np.ndarray:
    return vector / max(float(np.linalg.norm(vector)), 1e-9)
