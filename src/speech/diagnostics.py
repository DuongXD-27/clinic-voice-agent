"""Chẩn đoán lượt nói trên đường streaming — chỉ quan sát, KHÔNG đổi quyết định nào.

Mỗi đoạn giọng (VAD speech_start của TurnController) có một `utterance_id` và đúng MỘT kết
cục cuối: EMITTED (thành lượt gửi core) hoặc DROPPED kèm `stage`/`reason` của cổng đã bỏ nó.
Mục đích: biết chắc cổng nào đang bỏ câu ngắn / cho lượt giả lọt, thay vì đoán (plan âm thanh
Web/SIP, PR1). Chỉ ghi số — không bao giờ ghi text (PII).

ZipFormer bỏ đoạn quá ngắn (`min_decode_ms`) bên trong provider, không có đường báo lên; nó gọi
`report_asr_event()` và bản ghi đến đúng cuộc gọi qua contextvar mà `STTPipeline.stream()` gắn
cho task ASR — không phải đổi chữ ký `stream()` của mọi provider.
"""

from __future__ import annotations

import contextvars
import logging
import time
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Callable, Optional, Protocol

from speech.asr.vad.silero_probe import VOICE_PROBABILITY

logger = logging.getLogger(__name__)

EMITTED = "EMITTED"
DROPPED = "DROPPED"

# stage / reason của các cổng hiện có (giá trị cố định để đếm được)
STAGE_TURN = "turn"
STAGE_CONTENT = "content"
STAGE_DURATION = "duration"
STAGE_VALIDATOR = "validator"
STAGE_BOT_SPEAKING = "bot_speaking"
STAGE_ASR = "asr"

REASON_EMITTED = "emitted"
REASON_SUPERSEDED = "superseded"
REASON_NOT_MEANINGFUL = "not_meaningful"
REASON_MIN_SPEECH = "min_speech"
REASON_POST_BOT_GUARD = "post_bot_guard"
REASON_DURING_BOT_SPEECH = "during_bot_speech"
REASON_MIN_DECODE = "min_decode"
REASON_NO_TEXT = "no_text"
REASON_CALL_ENDED = "call_ended"

ASR_SKIP_MIN_DECODE = "skip_min_decode"
ASR_EMPTY_DECODE = "empty_decode"
# ASR lùi pre-speech qua phần giọng bộ phân loại báo trễ (`asr_voice_lookback_ms`); kèm số ms.
ASR_VOICE_LOOKBACK = "voice_lookback"


class ProbabilityProbe(Protocol):
    def probability(self, frame: bytes) -> Optional[float]: ...


@dataclass(frozen=True)
class UtteranceRecord:
    """Mốc thời gian tính bằng giây từ frame đầu tiên của cuộc gọi."""

    utterance_id: str
    decision: str
    stage: str
    reason: str
    started_s: float
    ended_s: float
    vad_ended_s: Optional[float]
    last_speech_s: Optional[float]
    last_voice_s: Optional[float]
    speech_ms: float
    voice_ms: float
    vad_prob_mean: Optional[float]
    vad_prob_max: Optional[float]
    snr_db: Optional[float]
    guard_extra_ms: float
    words: int
    asr_skips: int
    asr_lookback_ms: float
    during_bot_speech: bool

    @property
    def endpoint_ms(self) -> Optional[float]:
        """Từ frame cuối detector còn coi là tiếng nói tới lúc có kết cục (chốt hoặc bỏ).
        Detector Silero giữ "đang nói" thêm `silero_min_silence_ms` sau khi hết tiếng, nên số
        này KHÔNG gồm phần chờ đó — xem `voice_endpoint_ms`."""
        if self.last_speech_s is None:
            return None
        return (self.ended_s - self.last_speech_s) * 1000

    @property
    def voice_endpoint_ms(self) -> Optional[float]:
        """Từ frame cuối Silero thô thấy giọng (probe) tới lúc có kết cục: thời gian người
        gọi thật sự chờ sau khi ngừng nói. None khi không có probe."""
        if self.last_voice_s is None:
            return None
        return (self.ended_s - self.last_voice_s) * 1000


@dataclass(frozen=True)
class BargeInRecord:
    barge_in_id: str
    outcome: str  # CONFIRMED | REVERTED | BOT_STOPPED | RESET
    started_s: float
    ended_s: float

    @property
    def latency_ms(self) -> float:
        return (self.ended_s - self.started_s) * 1000


@dataclass
class _Open:
    utterance_id: str
    started_s: float
    vad_ended_s: Optional[float] = None
    last_speech_s: Optional[float] = None
    last_voice_s: Optional[float] = None
    speech_ms: float = 0.0
    voice_ms: float = 0.0
    prob_sum: float = 0.0
    prob_n: int = 0
    prob_max: Optional[float] = None
    asr_skips: int = 0
    asr_lookback_ms: float = 0.0
    during_bot_speech: bool = False


class SpeechDiagnostics:
    """Một instance cho MỘT cuộc gọi (hoặc một trial của bộ đo). `clock` phải là đồng hồ của
    TurnController (bộ đo dùng thời gian ảo). Lỗi trong callback chỉ ghi log, không lan ra
    pipeline."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        probe: Optional[ProbabilityProbe] = None,
        on_utterance: Optional[Callable[[UtteranceRecord], None]] = None,
        on_barge_in: Optional[Callable[[BargeInRecord], None]] = None,
    ) -> None:
        self._clock = clock
        self._probe = probe
        self._on_utterance = on_utterance
        self._on_barge_in = on_barge_in
        self._origin: Optional[float] = None
        self._seq = 0
        self._barge_seq = 0
        self._open: Optional[_Open] = None
        self._pending_lookback_ms = 0.0
        self._barge_started: Optional[tuple[str, float]] = None
        self._bot_speaking = False
        self.utterances: list[UtteranceRecord] = []
        self.barge_ins: list[BargeInRecord] = []

    # --- thời gian ------------------------------------------------------------------------

    def _now(self) -> float:
        now = self._clock()
        if self._origin is None:
            self._origin = now
        return now - self._origin

    # --- audio (pipeline._fanout, mỗi frame) ----------------------------------------------

    def observe_frame(
        self,
        frame: bytes,
        *,
        is_speech: bool,
        frame_ms: float,
        probability: Optional[float] = None,
    ) -> None:
        """`probability`: xác suất đã tính sẵn (probe của bộ phân loại dùng chung). Không có thì
        dùng probe riêng, nếu được cấu hình."""
        now = self._now()
        if probability is None:
            probability = self._safe_probability(frame)  # mọi frame: probe có trạng thái
        current = self._open
        if current is None or current.vad_ended_s is not None:
            # Sau speech_end, tiếng nói là của đoạn kế tiếp: speech_start của nó tới
            # TurnController muộn hơn frame đầu tiên một nhịp hàng đợi.
            return
        if is_speech:
            current.speech_ms += frame_ms
            current.last_speech_s = now
        if probability is None:
            return
        if is_speech:
            current.prob_sum += probability
            current.prob_n += 1
        current.prob_max = (
            probability if current.prob_max is None else max(current.prob_max, probability)
        )
        if probability >= VOICE_PROBABILITY:
            current.voice_ms += frame_ms
            current.last_voice_s = now

    def _safe_probability(self, frame: bytes) -> Optional[float]:
        if self._probe is None:
            return None
        try:
            return self._probe.probability(frame)
        except Exception as exc:  # quan sát không được làm hỏng cuộc gọi
            logger.warning("speech_diagnostics: probe lỗi, tắt (%s)", type(exc).__name__)
            self._probe = None
            return None

    def bot_speaking_changed(self, speaking: bool) -> None:
        self._bot_speaking = speaking
        if speaking and self._open is not None:
            self._open.during_bot_speech = True

    # --- ASR (ZipFormer qua contextvar) ---------------------------------------------------

    def on_asr_event(self, kind: str, value: float = 0.0) -> None:
        current = self._open
        if kind == ASR_SKIP_MIN_DECODE and current is not None:
            current.asr_skips += 1
        elif kind == ASR_VOICE_LOOKBACK:
            # ASR và VAD đọc hai hàng đợi riêng: ASR có thể vào đoạn mới trước khi
            # TurnController mở đoạn đó — giữ lại cho đoạn kế tiếp.
            if current is not None and current.vad_ended_s is None:
                current.asr_lookback_ms += value
            else:
                self._pending_lookback_ms += value

    # --- TurnController -------------------------------------------------------------------

    def utterance_started(self) -> str:
        self._seq += 1
        utterance_id = f"u{self._seq:05d}"
        self._open = _Open(
            utterance_id=utterance_id,
            started_s=self._now(),
            asr_lookback_ms=self._pending_lookback_ms,
            during_bot_speech=self._bot_speaking,
        )
        self._pending_lookback_ms = 0.0
        return utterance_id

    def utterance_vad_ended(self, utterance_id: Optional[str]) -> None:
        current = self._open
        if current is not None and current.utterance_id == utterance_id:
            current.vad_ended_s = self._now()

    def asr_skipped(self, utterance_id: Optional[str]) -> bool:
        current = self._open
        return (
            current is not None and current.utterance_id == utterance_id and current.asr_skips > 0
        )

    def utterance_finished(
        self,
        utterance_id: Optional[str],
        *,
        decision: str,
        stage: str,
        reason: str,
        snr_db: Optional[float] = None,
        guard_extra_s: float = 0.0,
        words: int = 0,
    ) -> Optional[UtteranceRecord]:
        """Kết cục cuối của đoạn — gọi lần hai cho cùng id thì bỏ qua (một lý do duy nhất).
        `utterance_id=None`: lượt không có speech_start (final tới trước VAD) — tự cấp id."""
        current = self._open
        if utterance_id is None:
            utterance_id = self.utterance_started()
            current = self._open
        if current is None or current.utterance_id != utterance_id:
            return None
        self._open = None
        record = UtteranceRecord(
            utterance_id=utterance_id,
            decision=decision,
            stage=stage,
            reason=reason,
            started_s=_ms(current.started_s),
            ended_s=_ms(self._now()),
            vad_ended_s=_ms(current.vad_ended_s),
            last_speech_s=_ms(current.last_speech_s),
            last_voice_s=_ms(current.last_voice_s),
            speech_ms=round(current.speech_ms, 1),
            voice_ms=round(current.voice_ms, 1),
            vad_prob_mean=(round(current.prob_sum / current.prob_n, 3) if current.prob_n else None),
            vad_prob_max=round(current.prob_max, 3) if current.prob_max is not None else None,
            snr_db=round(snr_db, 1) if snr_db is not None else None,
            guard_extra_ms=round(guard_extra_s * 1000, 1),
            words=words,
            asr_skips=current.asr_skips,
            asr_lookback_ms=round(current.asr_lookback_ms, 1),
            during_bot_speech=current.during_bot_speech,
        )
        self.utterances.append(record)
        self._emit(self._on_utterance, record)
        return record

    def close(self) -> None:
        """Hết cuộc gọi: đoạn còn mở được ghi là bỏ vì cuộc gọi kết thúc."""
        if self._open is not None:
            self.utterance_finished(
                self._open.utterance_id,
                decision=DROPPED,
                stage=STAGE_TURN,
                reason=REASON_CALL_ENDED,
            )
        if self._barge_started is not None:
            self.barge_in_finished("CALL_ENDED")

    # --- InterruptionController -----------------------------------------------------------

    def barge_in_started(self) -> None:
        self._barge_seq += 1
        self._barge_started = (f"b{self._barge_seq:04d}", self._now())

    def barge_in_finished(self, outcome: str) -> None:
        if self._barge_started is None:
            return
        barge_in_id, started_s = self._barge_started
        self._barge_started = None
        record = BargeInRecord(
            barge_in_id=barge_in_id,
            outcome=outcome,
            started_s=_ms(started_s),
            ended_s=_ms(self._now()),
        )
        self.barge_ins.append(record)
        self._emit(self._on_barge_in, record)

    # --- tổng hợp -------------------------------------------------------------------------

    def summary(self) -> dict[str, object]:
        reasons = Counter(f"{r.decision}:{r.reason}" for r in self.utterances)
        outcomes = Counter(b.outcome for b in self.barge_ins)
        return {"utterances": dict(sorted(reasons.items())), "barge_ins": dict(outcomes)}

    def _emit(self, callback, record) -> None:
        if callback is None:
            return
        try:
            callback(record)
        except Exception as exc:
            logger.warning("speech_diagnostics: callback lỗi (%s)", type(exc).__name__)


def _ms(seconds: Optional[float]) -> Optional[float]:
    """Mốc thời gian làm tròn tới mili-giây cho log gọn."""
    return round(seconds, 3) if seconds is not None else None


# --- contextvar cho provider ASR ----------------------------------------------------------

_CURRENT: contextvars.ContextVar[Optional[SpeechDiagnostics]] = contextvars.ContextVar(
    "speech_diagnostics", default=None
)


def context_with(diagnostics: Optional[SpeechDiagnostics]) -> contextvars.Context:
    """Context để tạo task ASR: provider gọi `report_asr_event()` trong task đó."""
    context = contextvars.copy_context()
    context.run(_CURRENT.set, diagnostics)
    return context


def report_asr_event(kind: str, value: float = 0.0) -> None:
    diagnostics = _CURRENT.get()
    if diagnostics is not None:
        diagnostics.on_asr_event(kind, value)


def record_as_log_fields(record: UtteranceRecord | BargeInRecord) -> dict[str, object]:
    fields = asdict(record)
    if isinstance(record, UtteranceRecord):
        for name in ("endpoint_ms", "voice_endpoint_ms"):
            value = getattr(record, name)
            fields[name] = round(value, 1) if value is not None else None
    else:
        fields["latency_ms"] = round(record.latency_ms, 1)
    return fields


__all__ = [
    "BargeInRecord",
    "SpeechDiagnostics",
    "UtteranceRecord",
    "context_with",
    "record_as_log_fields",
    "report_asr_event",
]
