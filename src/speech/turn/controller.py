"""Turn Controller — quyết định "user đã nói xong lượt chưa?".

Không chỉ dựa vào `silence > ngưỡng`: kết hợp VAD speech_end + ASR final/partial. VAD và
ASR chạy song song và đẩy event vào đây qua 2 phương thức độc lập —
`on_vad_event`/`on_transcript_event` — controller không tự đọc audio, không biết VAD/ASR
cụ thể nào đang chạy phía trên nó.

Quy tắc chốt turn (UserTurnCompleted):
1. ASR final luôn chốt turn ngay khi nhận được (ASR endpoint riêng của nó).
2. VAD speech_end mà chưa có final tương ứng: chờ tối đa `max_wait_after_vad_end_ms`
   rồi chốt bằng partial cuối cùng nếu vẫn chưa có final — tránh treo turn vô thời hạn.
3. Trong lúc bot đang nói (`on_bot_speaking_changed(True)`), input vẫn được xử lý (VAD/ASR
   không bị tạm dừng ở tầng trên) nhưng KHÔNG chốt turn — tránh lẫn audio user với audio
   bot đang phát; turn ứng viên được giữ lại và chốt ngay khi bot ngừng nói.
4. Turn phải kéo dài ít nhất `min_speech_ms` (tính từ VAD speech_start) — chặn "ừ", ho,
   tiếng động ngắn lọt qua VAD. Bắt đầu sát lúc bot vừa dứt lời thì phải dài thêm phần còn
   thiếu của `post_bot_guard_ms` (chống tiếng vọng).
5. Text phải có nghĩa (`is_meaningful_text`; `drop_filler_words=False` thì chỉ cần có chữ —
   engine tự hiểu "ừ/ờ/dạ/à" — trừ từ đệm nghe lúc bot đang nói) và TurnValidator (nếu có)
   không DROP.
6. Một lượt gồm một hay nhiều đoạn ASR: `speech_start` khi lượt đang dở (đã có chữ, hoặc VAD
   hết đoạn mà ASR còn chưa trả final) mở đoạn mới trong cùng lượt, không bỏ đoạn trước.
   Bug thật 06/10 (Gemini): người gọi ngừng giữa "...Nguyễn Văn A" và "sinh ngày...", đoạn
   mới bắt đầu trước khi final có tên tới -> final đó bị bỏ, mất tên.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from speech.asr.evidence import StabilityVerdict
from speech.asr.vad.base import VadEvent
from speech.audio.noise_tracker import NoiseEvidence
from speech.turn.events import UserTurnCompleted
from speech.turn.validator import TurnValidator, ValidationDecision
from speech.types import TranscriptEvent

logger = logging.getLogger(__name__)

# Từ đệm không mang nội dung — gửi lên core thì bot hỏi lại, tệ hơn bỏ qua. Chỉ gồm các từ
# đã gặp trong log.
#
# "ừ"/"ờ"/"dạ" vẫn bị bỏ dù engine dùng được ("ừ/ờ" = đồng ý, "dạ" = hỏi lại): đo 06/10
# (eval/noise-bench, docs/evidence/stt-turn-segments-backchannel-fallback-2026-10-06.md) cho
# chúng qua theo SNR đoạn nói thì ở mọi ngưỡng đã thử (6/10/15 dB) nhiễu văn phòng thuần vẫn
# thành lượt "Ừ" — đồng ý giả; confidence ZipFormer của "Ừ" giả và thật cũng chồng lấn.
_FILLER_WORDS = frozenset(
    {"à", "ừ", "ờ", "ạ", "ơ", "ừm", "ờm", "à ừ", "dạ", "ừa", "ơ kìa", "hửm", "hử"}
)
_PUNCTUATION_ONLY_RE = re.compile(r"^[\W_]+$", re.UNICODE)
# Gemini trả "Ừ." còn ZipFormer trả "Ừ": bỏ dấu câu trước khi so với các tập từ ở trên.
_PUNCTUATION_RE = re.compile(r"[^\w\s]+", re.UNICODE)
_ASR_POLL_S = 0.05
# `strip_echo_prefix`: khối từ trùng câu bot bắt đầu trong chừng này từ đầu, hai khối cách nhau
# không quá chừng này từ (ASR chép sai tên riêng "VINMEC" -> "VIN BÁCH"); cần đủ số từ trùng và
# chiếm phần lớn đoạn bị bỏ.
_ECHO_PREFIX_MAX_GAP = 2
_ECHO_PREFIX_MIN_WORDS = 3
_ECHO_PREFIX_MIN_COVERAGE = 0.6


def spoken_words(text: str) -> str:
    """Chữ thường, bỏ dấu câu, một khoảng trắng giữa các từ."""
    return " ".join(_PUNCTUATION_RE.sub(" ", text.lower()).split())


def strip_echo_prefix(text: str, bot_text: str) -> str:
    """Bỏ phần đầu `text` là câu bot vọng lại, giữ nguyên chữ gốc của phần còn lại.

    Người gọi chen vào khi tiếng bot còn vọng trong mic: ASR chép câu bot trước rồi tới lời
    người gọi ("ANH CHỊ CHẮC CHẮN MUỐN HỦY TÔI LÀ NGUYỄN VĂN A"). So khớp theo TỪ (difflib),
    không theo ký tự: so mờ ký tự trên cả đoạn đầu ăn luôn lời người gọi ("TÔI TÊN LÀ" mất)."""
    import difflib

    tokens = text.split()
    words = [spoken_words(token) for token in tokens]
    bot = spoken_words(bot_text).split()
    if not bot:
        return text
    end = matched = 0
    blocks = difflib.SequenceMatcher(None, words, bot, autojunk=False).get_matching_blocks()
    for block in blocks:
        if block.size == 0 or block.a - end > _ECHO_PREFIX_MAX_GAP:
            break
        end = block.a + block.size
        matched += block.size
    if matched >= _ECHO_PREFIX_MIN_WORDS and matched >= _ECHO_PREFIX_MIN_COVERAGE * end:
        return " ".join(tokens[end:])
    return text


def is_meaningful_text(text: str) -> bool:
    """False cho text rỗng, chỉ có dấu câu, hoặc chỉ là từ đệm (kể cả có dấu câu như "Ừ." của
    Gemini). Không lọc theo độ dài: "có"/"không" là câu trả lời hợp lệ."""
    normalized = text.strip().lower()
    if not normalized:
        return False
    if _PUNCTUATION_ONLY_RE.match(normalized):
        return False
    return spoken_words(normalized) not in _FILLER_WORDS


@dataclass
class _Segment:
    """Một đoạn ASR trong lượt. `key`: segment_id của ASR remote (Gemini, final có thể tới sau
    khi đoạn sau đã bắt đầu); None với ASR cục bộ (ZipFormer, event tới đúng thứ tự)."""

    key: Optional[int]
    text: str = ""
    final: bool = False


@dataclass
class _Candidate:
    """Turn đang hình thành: các đoạn ASR đã nghe, chờ điều kiện chốt."""

    segments: list[_Segment] = field(default_factory=list)
    confidence: Optional[float] = None
    vad_ended: bool = False
    # VAD đang trong một đoạn nói của lượt này.
    vad_speaking: bool = False
    # Lượt có từ hai đoạn VAD trở lên (quy tắc 6).
    continued: bool = False
    finalized: bool = False
    started_at: Optional[float] = None
    vad_ended_at: Optional[float] = None
    first_partial_at: Optional[float] = None
    final_at: Optional[float] = None
    partial_count: int = 0
    # Thời lượng phải có thêm khi câu bắt đầu sát lúc bot dứt lời (post_bot_guard).
    guard_extra_s: float = 0.0
    # Câu bot có thể vọng lại ở đầu chữ của lượt này (expect_echo).
    echo_text: str = ""
    # Đã đủ điều kiện chốt, đang chờ hết cửa sổ gộp (merge_window_ms).
    merge_pending: bool = False
    # Bằng chứng mới nhất cho TurnValidator (on_evidence_updated).
    noise_evidence: Optional[NoiseEvidence] = None
    stability: StabilityVerdict = StabilityVerdict.UNKNOWN

    @property
    def text(self) -> str:
        return " ".join(seg.text.strip() for seg in self.segments if seg.text.strip())

    @property
    def has_final_transcript(self) -> bool:
        """Mọi đoạn đã nghe (hoặc đã mở ở ASR remote, xem `expect_final`) đều có final."""
        return bool(self.segments) and all(seg.final for seg in self.segments)

    def segment_for(self, key: Optional[int]) -> _Segment:
        if key is not None:
            for seg in self.segments:
                if seg.key == key:
                    return seg
            self.segments.append(_Segment(key))
            self.segments.sort(key=lambda seg: seg.key)
            return next(seg for seg in self.segments if seg.key == key)
        # ASR cục bộ: final đóng đoạn hiện tại, event sau đó thuộc đoạn ASR kế tiếp.
        if not self.segments or self.segments[-1].final:
            self.segments.append(_Segment(None))
        return self.segments[-1]


class TurnController:
    def __init__(
        self,
        *,
        max_wait_after_vad_end_ms: int = 300,
        min_speech_ms: int = 250,
        post_bot_guard_ms: int = 500,
        clock: Optional[Callable[[], float]] = None,
        sleep: Optional[Callable[[float], Awaitable[None]]] = None,
        validator: Optional[TurnValidator] = None,
        max_wait_for_asr_ms: int = 3_000,
        merge_window_ms: int = 0,
        drop_filler_words: bool = True,
    ) -> None:
        """`validator`: chỉ được WAIT khi còn event mới có thể tới; ở "cơ hội cuối" (đã có
        final, hoặc hết timeout) WAIT coi như ACCEPT để lượt không treo mãi.

        `clock`/`sleep` đi thành cặp: bộ đo offline chạy cả đồng hồ lẫn hẹn giờ theo thời gian ảo.

        `max_wait_for_asr_ms`: VAD đã hết câu nhưng ASR (decode chậm) còn tồn audio của câu —
        chờ tối đa chừng này rồi mới chốt bằng partial.

        `merge_window_ms`: lượt đã đủ điều kiện chốt vẫn chờ thêm chừng này; người gọi nói tiếp
        trong lúc đó ("14 tháng 3" … "năm 1978") thì nối vào cùng lượt. 0 = chốt ngay.
        `drop_filler_words`: bỏ lượt chỉ có từ đệm (`_FILLER_WORDS`)."""
        self._max_wait_after_vad_end_s = max_wait_after_vad_end_ms / 1000
        self._min_speech_s = min_speech_ms / 1000
        self._post_bot_guard_s = post_bot_guard_ms / 1000
        self._clock = clock or time.monotonic
        self._sleep = sleep or asyncio.sleep
        self._validator = validator
        self._max_wait_for_asr_s = max_wait_for_asr_ms / 1000
        self._merge_window_s = merge_window_ms / 1000
        self._drop_filler_words = drop_filler_words
        self._asr_pending: Optional[Callable[[], bool]] = None
        self._asr_final_required = False
        self._queue: "asyncio.Queue[UserTurnCompleted]" = asyncio.Queue()
        self._candidate = _Candidate()
        self._bot_speaking = False
        self._bot_stopped_at: Optional[float] = None
        self._last_vad_activity_at: Optional[float] = None
        self._timeout_task: Optional[asyncio.Task] = None
        # Câu bot vọng lại ở đầu final kế tiếp, kể cả khi lượt dở đã bị bỏ (expect_echo).
        self._echo_hint = ""

    def on_bot_speaking_changed(self, speaking: bool, *, preserve_candidate: bool = False) -> None:
        """CallBridge gọi khi bot bắt đầu/dừng phát TTS.

        Bot vừa dứt lời: bỏ câu dở nghe được trong lúc bot nói (nhiều khả năng là tiếng bot
        vọng lại) — trừ khi đó là lần ngắt lời đã xác nhận (`preserve_candidate=True`)."""
        self._bot_speaking = speaking
        if speaking:
            self._echo_hint = ""
        else:
            self._bot_stopped_at = self._clock()
        if not speaking and not preserve_candidate:
            if self._candidate.started_at is not None and not self._candidate.finalized:
                # DEBUG: text có thể chứa PII.
                logger.debug(
                    "turn_controller: discard candidate on bot_speaking->False text=%r "
                    "(not confirmed as barge-in)",
                    self._candidate.text,
                )
            self._reset_candidate()
        elif not speaking:
            # Ngắt lời đã xác nhận: chốt ngay nếu final đã tới, nếu chưa thì chờ phần còn lại.
            self._try_emit(allow_partial=True)

    @property
    def is_bot_speaking(self) -> bool:
        """STTPipeline đọc để không đưa tiếng bot vọng lại vào ASR."""
        return self._bot_speaking

    def set_asr_pending_probe(self, probe: Optional[Callable[[], bool]]) -> None:
        """STTPipeline.stream() gắn hàm cho biết ASR còn audio chưa xử lý (None = không biết)."""
        self._asr_pending = probe

    def set_asr_final_required(self, required: bool) -> None:
        """Cloud STT phải có final; timeout không được đưa partial thiếu phủ định tới engine."""
        self._asr_final_required = required

    def silence_elapsed_s(self) -> Optional[float]:
        """Số giây người dùng im lặng, tính từ lúc bot dứt lời hoặc lần cuối VAD còn thấy tiếng
        nói (mốc muộn hơn). None khi bot đang nói, khi đang có câu dở (đã speech_start, chưa
        chốt/huỷ) hoặc chưa có mốc nào — CallBridge dùng để gửi lượt im lặng cho core."""
        if self._bot_speaking:
            return None
        if self._candidate.started_at is not None and not self._candidate.finalized:
            return None
        marks = [m for m in (self._bot_stopped_at, self._last_vad_activity_at) if m is not None]
        if not marks:
            return None
        return self._clock() - max(marks)

    def continues_turn(self) -> bool:
        """`speech_start` lúc này mở đoạn mới trong lượt đang dở thay vì bắt đầu lượt mới:
        lượt chưa chốt và đã có chữ, hoặc còn đoạn ASR remote chưa trả final.
        STTPipeline hỏi trước khi báo cho ASR remote để giữ lại final của đoạn trước."""
        candidate = self._candidate
        if candidate.started_at is None or candidate.finalized or self._bot_speaking:
            return False
        return bool(candidate.text.strip()) or not candidate.has_final_transcript

    def expect_final(self, segment_id: int) -> None:
        """ASR remote vừa mở đoạn `segment_id` cho `speech_start` vừa báo: lượt chỉ chốt khi
        đoạn này đã có final (kể cả final rỗng), dù final tới sau khi VAD đã hết đoạn."""
        self._candidate.segment_for(segment_id)

    def expect_echo(self, bot_text: str) -> None:
        """ASR đã nghe audio lúc bot đọc `bot_text` (ứng viên ngắt lời): chữ của lượt đang dở và
        của final kế tiếp — tới sau cả khi bot dứt lời đã bỏ lượt dở — có thể bắt đầu bằng câu
        bot vọng lại. Lúc chốt, bỏ phần đó (`strip_echo_prefix`)."""
        self._candidate.echo_text = bot_text
        self._echo_hint = bot_text

    async def on_vad_event(self, event: VadEvent) -> None:
        self._last_vad_activity_at = self._clock()
        if event.kind == "speech_start" and self.continues_turn():
            self._cancel_timeout()
            candidate = self._candidate
            candidate.vad_speaking = True
            candidate.vad_ended = False
            candidate.continued = True
            candidate.merge_pending = False
        elif event.kind == "speech_start":
            self._reset_candidate()
            self._candidate.vad_speaking = True
            now = self._clock()
            self._candidate.started_at = now
            if self._bot_stopped_at is not None:
                elapsed_since_bot_stopped = now - self._bot_stopped_at
                if elapsed_since_bot_stopped < self._post_bot_guard_s:
                    # Có thể là tiếng vọng, nhưng cũng có thể người gọi nói ngay: không bỏ,
                    # chỉ đòi dài thêm — tiếng vọng ngắn sẽ không đủ.
                    self._candidate.guard_extra_s = (
                        self._post_bot_guard_s - elapsed_since_bot_stopped
                    )
        elif event.kind == "speech_end":
            self._candidate.vad_speaking = False
            self._candidate.vad_ended = True
            self._candidate.vad_ended_at = self._clock()
            # Final có thể đã tới trước speech_end; nếu chưa thì chờ final, chưa dùng partial.
            if self._try_emit(allow_partial=False):
                return
            if self._candidate.merge_pending:
                return  # đã đủ điều kiện, đang chờ hết cửa sổ gộp
            self._start_timeout()

    async def on_transcript_event(self, event: TranscriptEvent) -> None:
        if self._echo_hint:
            self._candidate.echo_text = self._echo_hint
            if event.is_final:
                self._echo_hint = ""
        segment = self._candidate.segment_for(event.segment_id)
        now = self._clock()
        if event.is_final:
            segment.text = event.text
            segment.final = True
            self._candidate.confidence = event.confidence
            self._candidate.final_at = now
            self._try_emit(allow_partial=True, is_last_chance=True)
        else:
            if segment.final:
                return  # partial tới muộn của đoạn đã có final
            segment.text = event.text
            self._candidate.confidence = event.confidence
            self._candidate.partial_count += 1
            if self._candidate.first_partial_at is None:
                self._candidate.first_partial_at = now

    def on_evidence_updated(
        self,
        *,
        noise_evidence: Optional[NoiseEvidence] = None,
        stability: Optional[StabilityVerdict] = None,
    ) -> None:
        """Pipeline gọi mỗi khi có transcript mới; None = giữ giá trị cũ."""
        if noise_evidence is not None:
            self._candidate.noise_evidence = noise_evidence
        if stability is not None:
            self._candidate.stability = stability

    def _try_emit(
        self, *, allow_partial: bool, is_last_chance: bool = False, merge_due: bool = False
    ) -> bool:
        """Chốt lượt nếu đủ điều kiện và bot không đang nói. Trả True nếu đã chốt.

        `allow_partial`: cho chốt bằng partial khi VAD đã hết câu (final chưa tới).
        `is_last_chance`: không còn event nào tới cho câu này (đã có final, hoặc hết
        timeout) — validator WAIT khi đó coi như ACCEPT.
        `merge_due`: cửa sổ gộp đã hết, chốt luôn.
        """
        candidate = self._candidate
        if self._asr_final_required and not candidate.has_final_transcript:
            return False
        if candidate.finalized or self._bot_speaking:
            return False
        if candidate.continued and candidate.vad_speaking:
            return False  # đoạn sau của lượt còn đang nói
        if not candidate.has_final_transcript:
            if not allow_partial or not candidate.vad_ended:
                return False
        text = candidate.text.strip()
        if candidate.echo_text:
            text = strip_echo_prefix(text, candidate.echo_text)
        if not text:
            return False
        # Từ đệm nghe lúc bot đang nói (echo_text) là tiếng đệm "tôi đang nghe", không phải trả lời.
        keep_filler = not self._drop_filler_words and not candidate.echo_text
        if not is_meaningful_text(text) and not (keep_filler and spoken_words(text)):
            # Chờ thêm không giúp gì — bỏ câu.
            self._reset_candidate()
            return False
        if not self._has_min_duration(candidate):
            # Có thể còn đang nói: hẹn kiểm tra lại đúng lúc đủ ngưỡng.
            self._schedule_min_duration_check(candidate)
            return False
        if self._validator is not None:
            decision = self._validator.evaluate(
                text,
                noise_evidence=candidate.noise_evidence,
                stability=candidate.stability,
            )
            if decision == ValidationDecision.DROP:
                self._reset_candidate()
                return False
            if decision == ValidationDecision.WAIT and not is_last_chance:
                return False  # final hoặc timeout sau đó sẽ gọi lại
        if self._merge_window_s > 0 and not merge_due:
            self._schedule_merge_commit(candidate)
            return False
        candidate.finalized = True
        self._cancel_timeout()
        started = candidate.started_at

        def elapsed(at: Optional[float]) -> Optional[float]:
            return (
                max(0.0, (at - started) * 1000) if at is not None and started is not None else None
            )

        self._queue.put_nowait(
            UserTurnCompleted(
                text=text,
                confidence=candidate.confidence,
                audio_duration_ms=elapsed(candidate.vad_ended_at),
                first_partial_ms=elapsed(candidate.first_partial_at),
                final_ms=elapsed(candidate.final_at),
                partial_count=candidate.partial_count,
                vad_end_reason="vad_end" if candidate.vad_ended else "asr_final",
            )
        )
        return True

    def _has_min_duration(self, candidate: _Candidate) -> bool:
        if candidate.started_at is None:
            return True  # không có mốc bắt đầu (vd. final tới mà chưa từng có speech_start) — không chặn
        required = self._min_speech_s + candidate.guard_extra_s
        return self._clock() - candidate.started_at >= required

    def _start_timeout(self) -> None:
        self._cancel_timeout()
        self._timeout_task = asyncio.ensure_future(
            self._timeout_flush(self._candidate, self._max_wait_after_vad_end_s)
        )

    def _schedule_min_duration_check(self, candidate: _Candidate) -> None:
        """Final đến trước khi đủ min_speech_ms (và trước cả speech_end) — hẹn kiểm tra
        lại đúng lúc đủ ngưỡng thay vì phụ thuộc speech_end có bao giờ tới hay không."""
        if self._timeout_task is not None and not self._timeout_task.done():
            return  # đã có timeout đang chờ (vd. từ speech_end) — không cần hẹn thêm
        started_at = candidate.started_at if candidate.started_at is not None else self._clock()
        required = self._min_speech_s + candidate.guard_extra_s
        remaining = max(0.0, required - (self._clock() - started_at))
        self._timeout_task = asyncio.ensure_future(self._timeout_flush(candidate, remaining))

    def _schedule_merge_commit(self, candidate: _Candidate) -> None:
        task = self._timeout_task
        if candidate.merge_pending and task is not None and not task.done():
            return
        candidate.merge_pending = True
        self._cancel_timeout()
        self._timeout_task = asyncio.ensure_future(self._merge_commit(candidate))

    async def _merge_commit(self, candidate: _Candidate) -> None:
        """Hết cửa sổ gộp mà người gọi không nói tiếp (speech_start huỷ task này)."""
        await self._sleep(self._merge_window_s)
        if candidate is not self._candidate or candidate.finalized or not candidate.merge_pending:
            return
        self._try_emit(allow_partial=True, is_last_chance=True, merge_due=True)

    async def _timeout_flush(self, candidate: _Candidate, delay_s: float) -> None:
        await self._sleep(delay_s)
        if candidate is not self._candidate or candidate.finalized:
            return
        await self._wait_for_asr_backlog(candidate)
        if candidate is not self._candidate or candidate.finalized:
            return
        if not self._has_min_duration(candidate):
            if not candidate.vad_ended:
                return  # speech_end chưa tới, on_vad_event sẽ xử lý tiếp
            # Hết câu mà vẫn quá ngắn: tiếng động/backchannel ("dạ dạ" do nhiễu) — bỏ.
            logger.debug(
                "turn_controller: discard candidate on timeout text=%r duration_required_s=%.2f "
                "guard_extra_s=%.2f",
                candidate.text,
                self._min_speech_s + candidate.guard_extra_s,
                candidate.guard_extra_s,
            )
            self._reset_candidate()
            return
        self._try_emit(allow_partial=True, is_last_chance=True)
        if (
            candidate is self._candidate
            and candidate.vad_ended
            and not candidate.text.strip()
            and not self._bot_speaking
        ):
            logger.debug("turn_controller: discard empty candidate after VAD timeout")
            self._reset_candidate()

    async def _wait_for_asr_backlog(self, candidate: _Candidate) -> None:
        """VAD đã hết câu nhưng ASR còn tồn audio (decode chậm): final của câu chưa thể tới.
        Chờ ASR xử lý hết (có trần) thay vì chốt ngay bằng partial cũ thiếu chữ."""
        if self._asr_pending is None or not candidate.vad_ended or candidate.has_final_transcript:
            return
        waited = 0.0
        while waited < self._max_wait_for_asr_s and self._asr_pending():
            await self._sleep(_ASR_POLL_S)
            waited += _ASR_POLL_S
            if candidate is not self._candidate or candidate.finalized:
                return
        if waited:
            logger.debug("turn_controller: chờ ASR tồn %.2f s trước khi chốt câu", waited)

    def _cancel_timeout(self) -> None:
        if self._timeout_task is not None and not self._timeout_task.done():
            self._timeout_task.cancel()
        self._timeout_task = None

    async def aclose(self) -> None:
        """Stop a remote ASR turn timer before its pipeline/session is torn down."""
        task = self._timeout_task
        self._cancel_timeout()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        self._candidate = _Candidate()

    def _reset_candidate(self) -> None:
        self._cancel_timeout()
        self._candidate = _Candidate()

    def has_pending_turn(self) -> bool:
        """True nếu còn UserTurnCompleted chưa được tiêu thụ — dùng để caller
        (STTPipeline.stream) biết khi nào an toàn dừng lắng nghe sau khi audio kết thúc.
        Lượt đang chờ hết cửa sổ gộp cũng tính: audio hết thì không ai nói tiếp, lượt sẽ chốt."""
        task = self._timeout_task
        merging = self._candidate.merge_pending and task is not None and not task.done()
        return merging or not self._queue.empty()

    async def get_turn(self) -> UserTurnCompleted:
        """Chờ turn kế tiếp. An toàn gọi lặp lại — không như một generator dùng chung,
        mỗi lời gọi độc lập nên có thể bọc trong `asyncio.ensure_future` rồi `cancel()`
        mà không làm hỏng trạng thái nội bộ của các lần gọi sau."""
        return await self._queue.get()
