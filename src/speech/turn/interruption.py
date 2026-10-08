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
5. TurnValidator trả ACCEPT; partial WAIT tiếp tục chờ, final WAIT được xét qua các gate còn lại.
"""

import logging
import math
import re
import time
from collections import deque
from enum import Enum, auto
from typing import Literal, Optional, Protocol

import numpy as np

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
# `echo_text` ước lượng lúc phát từng chữ của câu bot theo vị trí ký tự trên độ dài audio TTS.
# TTS chưa trả hết câu (stream) thì lấy tốc độ đọc câu trước trong cuộc gọi; câu đầu dùng mức này.
_DEFAULT_MS_PER_CHAR = 70.0
# Sai số ước lượng + trễ vọng (mạng, loa): chữ phát sát mép khoảng ASR nghe vẫn tính.
_ON_AIR_MARGIN_S = 0.6
# Có tiếng vọng hay không (`_echo_score`): tương quan đường bao năng lượng (dB, mỗi `_LEVEL_HOP_S`)
# giữa mic người gọi và audio bot đã phát, thử mọi độ trễ tới `_ECHO_MAX_LAG_S` (mạng hai chiều +
# loa/mic). Tiếng vọng là đặc tính của đường truyền nên đo trên CẢ phần câu bot đã phát: đoạn
# ngắn quanh lúc người gọi chen vào (1-3 s) cho tương quan ngẫu nhiên tới 0,9 khi không có vọng.
# Cần cả hai: tương quan cao, và mic có tiếng ở phần lớn lúc bot có tiếng (`coverage`) — câu
# người gọi ngắn ("Ừ", 10-30 frame) lấy tương quan lớn nhất qua các độ trễ vẫn có thể ra 0,9.
# Đo 08/10 (temp/noise-bench/echo_score_probe.py, 0,6/0,7): câu chỉ có tiếng vọng 83-100% nhận ra,
# không vọng 0%; người gọi nói chồng lên tiếng vọng chỉ 8-55% (giọng người gọi làm loãng) — nên
# nhớ theo CUỘC GỌI: một câu bot không bị ngắt lời đã thấy vọng thì các câu sau đều coi là có.
_LEVEL_HOP_S = 0.03
_ECHO_MAX_LAG_S = 1.0
_ECHO_MIN_SCORE = 0.6
_ECHO_MIN_COVERAGE = 0.7
# Frame bot "có tiếng": không nhỏ hơn frame to nhất của câu quá chừng này.
_BOT_ACTIVE_RANGE_DB = 30.0
# Chỉ tính frame mic có tiếng (hơn mức nền của đoạn chừng này): bước nhảy im lặng -> giọng người
# gọi khớp với một chỗ ngắt nào đó của câu bot là đủ đẩy tương quan lên cao.
_ECHO_ACTIVE_DB = 10.0
# Đường bao gần như phẳng không nói gì về tiếng vọng (Pearson không phụ thuộc biên độ).
_ECHO_MIN_SPREAD_DB = 1.0
# Tiếng vọng nhỏ hơn mức này không thành chữ ASR (barge_in_eval 08/10: echo ~6 dB không lượt
# nào có chữ bot, ~36 dB thì 12/12): chữ trùng câu bot khi đó là người gọi nói.
_ECHO_MIN_DB = 24.0
_ECHO_MIN_FRAMES = 8
_ECHO_PROBE_MIN_SPAN_S = 0.6
_ECHO_PROBE_INTERVAL_S = 0.3
_CALLER_LEVELS_KEPT = 1000  # ~30 s frame 30 ms
# `three_state`: "không vọng" chỉ khi đủ chừng này câu bot đọc trọn, không ai chen, mỗi câu
# >= `_QUIET_MIN_BOT_MS`, mà mic có tiếng (>= `_ECHO_MIN_DB`) ở dưới `_QUIET_MAX_ACTIVE` thời gian.
_QUIET_SENTENCES = 2
_QUIET_MIN_BOT_MS = 2000.0
_QUIET_MAX_ACTIVE = 0.05

# Bỏ chữ bot vọng lại khỏi lượt người gọi (`echo_text`):
# - "text": như trước 08/10 — luôn so với cả câu bot (xoá cả lời người gọi nhắc lại câu bot).
# - "acoustic": chỉ khi mic có tiếng vọng (câu này hoặc câu trước của cuộc gọi).
# - "three_state": đường truyền chưa biết / có vọng thì như "text" (giới hạn chữ bot đang phát);
#   chỉ không bỏ khi đã chắc không vọng (`_QUIET_SENTENCES`).
EchoPolicy = Literal["text", "acoustic", "three_state"]


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
        echo_policy: EchoPolicy = "acoustic",
    ) -> None:
        """`validator`: dùng chung TurnValidator với TurnController, ở đây chỉ để chặn thêm.
        `min_snr_db`: None = tắt điều kiện 4."""
        self._echo_policy = echo_policy
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
        # Mốc phát câu bot cho `echo_text`.
        self._bot_started_at = 0.0
        self._bot_audio_at: Optional[float] = None
        self._bot_audio_ms = 0.0
        self._bot_audio_complete = False
        self._bot_stopped_at: Optional[float] = None
        self._bot_finished = False
        self._ms_per_char = _DEFAULT_MS_PER_CHAR
        # VAD báo ứng viên ngắt lời gần nhất của câu bot này (giữ cả sau khi bot dứt lời).
        self._heard_from: Optional[float] = None
        # Đường bao năng lượng (dB) của audio bot đã phát và của mic người gọi (`_echo_score`).
        self._bot_levels: list[float] = []
        self._bot_pcm_tail = b""
        self._caller_levels: deque[tuple[float, float]] = deque(maxlen=_CALLER_LEVELS_KEPT)
        # Đường truyền của cuộc gọi đã cho thấy tiếng vọng (một instance cho một cuộc gọi).
        self._call_has_echo = False
        # `three_state`: số câu bot đọc trọn mà mic im (bằng chứng không vọng).
        self._quiet_sentences = 0
        self._next_echo_probe_at = 0.0

    @property
    def state(self) -> InterruptionState:
        return self._state

    def on_bot_started_speaking(self, bot_text: str = "") -> None:
        """`bot_text`: câu đầy đủ bot sắp đọc; "" tắt kiểm tra tiếng vọng."""
        self._state = InterruptionState.BOT_SPEAKING
        self._candidate_started_at = None
        self._stability = StabilityVerdict.UNKNOWN
        self._bot_text = bot_text
        self._bot_started_at = self._clock()
        self._bot_audio_at = None
        self._bot_audio_ms = 0.0
        self._bot_audio_complete = False
        self._bot_stopped_at = None
        self._bot_finished = False
        self._heard_from = None
        self._bot_levels = []
        self._bot_pcm_tail = b""
        self._next_echo_probe_at = self._bot_started_at + _ECHO_PROBE_MIN_SPAN_S

    def on_bot_audio(self, pcm: bytes, sample_rate: int, *, complete: bool = False) -> None:
        """CallBridge nhận thêm audio TTS (PCM16) của câu đang đọc và phát liền mạch từ chunk
        đầu; `complete`: TTS đã trả hết câu. Không báo thì `echo_text` không bỏ gì."""
        if self._bot_audio_at is None:
            self._bot_audio_at = self._clock()
        self._bot_audio_ms += len(pcm) / 2 / sample_rate * 1000
        self._bot_audio_complete = self._bot_audio_complete or complete
        hop = int(sample_rate * _LEVEL_HOP_S) * 2
        data = self._bot_pcm_tail + pcm
        whole = len(data) - len(data) % hop
        self._bot_levels.extend(_level_db(data[i : i + hop]) for i in range(0, whole, hop))
        self._bot_pcm_tail = data[whole:]

    def on_caller_audio(self, pcm: bytes) -> None:
        """STTPipeline đưa mọi frame mic (PCM16) theo thời gian thực, cho `_echo_score`."""
        now = self._clock()
        self._caller_levels.append((now, _level_db(pcm)))
        if (
            self._echo_policy != "text"
            and self._bot_audio_at is not None
            and self._bot_stopped_at is None
            and not self._call_has_echo
            and now - self._bot_audio_at >= _ECHO_PROBE_MIN_SPAN_S
            and now >= self._next_echo_probe_at
        ):
            self._next_echo_probe_at = now + _ECHO_PROBE_INTERVAL_S
            # Remember echo while the caller is still quiet. A later overlapping voice
            # can drown out this evidence even within the first bot sentence of a call.
            if self._echo_heard(*self._echo_evidence()):
                self._call_has_echo = True

    @property
    def heard_from(self) -> Optional[float]:
        """Lúc VAD báo ứng viên ngắt lời gần nhất của câu bot đang/vừa đọc."""
        return self._heard_from

    @property
    def bot_stopped_at(self) -> Optional[float]:
        return self._bot_stopped_at

    @property
    def echo_path(self) -> str:
        """`three_state`: "echo" | "no_echo" | "unknown"."""
        if self._call_has_echo:
            return "echo"
        return "no_echo" if self._quiet_sentences >= _QUIET_SENTENCES else "unknown"

    def on_bot_stopped_speaking(self) -> None:
        self._bot_finished = self._state != InterruptionState.INTERRUPTED
        self._bot_stopped_at = self._clock()
        if self._bot_finished:
            if self._echo_heard(*self._echo_evidence()):
                self._call_has_echo = True
            elif (
                self._heard_from is None
                and self._bot_audio_ms >= _QUIET_MIN_BOT_MS
                and self._mic_active_fraction() < _QUIET_MAX_ACTIVE
            ):
                self._quiet_sentences += 1
        if self._bot_audio_complete and self._bot_text:
            self._ms_per_char = self._bot_audio_ms / len(self._bot_text)
        self._state = InterruptionState.IDLE
        self._candidate_started_at = None

    def echo_text(self, lookback_s: float, *, heard_from: Optional[float] = None) -> str:
        """Phần câu bot có thể vọng vào audio ASR của ứng viên ngắt lời gần nhất: các chữ phát
        từ `lookback_s` (pre-roll phát lại vào ASR) trước lúc VAD báo ứng viên tới lúc bot dứt lời.

        Chữ bot đã đọc xong trước đó không thể có trong audio này: người gọi nhắc lại chúng
        ("Anh cần em hỗ trợ gì ạ?" -> "Anh cần em hỗ trợ đặt lịch") là lời thật, không được bỏ
        (`strip_echo_prefix` chỉ so chữ nên không tự phân biệt được)."""
        words = self._bot_text.split()
        heard = heard_from if heard_from is not None else self._heard_from
        if not words or heard is None:
            return ""
        if self._echo_policy == "text":
            return self._bot_text
        score, coverage = self._echo_evidence()
        logger.info(
            "interruption: echo_score=%.2f coverage=%.2f echo_path=%s policy=%s",
            score,
            coverage,
            self.echo_path,
            self._echo_policy,
        )
        if self._echo_policy == "three_state":
            if self.echo_path == "no_echo" and not self._echo_heard(score, coverage):
                return ""  # đã chắc đường truyền không vọng: chữ trùng câu bot là người gọi nói
        elif not (self._call_has_echo or self._echo_heard(score, coverage)):
            # Không thấy bản sao trễ của tiếng bot trong mic (AEC đã khử): chữ trùng câu bot là
            # người gọi nhắc lại, không bỏ gì.
            return ""
        chars = len(" ".join(words))
        if self._bot_audio_complete:
            total_ms = self._bot_audio_ms
        else:
            total_ms = max(self._bot_audio_ms, chars * self._ms_per_char)
        start = self._bot_audio_at if self._bot_audio_at is not None else self._bot_started_at
        heard_from = heard - lookback_s - _ON_AIR_MARGIN_S
        if self._bot_finished:
            heard_to = float("inf")  # bot đọc hết câu: mọi chữ sau mốc đều đã phát
        else:
            stopped = self._bot_stopped_at if self._bot_stopped_at is not None else self._clock()
            heard_to = stopped + _ON_AIR_MARGIN_S
        on_air, offset = [], 0
        for word in words:
            begin = start + total_ms * offset / chars / 1000
            offset = min(offset + len(word) + 1, chars)
            end = start + total_ms * offset / chars / 1000
            if end >= heard_from and begin <= heard_to:
                on_air.append(word)
        return " ".join(on_air)

    def _mic_active_fraction(self) -> float:
        """Tỉ lệ frame mic đủ to để ASR chép ra chữ (>= `_ECHO_MIN_DB`) trong lúc bot phát câu."""
        if self._bot_audio_at is None or self._bot_stopped_at is None:
            return 1.0
        mic = [
            db for t, db in self._caller_levels if self._bot_audio_at <= t <= self._bot_stopped_at
        ]
        if not mic:
            return 1.0
        return sum(db >= _ECHO_MIN_DB for db in mic) / len(mic)

    @staticmethod
    def _echo_heard(score: float, coverage: float) -> bool:
        return score >= _ECHO_MIN_SCORE and coverage >= _ECHO_MIN_COVERAGE

    def _echo_evidence(self) -> tuple[float, float]:
        """(tương quan, độ phủ) trên cả phần câu bot đã phát. Tương quan: Pearson lớn nhất qua
        các độ trễ giữa đường bao mic và đường bao bot. Độ phủ: ở độ trễ đó, tỉ lệ frame bot có
        tiếng mà mic cũng có tiếng. Tiếng vọng (bản sao trễ, nhỏ đi của tiếng bot): cả hai gần 1."""
        if not self._bot_levels or self._bot_audio_at is None:
            return 0.0, 0.0
        stopped = self._bot_stopped_at if self._bot_stopped_at is not None else self._clock()
        start, end = self._bot_audio_at, stopped + _ECHO_MAX_LAG_S
        caller = [(t, db) for t, db in self._caller_levels if start <= t <= end]
        if not caller:
            return 0.0, 0.0
        times = np.array([t for t, _ in caller])
        mic = np.array([db for _, db in caller])
        active = mic >= mic.min() + _ECHO_ACTIVE_DB
        times, mic = times[active], mic[active]
        if len(mic) < _ECHO_MIN_FRAMES or mic.std() < _ECHO_MIN_SPREAD_DB:
            return 0.0, 0.0
        if np.median(mic) < _ECHO_MIN_DB:
            return 0.0, 0.0
        played = int((stopped - self._bot_audio_at) / _LEVEL_HOP_S)
        bot = np.array(self._bot_levels[: max(played, 1)])
        bot_active = set(np.flatnonzero(bot >= bot.max() - _BOT_ACTIVE_RANGE_DB).tolist())
        best, best_index = 0.0, None
        for lag in np.arange(0.0, _ECHO_MAX_LAG_S + 1e-9, _LEVEL_HOP_S):
            index = np.floor((times - lag - self._bot_audio_at) / _LEVEL_HOP_S).astype(int)
            inside = (index >= 0) & (index < len(bot))
            reference = np.where(inside, bot[np.clip(index, 0, len(bot) - 1)], 0.0)
            if reference.std() < _ECHO_MIN_SPREAD_DB:
                continue
            score = float(np.corrcoef(mic, reference)[0, 1])
            if score > best:
                best, best_index = score, index[inside]
        if best_index is None or not bot_active:
            return best, 0.0
        return best, len(bot_active.intersection(best_index.tolist())) / len(bot_active)

    async def on_speech_started(self, event: VadEvent) -> None:
        if self._state == InterruptionState.BOT_SPEAKING:
            self._state = InterruptionState.INTERRUPTION_CANDIDATE
            self._candidate_started_at = self._clock()
            self._heard_from = self._candidate_started_at

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
            if decision == ValidationDecision.DROP or (
                decision == ValidationDecision.WAIT and not event.is_final
            ):
                return False
        return True

    def _is_echo_of_bot(self, candidate_text: str) -> bool:
        """ASR thường chỉ nghe được một đoạn của câu bot đang đọc dở, nên so với từng cửa sổ
        từ liên tiếp cùng độ dài trong câu bot.

        Không so ở mức ký tự (`partial_ratio` cũ): partial ngắn của người gọi như "Anh",
        "Anh muốn" luôn khớp một khúc nào đó của câu bot ("...anh chị...") — đo 06/10, cả 15
        partial thật bị coi là echo, 0/12 lần ngắt lời được xác nhận. Partial dưới
        `_ECHO_FUZZY_MIN_WORDS` từ chỉ là echo khi trùng nguyên văn một đoạn câu bot."""
        # TTS templates spell "Alo" as one word; ASR can spell the same greeting "A LÔ".
        # Without normalization a complete echoed sentence is longer than the template
        # and bypasses the echo check before the fuzzy comparison even runs.
        candidate = re.sub(r"\ba lô\b", "alo", spoken_words(candidate_text)).split()
        bot = re.sub(r"\ba lô\b", "alo", spoken_words(self._bot_text)).split()
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


def _level_db(pcm: bytes) -> float:
    """Năng lượng frame PCM16, dB (0 = im lặng số)."""
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    if not samples.size:
        return 0.0
    return 10 * math.log10(float(np.mean(samples * samples)) + 1.0)
