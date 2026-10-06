"""Interruption Controller — xác nhận người gọi ngắt lời (barge-in) khi bot đang nói.

Luồng: VAD speech_start lúc bot nói -> INTERRUPTION_CANDIDATE -> ASR có partial và partial qua
gate -> INTERRUPTED, gọi `tts.cancel()`. VAD speech_end trước đó -> quay lại BOT_SPEAKING.
Việc dừng phát audio đã gửi là của CallBridge.

Gate (`_passes_gate`) — mọi điều kiện đều phải qua; thà bỏ lỡ một lần ngắt lời còn hơn cắt lời
bot sai:
1. Ứng viên kéo dài đủ `min_speech_ms` — chặn tiếng ho, "ừ".
2. Có chữ có nghĩa (`is_meaningful_text`) — không xác nhận chỉ bằng thời lượng (quạt máy).
3. Không phải tiếng bot vọng lại: các từ của partial trùng một đoạn từ liên tiếp trong câu bot
   (khớp đúng khi partial ngắn, khớp mờ khi dài — xem `_is_echo_of_bot`).
4. SNR >= `min_snr_db` (áp cho mọi độ dài câu) — tiếng vọng qua loa/mic có SNR rất thấp.
5. TurnValidator trả ACCEPT; WAIT cũng bị chặn (chưa đủ bằng chứng ở lần này).
"""

import logging
import time
from enum import Enum, auto
from typing import Optional, Protocol

from speech.asr.evidence import StabilityVerdict
from speech.asr.vad.base import VadEvent
from speech.audio.noise_tracker import NoiseEvidence
from speech.turn.controller import is_meaningful_text, spoken_words
from speech.turn.validator import TurnValidator, ValidationDecision
from speech.types import TranscriptEvent

logger = logging.getLogger(__name__)

# Partial từ chừng này từ trở lên mới so khớp mờ với câu bot; ngắn hơn thì phải trùng nguyên văn.
_ECHO_FUZZY_MIN_WORDS = 3
_ECHO_SIMILARITY_THRESHOLD = 70.0


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
        clock: Optional[object] = None,
        validator: Optional[TurnValidator] = None,
        min_snr_db: Optional[float] = None,
    ) -> None:
        """`validator`: dùng chung TurnValidator với TurnController, ở đây chỉ để chặn thêm.
        `min_snr_db`: None = tắt điều kiện 4."""
        self._tts = tts
        self._min_speech_s = min_speech_ms / 1000
        self._clock = clock or time.monotonic
        self._validator = validator
        self._min_snr_db = min_snr_db
        self._noise_evidence: Optional[NoiseEvidence] = None
        self._stability = StabilityVerdict.UNKNOWN
        self._state = InterruptionState.IDLE
        self._candidate_started_at: Optional[float] = None
        self._bot_text = ""  # câu bot đang đọc, để nhận ra tiếng vọng

    @property
    def state(self) -> InterruptionState:
        return self._state

    def on_bot_started_speaking(self, bot_text: str = "") -> None:
        """`bot_text`: câu đầy đủ bot sắp đọc; "" tắt kiểm tra tiếng vọng."""
        self._state = InterruptionState.BOT_SPEAKING
        self._candidate_started_at = None
        self._stability = StabilityVerdict.UNKNOWN
        self._bot_text = bot_text

    def on_bot_stopped_speaking(self) -> None:
        self._state = InterruptionState.IDLE
        self._candidate_started_at = None

    async def on_speech_started(self, event: VadEvent) -> None:
        if self._state == InterruptionState.BOT_SPEAKING:
            self._state = InterruptionState.INTERRUPTION_CANDIDATE
            self._candidate_started_at = self._clock()

    async def on_partial_transcript(self, event: TranscriptEvent) -> bool:
        """Đường duy nhất xác nhận ngắt lời. Trả True nếu vừa xác nhận."""
        if self._state != InterruptionState.INTERRUPTION_CANDIDATE:
            return False
        if not self._passes_gate(event):
            # DEBUG: text có thể chứa PII, nhưng cần để chẩn đoán barge-in giả.
            logger.debug(
                "interruption: gate REJECTED text=%r duration_s=%s",
                event.text,
                self._candidate_duration_s(),
            )
            return False
        logger.debug("interruption: gate CONFIRMED barge-in text=%r", event.text)
        await self._confirm()
        return True

    async def _confirm(self) -> None:
        self._state = InterruptionState.INTERRUPTED
        await self._tts.cancel()

    def on_evidence_updated(
        self,
        *,
        noise_evidence: Optional[NoiseEvidence] = None,
        stability: Optional[StabilityVerdict] = None,
    ) -> None:
        """Gọi từ pipeline mỗi khi có transcript mới; None = giữ giá trị cũ."""
        if noise_evidence is not None:
            self._noise_evidence = noise_evidence
        if stability is not None:
            self._stability = stability

    async def on_speech_ended_without_confirmation(self) -> None:
        """VAD speech_end khi chưa xác nhận: coi là tiếng động/backchannel, không cancel TTS."""
        if self._state != InterruptionState.INTERRUPTION_CANDIDATE:
            return
        logger.debug(
            "interruption: candidate reverted without confirmation duration_s=%s",
            self._candidate_duration_s(),
        )
        self._state = InterruptionState.BOT_SPEAKING
        self._candidate_started_at = None
        self._stability = StabilityVerdict.UNKNOWN

    def _candidate_duration_s(self) -> Optional[float]:
        if self._candidate_started_at is None:
            return None
        return self._clock() - self._candidate_started_at

    def _passes_gate(self, event: TranscriptEvent) -> bool:
        duration_s = self._candidate_duration_s()
        if duration_s is None or duration_s < self._min_speech_s:
            return False
        if not is_meaningful_text(event.text):
            return False
        if self._is_echo_of_bot(event.text):
            logger.debug("interruption: REJECTED echo of bot text=%r", event.text)
            return False
        snr_db = self._noise_evidence.snr_db if self._noise_evidence is not None else None
        if self._min_snr_db is not None and snr_db is not None and snr_db < self._min_snr_db:
            logger.debug("interruption: REJECTED low snr text=%r snr_db=%.1f", event.text, snr_db)
            return False
        if self._validator is not None:
            decision = self._validator.evaluate(
                event.text, noise_evidence=self._noise_evidence, stability=self._stability
            )
            logger.debug(
                "interruption: validator decision=%s text=%r snr_db=%s stability=%s",
                decision,
                event.text,
                snr_db,
                self._stability,
            )
            if decision != ValidationDecision.ACCEPT:
                return False
        return True

    def _is_echo_of_bot(self, candidate_text: str) -> bool:
        """ASR thường chỉ nghe được một đoạn của câu bot đang đọc dở, nên so với từng cửa sổ
        từ liên tiếp cùng độ dài trong câu bot.

        Không so ở mức ký tự (`partial_ratio` cũ): partial ngắn của người gọi như "Anh",
        "Anh muốn" luôn khớp một khúc nào đó của câu bot ("...anh chị...") — đo 06/10, cả 15
        partial thật bị coi là echo, 0/12 lần ngắt lời được xác nhận. Partial dưới
        `_ECHO_FUZZY_MIN_WORDS` từ chỉ là echo khi trùng nguyên văn một đoạn câu bot."""
        candidate = spoken_words(candidate_text).split()
        bot = spoken_words(self._bot_text).split()
        if not candidate or len(candidate) > len(bot):
            return False
        windows = [
            " ".join(bot[i : i + len(candidate)]) for i in range(len(bot) - len(candidate) + 1)
        ]
        joined = " ".join(candidate)
        if len(candidate) < _ECHO_FUZZY_MIN_WORDS:
            return joined in windows
        from rapidfuzz import fuzz

        return max(fuzz.ratio(joined, window) for window in windows) >= _ECHO_SIMILARITY_THRESHOLD
