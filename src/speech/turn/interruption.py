"""Interruption Controller — barge-in.

Trong lúc bot nói, input pipeline vẫn hoạt động (VAD/ASR không bị tạm dừng). Controller
này chỉ quyết định KHI NÀO việc user bắt đầu nói giữa lúc bot đang nói đủ để coi là một
lần ngắt lời thật — tránh false interruption từ noise/backchannel ngắn ("ừ", ho, tiếng
động). Khi xác nhận, gọi `tts.cancel()`; việc dừng publish audio đã yield thuộc trách
nhiệm của caller (CallBridge), không phải của class này.

Barge-in CHỈ được xác nhận qua `on_partial_transcript`, luôn đi qua `_passes_gate()`
(duration + nội dung có nghĩa + confidence nếu có) — bug thật đã gặp qua 4 lỗ hổng độc
lập, cả bốn đều cho phép confirm mà không đủ điều kiện:
1. `on_partial_transcript` từng tự xác nhận ngay khi ASR trả về BẤT KỲ text non-empty
   nào, bỏ qua hoàn toàn duration/nội dung — ASR hallucinate 1 cụm từ trông "có vẻ hợp
   lệ" từ noise nền (quạt máy) là đủ để cắt ngang TTS.
2. Từng có `confirm_if_sustained()` xác nhận CHỈ bằng duration VAD (không cần ASR trả
   chữ nào) — quạt chạy đều kéo dài liên tục vượt `min_speech_ms` tự cắt lời bot mà
   không có nội dung nói thật nào. Đã bỏ hẳn method này: duration một mình không còn là
   tín hiệu đủ, phải luôn đi kèm ASR partial có nghĩa.
3. `is_meaningful_text()`/duration một mình vẫn không đủ khi VAD nhận NHẦM noise phòng
   không đồng đều thành speech_start GIỮA LÚC bot đang nói (khác case #2 — ở đây ASR có
   generate ra chữ, chỉ là chữ đó bị hallucinate từ noise, không phải audio rỗng): log
   thật đã gặp qua LiveKit demo, "ĐÂY" được confirm liên tục dù user hoàn toàn im lặng.
   `Speech Admission` (pipeline.py::_fanout()) KHÔNG áp dụng cho nhánh candidate này (audio
   phải tới ASR thật để có thể tự confirm, chặn ở Admission sẽ deadlock) — `TurnValidator`
   (`min_snr_db`/`TranscriptEvidenceTracker`, xem docs/reference/livekit-architecture.md
   §5.4) là lớp phòng thủ cuối, tuỳ chọn qua tham số `validator`.
4. `_passes_gate()` từng coi `ValidationDecision.WAIT` tương đương `ACCEPT` (chỉ DROP mới
   reject) — log thật qua LiveKit: SNR vừa phải (~14dB, không đủ thấp để trigger DROP ở
   `min_snr_db` mặc định) + text ngắn hallucinate ("ĐÚNG") + `stability=UNKNOWN` khiến
   `TurnValidator.evaluate()` trả WAIT, nhưng gate vẫn xác nhận barge-in ngay. Sửa: WAIT
   giờ cũng reject như DROP (khác biệt duy nhất là WAIT không mang ý nghĩa "chắc chắn rác"
   — chỉ đơn giản chưa đủ bằng chứng để xác nhận NGAY LẦN NÀY).
"""

import logging
import time
from enum import Enum, auto
from typing import Optional, Protocol

from speech.asr.evidence import StabilityVerdict
from speech.asr.vad.base import VadEvent
from speech.audio.noise_tracker import NoiseEvidence
from speech.turn.controller import is_meaningful_text
from speech.turn.validator import TurnValidator, ValidationDecision
from speech.types import TranscriptEvent

logger = logging.getLogger(__name__)


class _Cancellable(Protocol):
    async def cancel(self) -> None: ...


class InterruptionState(Enum):
    IDLE = auto()
    BOT_SPEAKING = auto()
    INTERRUPTION_CANDIDATE = auto()
    INTERRUPTED = auto()


class InterruptionController:
    def __init__(
        self,
        tts: _Cancellable,
        *,
        min_speech_ms: int = 200,
        min_confidence: Optional[float] = None,
        clock: Optional[object] = None,
        validator: Optional[TurnValidator] = None,
    ) -> None:
        """`min_confidence`: nếu ASR provider cung cấp `TranscriptEvent.confidence` (hiện
        ZipFormer luôn trả `None` — chưa hỗ trợ), partial dưới ngưỡng này bị gate chặn
        như audio chưa đủ tin cậy. `None` (mặc định) tắt hẳn kiểm tra này thay vì âm thầm
        cho qua mọi giá trị — không giả vờ lọc bằng một tín hiệu provider không cung cấp.

        `validator` (tuỳ chọn, mặc định `None` — giữ hành vi cũ 100%): dùng CHUNG
        `TurnValidator` với `TurnController` (cùng logic SNR/stability, xem module
        docstring #3) — nhưng ở đây CHỈ có quyền CHẶN THÊM (DROP hoặc WAIT -> reject),
        không bao giờ được xác nhận sớm hơn `_passes_gate()` hiện có (chỉ ACCEPT đi tiếp
        qua gate cũ) — barge-in thà bỏ lỡ còn hơn cắt lời bot sai. Khác `TurnController`
        (nơi WAIT có cơ hội chờ event mới rồi thử lại _try_emit): `on_partial_transcript`
        không tự lặp lại khi có evidence mới — WAIT ở đây coi như "chưa đủ bằng chứng,
        chưa xác nhận NGAY LẦN NÀY", partial kế tiếp (nếu ASR còn gửi) sẽ được đánh giá
        lại từ đầu. Bug thật đã gặp: SNR vừa phải (~14dB, không đủ thấp để DROP) + text
        ngắn hallucinate ("ĐÚNG") + stability UNKNOWN -> validator trả WAIT nhưng vẫn bị
        gate cũ cho qua vì WAIT từng bị đối xử như ACCEPT, xác nhận barge-in giả dù user
        không nói gì."""
        self._tts = tts
        self._min_speech_s = min_speech_ms / 1000
        self._min_confidence = min_confidence
        self._clock = clock or time.monotonic
        self._validator = validator
        self._noise_evidence: Optional[NoiseEvidence] = None
        self._stability: StabilityVerdict = StabilityVerdict.UNKNOWN
        self._state = InterruptionState.IDLE
        self._candidate_started_at: Optional[float] = None
        # Counter đơn điệu để media fanout nhận biết một interruption đã được xác nhận
        # ngay cả khi state đã trở về IDLE sau khi TTS dừng.
        self._confirmed_count = 0

    @property
    def state(self) -> InterruptionState:
        return self._state

    @property
    def confirmed_count(self) -> int:
        return self._confirmed_count

    def on_bot_started_speaking(self) -> None:
        self._state = InterruptionState.BOT_SPEAKING
        self._candidate_started_at = None
        self._stability = StabilityVerdict.UNKNOWN

    def on_bot_stopped_speaking(self) -> None:
        self._state = InterruptionState.IDLE
        self._candidate_started_at = None

    async def on_speech_started(self, event: VadEvent) -> bool:
        """VAD speech_start trong lúc bot nói -> ứng viên ngắt lời. Trả True nếu chuyển
        thẳng sang INTERRUPTED ngay (một số caller có thể gọi việc này khi đã biết chắc
        đủ điều kiện, ví dụ độ dài audio frame đã đo sẵn); mặc định chỉ đánh dấu ứng viên,
        xác nhận thật qua `on_partial_transcript` khi ASR có chữ và qua được gate."""
        if self._state not in (
            InterruptionState.BOT_SPEAKING,
            InterruptionState.INTERRUPTION_CANDIDATE,
        ):
            return False
        if self._state == InterruptionState.BOT_SPEAKING:
            self._state = InterruptionState.INTERRUPTION_CANDIDATE
            self._candidate_started_at = self._clock()
        return False

    async def on_partial_transcript(self, event: TranscriptEvent) -> bool:
        """ASR đã nhận ra chữ trong lúc là INTERRUPTION_CANDIDATE -> tín hiệu DUY NHẤT
        xác nhận ngắt lời (không còn đường xác nhận thuần-duration — xem module
        docstring). Phải qua `_passes_gate` (duration + nội dung có nghĩa + confidence
        nếu có): text non-empty một mình không đủ, vì ASR có thể hallucinate ra chữ từ
        noise nền (quạt máy, tiếng ồn phòng) ngay trong vài trăm ms đầu của candidate."""
        if self._state != InterruptionState.INTERRUPTION_CANDIDATE:
            return False
        if not self._passes_gate(event):
            # DEBUG only: text có thể chứa nội dung nhạy cảm nếu barge-in thật — nhưng
            # cần thấy được để chẩn đoán false-positive từ noise nền (quạt máy...).
            logger.debug(
                "interruption: gate REJECTED text=%r confidence=%s duration_s=%s",
                event.text,
                event.confidence,
                (self._clock() - self._candidate_started_at)
                if self._candidate_started_at is not None
                else None,
            )
            return False
        logger.debug(
            "interruption: gate CONFIRMED barge-in text=%r confidence=%s",
            event.text,
            event.confidence,
        )
        await self._confirm()
        return True

    def _has_min_duration(self) -> bool:
        if self._candidate_started_at is None:
            return False
        return self._clock() - self._candidate_started_at >= self._min_speech_s

    def _passes_gate(self, event: TranscriptEvent) -> bool:
        """Gate chung trước khi xác nhận barge-in — tương ứng khối INTERRUPTION GATE
        (duration + acoustic confidence + transcript/words + backchannel detection).
        Không đủ MỘT điều kiện nào là đủ để chặn, kể cả khi các điều kiện khác đã qua."""
        if not self._has_min_duration():
            return False
        if not is_meaningful_text(event.text):
            return False
        if (
            self._min_confidence is not None
            and event.confidence is not None
            and event.confidence < self._min_confidence
        ):
            return False
        if self._validator is not None:
            decision = self._validator.evaluate(
                event.text,
                noise_evidence=self._noise_evidence,
                stability=self._stability,
            )
            logger.debug(
                "interruption: validator decision=%s text=%r snr_db=%s stability=%s",
                decision,
                event.text,
                self._noise_evidence.snr_db if self._noise_evidence is not None else None,
                self._stability,
            )
            if decision != ValidationDecision.ACCEPT:
                # DROP hoặc WAIT: chưa đủ bằng chứng để xác nhận barge-in NGAY LẦN NÀY —
                # không tự ý confirm sớm hơn (xem docstring __init__). Khác DROP (rõ ràng
                # là hallucination), WAIT không reset candidate — partial kế tiếp (nếu có)
                # vẫn được đánh giá lại bình thường.
                return False
        return True

    def on_evidence_updated(
        self,
        *,
        noise_evidence: Optional[NoiseEvidence] = None,
        stability: Optional[StabilityVerdict] = None,
    ) -> None:
        """Caller (`pipeline.py::_drain_asr()`) gọi song song với `on_partial_transcript()`
        khi có `NoiseTracker`/`TranscriptEvidenceTracker` cấu hình — cùng cơ chế với
        `TurnController.on_evidence_updated()`. Tham số `None` (mặc định) không ghi đè."""
        if noise_evidence is not None:
            self._noise_evidence = noise_evidence
        if stability is not None:
            self._stability = stability

    async def on_speech_ended_without_confirmation(self) -> None:
        """VAD speech_end trong lúc vẫn là INTERRUPTION_CANDIDATE (chưa đủ điều kiện xác
        nhận) -> coi là backchannel/noise ngắn, quay lại BOT_SPEAKING, không cancel TTS."""
        if self._state == InterruptionState.INTERRUPTION_CANDIDATE:
            self._state = InterruptionState.BOT_SPEAKING
            self._candidate_started_at = None
            self._stability = StabilityVerdict.UNKNOWN

    async def _confirm(self) -> None:
        self._state = InterruptionState.INTERRUPTED
        self._confirmed_count += 1
        await self._tts.cancel()
