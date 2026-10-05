"""ZipFormer self-host qua sherpa-onnx (model chọn ở config/asr.yaml).

Các model Zipformer tiếng Việt đều là bản offline (chỉ `OfflineRecognizer`), nên:
- `transcribe(pcm)`: decode một đoạn audio ở 16 kHz — đường HTTP.
- `stream(frames)`: giả lập streaming kiểu chunked-offline — đường LiveKit. Decode lại cả câu
  sau mỗi nhịp để phát partial, phát final khi hết câu. RTF ~0,03 nên vẫn rẻ hơn thời gian
  thực nhiều lần (docs/reference/phone-leg-architecture.md §3.1).

`stream()` nằm ngoài Protocol `ASRProvider`, gọi qua `SpeechRecognizer.stream`. Nhận PCM 8 kHz
hoặc 16 kHz, resample một lần lúc decode nếu khác 16 kHz.

Confidence = trung bình nhân xác suất token (`ys_log_probs`). Không bắt được nghe nhầm ("hủy
lịch" → "THÙY LINH" vẫn 0,79/0,98/0,57); hiện chỉ ghi log để đo.
"""

import asyncio
import logging
import math
from typing import Any, AsyncIterator, NamedTuple, Optional

from inference.asr.base import ASRResult
from inference.asr.config import ZipFormerConfig
from speech.asr.vad.base import FrameClassifier
from speech.audio.codec import resample
from speech.types import NARROWBAND_RATE, AsrSegmentEnd, TranscriptEvent

_PRE_SPEECH_PREROLL_MS = 300

logger = logging.getLogger(__name__)


class _Decoded(NamedTuple):
    text: str
    # exp(trung bình log-prob token) và xác suất token thấp nhất; None khi không có chữ.
    confidence: Optional[float] = None
    min_token_prob: Optional[float] = None


class ZipFormerASR:
    input_sample_rate = 16_000

    def __init__(self, config: ZipFormerConfig, *, recognizer: Any = None) -> None:
        self._config = config
        self._recognizer = recognizer

    @property
    def model(self) -> str:
        return self._config.model

    def _get_recognizer(self):
        if self._recognizer is None:
            import sherpa_onnx  # pip install -e ".[speech-zipformer]"

            self._recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
                tokens=self._config.tokens_path,
                encoder=self._config.encoder_path,
                decoder=self._config.decoder_path,
                joiner=self._config.joiner_path,
                num_threads=self._config.num_threads,
                sample_rate=self.input_sample_rate,
                feature_dim=80,
                decoding_method="greedy_search",
                provider="cpu",
            )
        return self._recognizer

    def transcribe(self, pcm: bytes) -> ASRResult:
        decoded = self._decode_scored(pcm)
        return ASRResult(text=decoded.text, confidence=decoded.confidence)

    async def stream(
        self,
        frames: AsyncIterator[bytes | AsrSegmentEnd],
        *,
        audio_sample_rate: int = NARROWBAND_RATE,
        silence_classifier: FrameClassifier | None = None,
        end_silence_ms: int = 600,
        min_emit_interval_ms: int = 300,
        min_decode_ms: int | None = None,
        max_turn_speech_ms: int | None = None,
    ) -> AsyncIterator[TranscriptEvent]:
        """Chunked-offline: gom từng câu theo `silence_classifier`, decode lại cả câu để phát
        partial, phát final khi đủ `end_silence_ms` im lặng hoặc nói liền quá
        `max_turn_speech_ms` (chống buffer phình vô hạn).

        - Câu có ít hơn `min_decode_ms` tiếng nói không bao giờ được decode: ZipFormer bịa cả
          cụm từ từ "à"/"ờm" quá ngắn.
        - Giữ 300 ms trước lúc nhận ra tiếng nói để không mất âm tiết đầu.
        - `AsrSegmentEnd.DISCARD`: bỏ câu dở, không phát event.
        """
        if min_decode_ms is None:
            min_decode_ms = self._config.min_decode_ms
        if max_turn_speech_ms is None:
            max_turn_speech_ms = self._config.max_turn_speech_ms
        if silence_classifier is None:
            from speech.asr.vad.energy import EnergyFrameClassifier

            silence_classifier = EnergyFrameClassifier()
        if audio_sample_rate not in (8_000, 16_000):
            raise ValueError(f"ZipFormer stream không hỗ trợ sample rate {audio_sample_rate}")

        utterance = _Utterance(audio_sample_rate)

        async def decode() -> _Decoded:
            # decode_stream chặn CPU — chạy trong thread, nếu không cả event loop LiveKit đứng.
            return await asyncio.to_thread(
                self._decode_stream_scored, bytes(utterance.pcm), audio_sample_rate
            )

        async for frame in frames:
            if isinstance(frame, AsrSegmentEnd):
                utterance.discard()
                continue
            if not frame:
                continue
            is_speech = silence_classifier.is_speech(frame)
            if not utterance.add(frame, is_speech):
                continue
            has_min_speech = utterance.speech_ms >= min_decode_ms
            # Mỗi partial decode lại cả câu; partial_interval_ratio giãn nhịp cho câu dài.
            partial_interval_ms = max(
                min_emit_interval_ms, self._config.partial_interval_ratio * utterance.duration_ms
            )
            if is_speech and has_min_speech and utterance.since_partial_ms >= partial_interval_ms:
                decoded = await decode()
                utterance.since_partial_ms = 0.0
                if decoded.text and decoded.text != utterance.last_partial:
                    utterance.last_partial = decoded.text
                    yield TranscriptEvent(
                        text=decoded.text, is_final=False, confidence=decoded.confidence
                    )

            still_speaking = utterance.speech_ms >= max_turn_speech_ms
            if utterance.silent_ms >= end_silence_ms or still_speaking:
                if has_min_speech:
                    decoded = await decode()
                    if decoded.text:
                        yield _final_event(decoded)
                utterance.close(still_speaking=still_speaking)

        if utterance.in_speech and utterance.pcm and utterance.speech_ms >= min_decode_ms:
            decoded = await decode()
            if decoded.text:
                yield _final_event(decoded)

    def _decode_stream_scored(self, pcm: bytes, source_rate: int) -> _Decoded:
        """Decode PCM streaming ở 8/16 kHz; chỉ resample khi nguồn khác rate model."""
        if source_rate != self.input_sample_rate:
            pcm = resample(pcm, source_rate, self.input_sample_rate)
        return self._decode_scored(pcm)

    def _decode_scored(self, pcm: bytes) -> _Decoded:
        """`pcm` đã ở `self.input_sample_rate` — decode thẳng, không resample lại."""
        import numpy as np

        if not pcm:
            return _Decoded("")
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        recognizer = self._get_recognizer()
        stream = recognizer.create_stream()
        stream.accept_waveform(self.input_sample_rate, samples)
        recognizer.decode_stream(stream)
        result = stream.result
        text = result.text.strip()
        log_probs = list(getattr(result, "ys_log_probs", None) or [])
        if not text or not log_probs:
            return _Decoded(text)
        return _Decoded(
            text,
            confidence=math.exp(sum(log_probs) / len(log_probs)),
            min_token_prob=math.exp(min(log_probs)),
        )


class _Utterance:
    """Câu đang nghe trong `stream()`: audio (kèm pre-roll) và các bộ đếm thời gian."""

    def __init__(self, sample_rate: int) -> None:
        self._rate = sample_rate
        self._pre_speech = bytearray()
        self._pre_speech_max = sample_rate * _PRE_SPEECH_PREROLL_MS // 1000 * 2
        self.pcm = bytearray()
        self.in_speech = False
        # Chỉ đếm frame có tiếng nói: đuôi im lặng không được giúp câu "à" vượt min_decode_ms.
        self.speech_ms = 0.0
        self.silent_ms = 0.0
        self.since_partial_ms = 0.0
        self.last_partial = ""

    @property
    def duration_ms(self) -> float:
        return len(self.pcm) / 2 / self._rate * 1000

    def add(self, frame: bytes, is_speech: bool) -> bool:
        """False khi frame chỉ vào pre-roll (chưa có câu nào đang mở)."""
        if not self.in_speech and not is_speech:
            self._pre_speech.extend(frame)
            del self._pre_speech[: max(0, len(self._pre_speech) - self._pre_speech_max)]
            return False
        if not self.in_speech:
            self.pcm.extend(self._pre_speech)
            self._pre_speech.clear()
            self.in_speech = True
        self.pcm.extend(frame)
        frame_ms = len(frame) / 2 / self._rate * 1000
        self.since_partial_ms += frame_ms
        if is_speech:
            self.speech_ms += frame_ms
            self.silent_ms = 0.0
        else:
            self.silent_ms += frame_ms
        return True

    def close(self, *, still_speaking: bool) -> None:
        """Đã chốt câu. `still_speaking`: chốt cưỡng bức giữa lúc đang nói — mở ngay câu mới."""
        self.pcm.clear()
        self.in_speech = still_speaking
        self.speech_ms = self.silent_ms = self.since_partial_ms = 0.0
        self.last_partial = ""

    def discard(self) -> None:
        """Pipeline ngừng đưa audio: audio trước và sau chỗ ngắt không liền nhau."""
        self.close(still_speaking=False)
        self._pre_speech.clear()


def _final_event(decoded: _Decoded) -> TranscriptEvent:
    if decoded.confidence is not None:
        # Không log text (PII); chỉ số để đối chiếu với turn qua thời điểm log.
        logger.debug(
            "zipformer final confidence=%.3f min_token_prob=%.3f",
            decoded.confidence,
            decoded.min_token_prob,
        )
    return TranscriptEvent(text=decoded.text, is_final=True, confidence=decoded.confidence)
