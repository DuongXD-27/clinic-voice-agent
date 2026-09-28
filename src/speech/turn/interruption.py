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
   Nhánh candidate này không thể lọc trước ASR (audio phải tới ASR thật để có thể tự
   confirm, chặn ở đó sẽ deadlock) — `TurnValidator`
   (`min_snr_db`/`TranscriptEvidenceTracker`, xem docs/reference/livekit-architecture.md
   §5.4) là lớp phòng thủ cuối, tuỳ chọn qua tham số `validator`.
4. `_passes_gate()` từng coi `ValidationDecision.WAIT` tương đương `ACCEPT` (chỉ DROP mới
   reject) — log thật qua LiveKit: SNR vừa phải (~14dB, không đủ thấp để trigger DROP ở
   `min_snr_db` mặc định) + text ngắn hallucinate ("ĐÚNG") + `stability=UNKNOWN` khiến
   `TurnValidator.evaluate()` trả WAIT, nhưng gate vẫn xác nhận barge-in ngay. Sửa: WAIT
   giờ cũng reject như DROP (khác biệt duy nhất là WAIT không mang ý nghĩa "chắc chắn rác"
   — chỉ đơn giản chưa đủ bằng chứng để xác nhận NGAY LẦN NÀY).
5. Echo chính giọng bot qua loa/mic: bug thật qua LiveKit — bot đang đọc câu chào (TTS),
   browser echo cancellation không loại hết audio đó (đặc biệt loa ngoài công suất lớn/
   phòng vang), VAD/ASR nghe lại CHÍNH câu bot đang nói và tưởng là barge-in thật. Khác
   case #3 (hallucination từ noise ngẫu nhiên): ở đây ASR nghe ĐÚNG nội dung âm thanh thật
   (không phải hallucinate), transcript hội tụ ổn định (`stability=CONVERGING`) — qua được
   mọi gate hiện có (duration, meaningful text, SNR, stability) vì bản chất tín hiệu không
   khác gì user nói thật. Sửa: `on_bot_started_speaking(bot_text)` nhận text bot ĐANG đọc,
   `_passes_gate()` so khớp mờ (rapidfuzz, cùng thư viện `TranscriptEvidenceTracker` đã
   dùng) giữa candidate text và `bot_text` — giống cao thì reject, không xác nhận barge-in.
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


_ECHO_SIMILARITY_THRESHOLD = 70.0


class InterruptionController:
    def __init__(
        self,
        tts: _Cancellable,
        *,
        min_speech_ms: int = 200,
        min_confidence: Optional[float] = None,
        clock: Optional[object] = None,
        validator: Optional[TurnValidator] = None,
        min_snr_db: Optional[float] = None,
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
        không nói gì.

        `min_snr_db` (tuỳ chọn, mặc định `None` — tắt hẳn, giữ hành vi cũ): ngưỡng SNR
        RIÊNG cho barge-in, KHÔNG dùng chung `validator.min_snr_db` — validator chỉ áp
        dụng luật SNR cho text NGẮN (<=2 từ, xem TurnValidator.evaluate()), nhưng echo
        giọng bot qua loa/mic vẫn có thể tạo ra text DÀI, mạch lạc, `stability=CONVERGING`
        (âm thanh thật, chỉ sai nguồn — không phải hallucinate từ noise ngẫu nhiên như bug
        #3), nên né được luật đó. Bug thật đã gặp: candidate 5 từ "EM ĐÃ CHUẨN BỊ Ở ĐÂY"
        snr_db=-25.56 (rất thấp) vẫn được validator ACCEPT vì áp dụng nhánh CONVERGING,
        không phải nhánh short-text+low-snr. Kiểm tra này áp dụng KHÔNG PHÂN BIỆT độ dài
        text (khác validator) — trong lúc bot đang nói, chấp nhận bỏ lỡ barge-in thật SNR
        thấp (user nói khẽ) còn hơn cắt lời bot vì nghe lại chính nó."""
        self._tts = tts
        self._min_speech_s = min_speech_ms / 1000
        self._min_confidence = min_confidence
        self._clock = clock or time.monotonic
        self._validator = validator
        self._min_snr_db = min_snr_db
        self._noise_evidence: Optional[NoiseEvidence] = None
        self._stability: StabilityVerdict = StabilityVerdict.UNKNOWN
        self._state = InterruptionState.IDLE
        self._candidate_started_at: Optional[float] = None
        # Counter đơn điệu để media fanout nhận biết một interruption đã được xác nhận
        # ngay cả khi state đã trở về IDLE sau khi TTS dừng.
        self._confirmed_count = 0
        # Text bot ĐANG đọc (câu đầy đủ, không phải chunk TTS) — dùng để phát hiện echo,
        # xem bug #5 trong docstring module.
        self._bot_text = ""

    @property
    def state(self) -> InterruptionState:
        return self._state

    @property
    def confirmed_count(self) -> int:
        return self._confirmed_count

    def on_bot_started_speaking(self, bot_text: str = "") -> None:
        """`bot_text`: câu đầy đủ bot chuẩn bị đọc (TTS input, không phải PCM) — dùng để
        `_passes_gate()` phát hiện echo (xem bug #5 trong docstring module). `""` (mặc
        định) tắt hẳn kiểm tra này — giữ hành vi cũ cho caller chưa cập nhật."""
        self._state = InterruptionState.BOT_SPEAKING
        self._candidate_started_at = None
        self._stability = StabilityVerdict.UNKNOWN
        self._bot_text = bot_text

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
        if self._is_echo_of_bot(event.text):
            logger.debug(
                "interruption: gate REJECTED (echo of bot) text=%r bot_text=%r",
                event.text,
                self._bot_text,
            )
            return False
        if (
            self._min_snr_db is not None
            and self._noise_evidence is not None
            and self._noise_evidence.snr_db < self._min_snr_db
        ):
            # Áp dụng KHÔNG PHÂN BIỆT độ dài text — khác TurnValidator (chỉ xét SNR cho
            # text ngắn), xem docstring __init__.
            logger.debug(
                "interruption: gate REJECTED (low snr) text=%r snr_db=%.1f",
                event.text,
                self._noise_evidence.snr_db,
            )
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

    def _is_echo_of_bot(self, candidate_text: str) -> bool:
        """True nếu `candidate_text` giống cao với `self._bot_text` (câu bot đang đọc) —
        dấu hiệu đây là chính giọng bot vọng lại qua mic, không phải user nói (xem bug #5
        module docstring). `partial_ratio` (không phải `ratio` như TranscriptEvidenceTracker
        dùng cho stability): candidate thường chỉ là 1 ĐOẠN của câu bot (ASR chưa nghe hết
        cả câu khi bot còn đang đọc dở), `ratio` so toàn chuỗi sẽ cho điểm thấp giả tạo dù
        đúng là echo — `partial_ratio` tìm đoạn khớp tốt nhất bên trong chuỗi dài hơn."""
        if not self._bot_text or not candidate_text.strip():
            return False
        from rapidfuzz import fuzz

        similarity = fuzz.partial_ratio(candidate_text.strip().lower(), self._bot_text.lower())
        return similarity >= _ECHO_SIMILARITY_THRESHOLD

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
            # Nếu đây là audio user nói thật (không phải echo/backchannel), nó biến mất
            # không có turn nào — VAD/ASR đã nhận đủ để tạo candidate nhưng
            # _passes_gate() (duration/nội dung/validator) chưa từng qua trước khi
            # speech_end tới. Log DEBUG only: candidate_started_at có thể None nếu chưa
            # từng qua on_speech_started (không nên xảy ra ở nhánh này, nhưng phòng thủ).
            duration_s = (
                self._clock() - self._candidate_started_at
                if self._candidate_started_at is not None
                else None
            )
            logger.debug(
                "interruption: candidate reverted to BOT_SPEAKING without confirmation "
                "duration_s=%s",
                duration_s,
            )
            self._state = InterruptionState.BOT_SPEAKING
            self._candidate_started_at = None
            self._stability = StabilityVerdict.UNKNOWN

    async def _confirm(self) -> None:
        self._state = InterruptionState.INTERRUPTED
        self._confirmed_count += 1
        await self._tts.cancel()
