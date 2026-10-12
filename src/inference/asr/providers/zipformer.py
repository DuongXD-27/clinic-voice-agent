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
from collections import deque
from typing import Any, AsyncIterator, NamedTuple, Optional

import numpy as np

from inference.asr.base import ASRResult
from inference.asr.config import ZipFormerConfig
from inference.asr.providers.transducer_nbest import NBest, NBestHyp, TransducerNBest
from speech.asr.hotwords import NO_HOTWORDS, HotwordBox, Hotwords, word_distance
from speech.asr.nbest import NBestBox
from speech.asr.stream_context import StreamingFrame
from speech.asr.vad.base import FrameClassifier
from speech.audio.codec import resample
from speech.types import NARROWBAND_RATE, AsrSegmentEnd, TranscriptEvent

logger = logging.getLogger(__name__)


class _Decoded(NamedTuple):
    text: str
    # exp(trung bình log-prob token) và xác suất token thấp nhất; None khi không có chữ.
    confidence: Optional[float] = None
    min_token_prob: Optional[float] = None


class ZipFormerASR:
    input_sample_rate = 16_000
    supports_preroll_frames = True
    supports_segment_finalize = True

    def __init__(self, config: ZipFormerConfig, *, recognizer: Any = None) -> None:
        self._config = config
        self._recognizer = recognizer
        self._nbest: Optional[TransducerNBest] = None

    @property
    def model(self) -> str:
        return self._config.model

    @property
    def supports_nbest(self) -> bool:
        """Top N phương án của final (`stream(nbest=...)`) để hiện trên trang demo."""
        return self._config.nbest_top_k > 0

    def nbest(self, pcm: bytes, source_rate: int, hotwords: tuple[str, ...] = ()) -> NBest:
        """Top `nbest_top_k` phương án của một câu, điểm cuối có cộng `hotwords` của lượt như
        lúc chọn câu (không hotword: điểm thô); chặn CPU, gọi trong thread."""
        if source_rate != self.input_sample_rate:
            pcm = resample(pcm, source_rate, self.input_sample_rate)
        hyps = self._nbest_at_model_rate(pcm, self._config.nbest_top_k, hotwords)
        return NBest(hyps, hotwords)

    def _nbest_at_model_rate(
        self, pcm: bytes, k: int, hotwords: tuple[str, ...] = ()
    ) -> list[NBestHyp]:
        if self._nbest is None:
            self._nbest = TransducerNBest(
                encoder=self._config.encoder_path,
                decoder=self._config.decoder_path,
                joiner=self._config.joiner_path,
                tokens=self._config.tokens_path,
                num_threads=self._config.num_threads,
                sample_rate=self.input_sample_rate,
                bpe_vocab=self._config.bpe_vocab_path,
            )
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        return self._nbest.nbest(
            samples, k, hotwords, self._config.hotwords_score, self._config.max_active_paths
        )

    @property
    def supports_hotwords(self) -> bool:
        """Bật hotword theo lượt (`stream(hotwords=...)`) — cần beam search, xem config/asr.yaml."""
        return self._config.hotwords_enabled

    def _get_recognizer(self):
        if self._recognizer is None:
            import sherpa_onnx  # pip install -e ".[speech-zipformer]"

            options: dict[str, Any] = {"decoding_method": "greedy_search"}
            if self._config.hotwords_enabled:
                # Hotword chỉ chạy với beam search; `bpe.vocab` để mã hóa cụm từ thành token.
                options = {
                    "decoding_method": "modified_beam_search",
                    "max_active_paths": self._config.max_active_paths,
                    "modeling_unit": "bpe",
                    "bpe_vocab": self._config.bpe_vocab_path,
                    "hotwords_score": self._config.hotwords_score,
                }
            self._recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
                tokens=self._config.tokens_path,
                encoder=self._config.encoder_path,
                decoder=self._config.decoder_path,
                joiner=self._config.joiner_path,
                num_threads=self._config.num_threads,
                sample_rate=self.input_sample_rate,
                feature_dim=80,
                provider="cpu",
                **options,
            )
        return self._recognizer

    def transcribe(self, pcm: bytes) -> ASRResult:
        decoded = self._decode_scored(pcm)
        return ASRResult(text=decoded.text, confidence=decoded.confidence)

    async def stream(
        self,
        frames: AsyncIterator[bytes | StreamingFrame | AsrSegmentEnd],
        *,
        audio_sample_rate: int = NARROWBAND_RATE,
        silence_classifier: FrameClassifier | None = None,
        end_silence_ms: int = 600,
        min_emit_interval_ms: int = 300,
        min_decode_ms: int | None = None,
        max_turn_speech_ms: int | None = None,
        pre_speech_ms: int | None = None,
        hotwords: HotwordBox | None = None,
        nbest: NBestBox | None = None,
    ) -> AsyncIterator[TranscriptEvent]:
        """Chunked-offline: gom từng câu theo `silence_classifier`, decode lại cả câu để phát
        partial, phát final khi đủ `end_silence_ms` im lặng hoặc nói liền quá
        `max_turn_speech_ms` (chống buffer phình vô hạn).

        - Câu có ít hơn `min_decode_ms` tiếng nói không bao giờ được decode: ZipFormer bịa cả
          cụm từ từ "à"/"ờm" quá ngắn.
        - Giữ `pre_speech_ms` (None = config) trước lúc nhận ra tiếng nói để không mất âm tiết đầu.
        - `AsrSegmentEnd.DISCARD`: bỏ câu dở, không phát event.
        - `hotwords`: chỉ final dùng hotword của lượt (partial giữ nguyên để barge-in và cổng từ
          đệm không đổi). `guard_one_word`: decode thêm bản không hotword, chỉ nhận bản có hotword
          khi hai bản lệch tối đa 1 từ (lượt tên — không kéo tên khác hẳn về tên hồ sơ, SF-03).
        - `nbest`: sau mỗi final có chữ, tính top `nbest_top_k` phương án trong nền và bỏ task vào
          hộp (chỉ để hiện trên trang demo, không đổi final).
        """
        if min_decode_ms is None:
            min_decode_ms = self._config.min_decode_ms
        if max_turn_speech_ms is None:
            max_turn_speech_ms = self._config.max_turn_speech_ms
        if pre_speech_ms is None:
            pre_speech_ms = self._config.pre_speech_ms
        if silence_classifier is None:
            from speech.asr.vad.energy import EnergyFrameClassifier

            silence_classifier = EnergyFrameClassifier()
        if audio_sample_rate not in (8_000, 16_000):
            raise ValueError(f"ZipFormer stream không hỗ trợ sample rate {audio_sample_rate}")

        tail_ms = self._config.final_tail_ms
        utterance = _Utterance(
            audio_sample_rate,
            pre_speech_ms,
            onset_lookback_ms=self._config.onset_lookback_ms,
            track_voice_end=tail_ms is not None,
        )

        async def decode(*, final: bool = False) -> _Decoded:
            pcm = utterance.final_pcm(tail_ms) if final else bytes(utterance.pcm)
            hints = hotwords.current if final and hotwords is not None else NO_HOTWORDS
            # decode_stream chặn CPU — chạy trong thread, nếu không cả event loop LiveKit đứng.
            decoded = await asyncio.to_thread(
                self._decode_stream_hinted, pcm, audio_sample_rate, hints
            )
            if final and decoded.text and nbest is not None and self.supports_nbest:
                # Trong nền: final phát ngay, top N tới sau (chỉ để xem).
                phrases = hints.phrases if self._config.hotwords_enabled else ()
                nbest.add(
                    asyncio.create_task(
                        asyncio.to_thread(self.nbest, pcm, audio_sample_rate, phrases)
                    )
                )
            return decoded

        def final_event(decoded: _Decoded) -> TranscriptEvent:
            return _final_event(_prefer_confident_partial(decoded, utterance))

        async for frame in frames:
            if isinstance(frame, AsrSegmentEnd):
                if (
                    frame is AsrSegmentEnd.FINALIZE
                    and utterance.in_speech
                    and utterance.speech_ms >= min_decode_ms
                ):
                    decoded = await decode(final=True)
                    if decoded.text:
                        yield final_event(decoded)
                utterance.discard()
                continue
            is_preroll = isinstance(frame, StreamingFrame) and frame.is_preroll
            if isinstance(frame, StreamingFrame):
                frame = frame.pcm
            if not frame:
                continue
            is_speech = silence_classifier.is_speech(frame)
            if not utterance.add(frame, is_speech, is_preroll=is_preroll):
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
                    utterance.last_partial_confidence = decoded.confidence
                    yield TranscriptEvent(
                        text=decoded.text, is_final=False, confidence=decoded.confidence
                    )

            still_speaking = utterance.speech_ms >= max_turn_speech_ms
            if utterance.silent_ms >= end_silence_ms or still_speaking:
                if has_min_speech:
                    # Tách cưỡng bức giữa lúc đang nói: không có đuôi im lặng để cắt.
                    decoded = await decode(final=not still_speaking)
                    if decoded.text:
                        yield final_event(decoded) if not still_speaking else _final_event(decoded)
                utterance.close(still_speaking=still_speaking)

        if utterance.in_speech and utterance.pcm and utterance.speech_ms >= min_decode_ms:
            decoded = await decode(final=True)
            if decoded.text:
                yield final_event(decoded)

    def _decode_stream_hinted(self, pcm: bytes, source_rate: int, hints: Hotwords) -> _Decoded:
        if not hints or not self._config.hotwords_enabled:
            return self._decode_stream_scored(pcm, source_rate)
        if source_rate != self.input_sample_rate:
            pcm = resample(pcm, source_rate, self.input_sample_rate)
        biased = self._decode_scored(pcm, hotwords="/".join(hints.phrases))
        if not hints.guard_one_word:
            return biased
        plain = self._decode_scored(pcm)
        if plain.text == biased.text:
            # Hotword không đổi chữ: dùng hẳn bản thô (confidence thật; sherpa trộn điểm cộng
            # hotword vào log-prob của bản có hotword).
            return plain
        if word_distance(plain.text, biased.text) > 1:
            return plain
        return self._accept_hinted(pcm, biased)

    def _accept_hinted(self, pcm: bytes, biased: _Decoded) -> _Decoded:
        """Bản có hotword lệch bản thô 1 từ: nhận (đủ qua cổng tên) khi nằm trong top N thô."""
        k = self._config.hotwords_accept_top_k
        if k == 0:
            return biased
        top = [h.text for h in self._nbest_at_model_rate(pcm, k)]
        accepted = " ".join(biased.text.split()) in top
        # Không log chữ: lượt tên có PII.
        logger.info(
            "zipformer: bản có hotword %s top %d thô", "nằm trong" if accepted else "ngoài", k
        )
        if not accepted:
            return biased
        confidence = max(biased.confidence or 0.0, self._config.hotwords_accept_confidence)
        return biased._replace(confidence=confidence)

    def _decode_stream_scored(self, pcm: bytes, source_rate: int) -> _Decoded:
        """Decode PCM streaming ở 8/16 kHz; chỉ resample khi nguồn khác rate model."""
        if source_rate != self.input_sample_rate:
            pcm = resample(pcm, source_rate, self.input_sample_rate)
        return self._decode_scored(pcm)

    def _decode_scored(self, pcm: bytes, hotwords: str = "") -> _Decoded:
        """`pcm` đã ở `self.input_sample_rate` — decode thẳng, không resample lại."""
        import numpy as np

        if not pcm:
            return _Decoded("")
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        recognizer = self._get_recognizer()
        stream = recognizer.create_stream(hotwords) if hotwords else recognizer.create_stream()
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

    def __init__(
        self,
        sample_rate: int,
        pre_speech_ms: int,
        *,
        onset_lookback_ms: Optional[int] = None,
        track_voice_end: bool = False,
    ) -> None:
        self._rate = sample_rate
        self._pre_speech = bytearray()
        self._pre_speech_max = sample_rate * pre_speech_ms // 1000 * 2
        self._pre_speech_limit = self._pre_speech_max
        # Lần ngược tới điểm năng lượng bắt đầu (`_onset_bytes`): giữ thêm audio và mức (dB) của
        # từng frame trước tiếng nói, cùng nền nhiễu của các frame không phải tiếng nói gần đây.
        self._lookback = sample_rate * (onset_lookback_ms or 0) // 1000 * 2
        self._pre_levels: deque[tuple[int, float]] = deque()
        self._quiet_levels: deque[float] = deque(maxlen=_ONSET_FLOOR_FRAMES)
        self._track_levels = bool(self._lookback) or track_voice_end
        # Mức to nhất của các frame tiếng nói trong câu (ngưỡng "còn là giọng" ở đuôi câu).
        self._peak = -96.0
        self.pcm = bytearray()
        self.in_speech = False
        # Chỉ đếm frame có tiếng nói: đuôi im lặng không được giúp câu "à" vượt min_decode_ms.
        self.speech_ms = 0.0
        self.silent_ms = 0.0
        self.since_partial_ms = 0.0
        self.last_partial = ""
        self.last_partial_confidence: Optional[float] = None
        # Độ dài `pcm` ngay sau frame cuối còn là giọng nói: được báo là tiếng nói, hoặc đủ to so
        # với câu (âm cuối nhỏ Silero không gắn cờ, vd. "KHÔNG" của "ĐÚNG KHÔNG"). Cắt đuôi final.
        self.speech_end = 0

    @property
    def duration_ms(self) -> float:
        return len(self.pcm) / 2 / self._rate * 1000

    def add(self, frame: bytes, is_speech: bool, *, is_preroll: bool = False) -> bool:
        """False khi frame chỉ vào pre-roll (chưa có câu nào đang mở)."""
        level = _level_dbfs(frame) if self._track_levels else -96.0
        if self._track_levels and not is_speech:
            self._quiet_levels.append(level)
        if not self.in_speech and not is_speech:
            self._pre_speech.extend(frame)
            if self._lookback:
                self._pre_levels.append((len(frame), level))
            if is_preroll:
                # Replay is bounded upstream. Keep it plus the usual onset allowance;
                # later silence still ages it out instead of retaining it indefinitely.
                self._pre_speech_limit = max(
                    self._pre_speech_limit, len(self._pre_speech) + self._pre_speech_max
                )
            keep = max(self._pre_speech_limit, self._lookback)
            del self._pre_speech[: max(0, len(self._pre_speech) - keep)]
            kept = 0
            for index in range(len(self._pre_levels) - 1, -1, -1):
                kept += self._pre_levels[index][0]
                if kept > len(self._pre_speech):
                    for _ in range(index + 1):
                        self._pre_levels.popleft()
                    break
            return False
        if not self.in_speech:
            lead = min(len(self._pre_speech), max(self._pre_speech_limit, self._onset_bytes(level)))
            self.pcm.extend(self._pre_speech[len(self._pre_speech) - lead :])
            self._pre_speech.clear()
            self._pre_levels.clear()
            self._pre_speech_limit = self._pre_speech_max
            self._peak = -96.0
            self.in_speech = True
        self.pcm.extend(frame)
        frame_ms = len(frame) / 2 / self._rate * 1000
        self.since_partial_ms += frame_ms
        if is_speech:
            self.speech_ms += frame_ms
            self.silent_ms = 0.0
            self.speech_end = len(self.pcm)
            self._peak = max(self._peak, level)
        else:
            self.silent_ms += frame_ms
            if self._track_levels and level >= self._voice_threshold(
                self._peak, below_db=_VOICE_END_BELOW_PEAK_DB
            ):
                self.speech_end = len(self.pcm)
        return True

    def _voice_threshold(self, reference: float, *, below_db: Optional[float] = None) -> float:
        """Frame "còn là giọng": hơn nền >= `_ONSET_ABOVE_FLOOR_DB` và không nhỏ hơn mức giọng
        `reference` quá `below_db` (mặc định `_ONSET_BELOW_SPEECH_DB`; không tính tiếng thở)."""
        if below_db is None:
            below_db = _ONSET_BELOW_SPEECH_DB
        floor = float(np.percentile(self._quiet_levels, 20)) if self._quiet_levels else -96.0
        return max(floor + _ONSET_ABOVE_FLOOR_DB, reference - below_db)

    def _onset_bytes(self, detected_level: float) -> int:
        """Số byte trước frame được báo là tiếng nói cần giữ để không mất phần đầu câu: lần
        ngược từ frame gần nhất qua các frame đủ to (hơn nền >= `_ONSET_ABOVE_FLOOR_DB` và không
        nhỏ hơn đoạn vừa nhận ra quá `_ONSET_BELOW_SPEECH_DB` — không kéo theo tiếng thở, tiếng
        động nhỏ), cho phép ngắt <= `_ONSET_MAX_GAP_FRAMES` frame, rồi thêm một khoảng đệm."""
        if not self._lookback or not self._pre_levels:
            return 0
        recent = [level for _, level in list(self._pre_levels)[-_ONSET_REF_FRAMES:]]
        threshold = self._voice_threshold(max([detected_level, *recent]))
        levels = list(self._pre_levels)
        onset, gap = len(levels), 0
        for index in range(len(levels) - 1, -1, -1):
            if levels[index][1] >= threshold:
                onset, gap = index, 0
            else:
                gap += 1
                if gap > _ONSET_MAX_GAP_FRAMES:
                    break
        if onset == len(levels):
            return 0
        start = max(0, onset - _ONSET_MARGIN_FRAMES)
        return sum(size for size, _ in levels[start:])

    def close(self, *, still_speaking: bool) -> None:
        """Đã chốt câu. `still_speaking`: chốt cưỡng bức giữa lúc đang nói — mở ngay câu mới."""
        self.pcm.clear()
        self.in_speech = still_speaking
        self.speech_ms = self.silent_ms = self.since_partial_ms = 0.0
        self.last_partial = ""
        self.last_partial_confidence = None
        self.speech_end = 0
        self._pre_speech_limit = self._pre_speech_max

    def final_pcm(self, tail_ms: Optional[int]) -> bytes:
        """Audio cho final: tới frame cuối còn là giọng nói + `tail_ms` (None = cả buffer)."""
        if tail_ms is None or not self.speech_end:
            return bytes(self.pcm)
        end = self.speech_end + self._rate * tail_ms // 1000 * 2
        return bytes(self.pcm[:end])

    def discard(self) -> None:
        """Pipeline ngừng đưa audio: audio trước và sau chỗ ngắt không liền nhau."""
        self.close(still_speaking=False)
        self._pre_speech.clear()
        self._pre_levels.clear()


# `_Utterance._onset_bytes` (frame 30 ms): nền = phân vị 20 của ~3 s frame không phải tiếng nói.
_ONSET_FLOOR_FRAMES = 100
_ONSET_ABOVE_FLOOR_DB = 12.0
# Đầu câu chỉ lần ngược qua frame gần bằng giọng vừa nhận ra ("HỌ" -17..-22 dB khi giọng -10..-12):
# 25 dB kéo theo tiếng thở/tiếng động, noise-bench 08/10 mất lượt "ĐÚNG RỒI", thêm "ẤY".
_ONSET_BELOW_SPEECH_DB = 15.0
# Đuôi câu: âm cuối nhỏ vẫn là giọng ("KHÔNG" của "ĐÚNG KHÔNG" ~17 dB dưới đỉnh câu).
_VOICE_END_BELOW_PEAK_DB = 25.0
_ONSET_REF_FRAMES = 5
_ONSET_MAX_GAP_FRAMES = 2
_ONSET_MARGIN_FRAMES = 3


def _level_dbfs(frame: bytes) -> float:
    samples = np.frombuffer(frame, dtype=np.int16).astype(np.float64)
    if not samples.size:
        return -96.0
    return 10 * math.log10(float(np.mean(samples * samples)) / 32768.0**2 + 1e-10)


# `_prefer_confident_partial`: final ngắn đổi hẳn chữ so với partial cuối, tin cậy thấp hơn nhiều.
_FLIP_MAX_WORDS = 2
_FLIP_MAX_FINAL_CONFIDENCE = 0.5
_FLIP_MIN_CONFIDENCE_GAP = 0.3


def _prefer_confident_partial(decoded: _Decoded, utterance: "_Utterance") -> _Decoded:
    """Final <= 2 từ, tin cậy thấp, không nối tiếp partial cuối (tin cậy cao hơn hẳn): giữ partial.

    Câu trả lời ngắn hay bị lật ở final ("BÂY GIỜ" 0,94 -> "ĐƯỢC" 0,28 — đồng ý giả). Final là
    phần mở rộng của partial ("KHÔNG" -> "KHÔNG ĐƯỢC") thì luôn giữ final."""
    partial, partial_confidence = utterance.last_partial, utterance.last_partial_confidence
    final_words, partial_words = decoded.text.split(), partial.split()
    if (
        not partial_words
        or partial_confidence is None
        or decoded.confidence is None
        or len(final_words) > _FLIP_MAX_WORDS
        or len(partial_words) > _FLIP_MAX_WORDS + 1
        or final_words[: len(partial_words)] == partial_words
        or decoded.confidence >= _FLIP_MAX_FINAL_CONFIDENCE
        or partial_confidence - decoded.confidence < _FLIP_MIN_CONFIDENCE_GAP
    ):
        return decoded
    logger.debug(
        "zipformer: final confidence=%.3f lật khỏi partial confidence=%.3f — giữ partial",
        decoded.confidence,
        partial_confidence,
    )
    return _Decoded(partial, partial_confidence)


def _final_event(decoded: _Decoded) -> TranscriptEvent:
    if decoded.confidence is not None:
        # Không log text (PII); chỉ số để đối chiếu với turn qua thời điểm log.
        logger.debug(
            "zipformer final confidence=%.3f min_token_prob=%.3f",
            decoded.confidence,
            decoded.min_token_prob,
        )
    return TranscriptEvent(text=decoded.text, is_final=True, confidence=decoded.confidence)
