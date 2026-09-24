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
4. Turn phải kéo dài ít nhất `min_speech_ms` (tính từ VAD speech_start đến lúc chốt) —
   lớp phòng thủ thứ 2 chống false-positive từ VAD/ASR (backchannel "ừ", ho, tiếng động
   ngắn có thể vẫn lọt qua VAD dù đã dùng classifier tốt hơn energy). Không áp dụng cho
   final ASR đến SAU khi đã đủ min_speech_ms tính tới thời điểm đó.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import AsyncIterator, Callable, Optional

from speech.asr.evidence import StabilityVerdict
from speech.asr.vad.base import VadEvent
from speech.audio.noise_tracker import NoiseEvidence
from speech.turn.events import UserTurnCompleted
from speech.turn.validator import TurnValidator, ValidationDecision
from speech.types import TranscriptEvent

logger = logging.getLogger(__name__)

# Filler word ASR có thể decode ĐÚNG (không phải hallucination — xem
# inference/asr/providers/zipformer.py) từ audio ngắn hợp lệ, nhưng bản thân không mang
# nội dung hội thoại — core không nên nhận những turn này (orchestrator sẽ hỏi lại/coi
# là câu trả lời không hiểu, gây trải nghiệm tệ hơn là im lặng bỏ qua). Danh sách tối
# thiểu, không cố gắng bắt hết mọi filler tiếng Việt — chỉ những từ đơn thực tế đã gặp
# qua log.
_FILLER_WORDS = frozenset(
    {"à", "ừ", "ờ", "ạ", "ơ", "ừm", "ờm", "à ừ", "dạ", "ừa", "ơ kìa", "hửm", "hử"}
)
_PUNCTUATION_ONLY_RE = re.compile(r"^[\W_]+$", re.UNICODE)


def is_meaningful_text(text: str) -> bool:
    """True nếu `text` đáng để chốt thành turn gửi lên core.

    Lọc 2 loại rác lọt qua được VAD+ASR dù không hallucination: (1) chỉ dấu câu/ký tự
    đặc biệt (ASR đôi khi trả về khi decode audio toàn nhiễu tần số thấp), (2) filler
    word đơn lẻ đúng nghĩa nhưng không mang nội dung ("à", "ờm"...). KHÔNG lọc theo độ
    dài chung chung — "có"/"không"/"ok" là câu trả lời hợp lệ 1 từ, phải giữ lại.
    """
    normalized = text.strip().lower()
    if not normalized:
        return False
    if _PUNCTUATION_ONLY_RE.match(normalized):
        return False
    if normalized in _FILLER_WORDS:
        return False
    return True


@dataclass
class _Candidate:
    """Turn đang hình thành: text/confidence tốt nhất đã biết, chờ điều kiện chốt."""

    text: str = ""
    confidence: Optional[float] = None
    has_final_transcript: bool = False
    vad_ended: bool = False
    finalized: bool = False
    started_at: Optional[float] = None
    # >0 nếu speech_start xảy ra khi vẫn còn trong post-bot echo guard — cộng thêm vào
    # min_speech_s khi kiểm tra thời lượng tối thiểu (xem on_vad_event/_has_min_duration),
    # để dư âm/tiếng vọng ngắn ngay sau khi bot dứt lời cần "nói tiếp" đủ lâu hơn bình
    # thường mới được chấp nhận thành turn thật, thay vì mất hẳn khả năng barge-in sớm.
    guard_extra_s: float = 0.0
    # Cập nhật bởi TurnController.on_evidence_updated() — caller (pipeline.py::_drain_asr())
    # đẩy giá trị mới nhất từ NoiseTracker/TranscriptEvidenceTracker vào đây mỗi khi có
    # event mới, để TurnValidator đọc được khi _try_emit() được gọi. None khi không có
    # validator cấu hình (giữ hành vi cũ, không tính toán thừa).
    noise_evidence: Optional[NoiseEvidence] = None
    stability: StabilityVerdict = StabilityVerdict.UNKNOWN


class TurnController:
    def __init__(
        self,
        *,
        max_wait_after_vad_end_ms: int = 300,
        min_speech_ms: int = 250,
        post_bot_guard_ms: int = 500,
        clock: Optional[Callable[[], float]] = None,
        validator: Optional[TurnValidator] = None,
    ) -> None:
        """`min_speech_ms`: turn ngắn hơn ngưỡng này (tính từ speech_start) bị coi là
        tiếng động/backchannel, không được chốt thành UserTurnCompleted — kể cả khi VAD
        và ASR đều đồng thuận có "speech".

        `post_bot_guard_ms`: candidate bắt đầu (speech_start) trong khoảng này ngay SAU
        khi bot vừa dứt lời bị discard — chống dư âm/tiếng vọng phòng còn sót lại trong
        mic đúng lúc is_bot_speaking chuyển False (xem `on_bot_speaking_changed`).

        `validator` (tuỳ chọn, mặc định `None` — giữ hành vi cũ 100%): lớp quyết định bổ
        sung dựa trên bằng chứng âm thanh/độ ổn định transcript (xem TurnValidator). CHỈ
        được quyền WAIT khi còn khả năng có event mới tới cho candidate hiện tại — tại
        "cơ hội cuối" (final ASR đã tới, hoặc timeout hết hạn, xem `_try_emit`), WAIT tự
        động coi như không có validator (fallback về hành vi cũ) để tránh treo turn vô
        thời hạn khi không còn event nào tới nữa."""
        self._max_wait_after_vad_end_s = max_wait_after_vad_end_ms / 1000
        self._min_speech_s = min_speech_ms / 1000
        self._post_bot_guard_s = post_bot_guard_ms / 1000
        self._clock = clock or time.monotonic
        self._validator = validator
        self._queue: "asyncio.Queue[UserTurnCompleted]" = asyncio.Queue()
        self._candidate = _Candidate()
        self._bot_speaking = False
        self._bot_stopped_at: Optional[float] = None
        self._timeout_task: Optional[asyncio.Task] = None

    def on_bot_speaking_changed(self, speaking: bool, *, preserve_candidate: bool = False) -> None:
        """Interruption Controller gọi khi bot bắt đầu/dừng phát TTS.

        Khi bot VỪA NGỪNG nói: bỏ candidate đã tích luỹ trong lúc bot đang nói, không
        emit nó thành turn. Audio nhận được trong khoảng đó nhiều khả năng là echo/dư âm
        tiếng bot vọng lại mic (đặc biệt qua loa ngoài, echo cancellation của trình duyệt
        không loại hết), không phải ý định thật của user — nếu user thực sự muốn nói,
        họ sẽ tạo `speech_start` MỚI sau khi nhận ra bot đã dứt lời. Barge-in thật đã
        được InterruptionController xử lý riêng (cancel TTS ngay khi đang nói), nên đến
        lúc `on_bot_speaking_changed(False)` chạy, mọi candidate còn sót lại không phải
        là ngắt lời hợp lệ."""
        self._bot_speaking = speaking
        if not speaking:
            self._bot_stopped_at = self._clock()
        if not speaking and not preserve_candidate:
            if self._candidate.started_at is not None and not self._candidate.finalized:
                # Candidate có audio thật (VAD đã speech_start) bị huỷ vì tích luỹ TRONG
                # LÚC bot nói và KHÔNG được InterruptionController xác nhận — nếu đây là
                # audio user nói thật (không phải echo), nó biến mất không có turn nào,
                # không log gì ở nơi khác (không đi qua nhánh Admission — is_bot_speaking
                # vẫn True lúc đó). Log DEBUG only: text có thể chứa PII.
                logger.debug(
                    "turn_controller: discard candidate on bot_speaking->False text=%r "
                    "(not confirmed as barge-in)",
                    self._candidate.text,
                )
            self._reset_candidate()
        elif not speaking:
            # Barge-in đã được xác nhận: giữ candidate VAD đang hình thành. Nếu final
            # đã tới trong lúc bot nói thì có thể chốt ngay; nếu chưa, các frame replay
            # từ pre-roll và phần audio tiếp theo sẽ hoàn thiện candidate này.
            self._try_emit(allow_partial=True)

    @property
    def is_bot_speaking(self) -> bool:
        """Đọc bởi STTPipeline.stream() để chặn audio (echo TTS) đưa vào ASR buffer
        ngay từ nguồn — xem docstring `stream()` (speech/asr/pipeline.py) để biết bug
        thật đã gặp khi không chặn: buffer ZipFormerASR tích luỹ echo câu bot vừa nói,
        hallucinate ra cùng 1 văn bản cố định ở mọi cuộc gọi bất kể user nói gì."""
        return self._bot_speaking

    @property
    def has_active_vad_candidate(self) -> bool:
        """True giữa lúc VAD chính đã báo speech_start và turn chưa chốt/reset — đọc bởi
        STTPipeline.stream() CHỈ để log chẩn đoán (không ảnh hưởng quyết định chốt turn):
        VAD chính và Speech Admission dùng 2 classifier độc lập (xem
        docs/reference/livekit-architecture.md §5.4), nên có thể lệch nhau — VAD chính
        coi là speech trong khi Admission vẫn REJECT (chưa đủ SNR/duration theo classifier
        RIÊNG của nó). Không dùng property này để đổi quyết định Admission."""
        return self._candidate.started_at is not None and not self._candidate.finalized

    async def on_vad_event(self, event: VadEvent) -> None:
        if event.kind == "speech_start":
            self._reset_candidate()
            now = self._clock()
            self._candidate.started_at = now
            if self._bot_stopped_at is not None:
                elapsed_since_bot_stopped = now - self._bot_stopped_at
                if elapsed_since_bot_stopped < self._post_bot_guard_s:
                    # Speech bắt đầu ngay sau khi bot vừa dứt lời — có thể là dư âm/tiếng
                    # vọng phòng, không phải ý định thật của user. Không discard thẳng
                    # (user có thể THẬT SỰ bắt đầu nói ngay lúc này) — thay vào đó đòi hỏi
                    # thêm phần thời lượng còn thiếu của guard window, cộng dồn vào
                    # min_speech_ms bình thường: echo ngắn/thoảng qua sẽ bị min_speech_ms
                    # (đã cộng thêm) chặn lại, còn speech thật kéo dài vẫn được chốt.
                    self._candidate.guard_extra_s = (
                        self._post_bot_guard_s - elapsed_since_bot_stopped
                    )
        elif event.kind == "speech_end":
            self._candidate.vad_ended = True
            # Final ASR có thể đã tới trước speech_end (ASR tự endpoint sớm hơn VAD) —
            # chốt ngay nếu vậy; ngược lại CHỜ final thật, không dùng partial ngay lập tức.
            if self._try_emit(allow_partial=False):
                return
            self._start_timeout()

    async def on_transcript_event(self, event: TranscriptEvent) -> None:
        self._candidate.text = event.text
        self._candidate.confidence = event.confidence
        if event.is_final:
            self._candidate.has_final_transcript = True
            # final đã tới -> không còn event ASR nào khác cho candidate này -> cơ hội
            # cuối, Validator không được WAIT nữa (xem docstring __init__/_try_emit).
            self._try_emit(allow_partial=True, is_last_chance=True)

    def on_evidence_updated(
        self,
        *,
        noise_evidence: Optional[NoiseEvidence] = None,
        stability: Optional[StabilityVerdict] = None,
    ) -> None:
        """Caller (`pipeline.py::_drain_asr()`) gọi song song với `on_transcript_event()`
        khi có `NoiseTracker`/`TranscriptEvidenceTracker` cấu hình — cập nhật bằng chứng
        mới nhất vào candidate hiện tại để `TurnValidator` đọc được lúc `_try_emit()`.
        Tham số `None` (mặc định) không ghi đè — cho phép gọi chỉ với 1 trong 2 giá trị."""
        if noise_evidence is not None:
            self._candidate.noise_evidence = noise_evidence
        if stability is not None:
            self._candidate.stability = stability

    def _try_emit(self, *, allow_partial: bool, is_last_chance: bool = False) -> bool:
        """Chốt turn nếu đã sẵn sàng và bot không đang nói.

        `allow_partial=False`: chỉ chốt khi đã có ASR final thật (dùng khi VAD vừa báo
        speech_end nhưng chưa chắc final đã tới). `allow_partial=True`: chốt bằng text
        hiện có dù chỉ là partial — dùng khi final đã tới, hoặc khi timeout hết hạn.

        `is_last_chance=True`: không còn cơ hội nào khác gọi lại `_try_emit` cho candidate
        hiện tại (final đã tới, hoặc timeout hết hạn) — nếu `self._validator` trả WAIT ở
        đây, tự động coi như không có validator (fallback is_meaningful_text()+duration)
        thay vì treo turn vô thời hạn.

        Trả True nếu đã emit.
        """
        candidate = self._candidate
        if candidate.finalized or self._bot_speaking:
            return False
        if not candidate.has_final_transcript:
            if not allow_partial or not candidate.vad_ended:
                return False
        text = candidate.text.strip()
        if not text:
            return False
        if not is_meaningful_text(text):
            # Rác nội dung (filler word đơn lẻ, chỉ dấu câu...) — không phải vấn đề thời
            # lượng nên chờ thêm không giúp gì; discard hẳn để không kẹt candidate lại
            # chờ speech_start mới ghi đè (on_vad_event đã tự _reset_candidate() ở đó,
            # nhưng reset sớm ở đây tránh 1 final/partial rác trễ ghi đè lại text tốt
            # hơn đã có, nếu candidate còn sống tới lúc đó).
            self._reset_candidate()
            return False
        if not self._has_min_duration(candidate):
            # Chưa đủ min_speech_ms — có thể vẫn đang tiếp tục nói (final/partial mới sẽ
            # gọi lại _try_emit), hoặc VAD/ASR nhầm tiếng động ngắn thành speech. Tự hẹn
            # giờ kiểm tra lại đúng lúc đủ ngưỡng (không phụ thuộc speech_end có tới hay
            # không — final có thể đến trước speech_end, xem on_transcript_event).
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
                # KHÔNG hẹn giờ qua _schedule_min_duration_check (đó là cơ chế chờ ĐỦ
                # DURATION, không liên quan WAIT vì thiếu evidence) — chỉ đơn giản chưa
                # chốt, lần on_transcript_event/on_vad_event kế tiếp sẽ tự gọi lại
                # _try_emit() khi có evidence mới (final tới, hoặc timeout -> is_last_chance).
                return False
            # ACCEPT, hoặc WAIT+is_last_chance (fallback về hành vi cũ) -> đi tiếp.
        candidate.finalized = True
        self._cancel_timeout()
        self._queue.put_nowait(UserTurnCompleted(text=text, confidence=candidate.confidence))
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

    async def _timeout_flush(self, candidate: _Candidate, delay_s: float) -> None:
        await asyncio.sleep(delay_s)
        if candidate is not self._candidate or candidate.finalized:
            return
        if not self._has_min_duration(candidate):
            if not candidate.vad_ended:
                # Chưa hết hạn chờ speech_end thật (chỉ vừa xong phần min_speech_ms) —
                # để nguyên, on_vad_event(speech_end) sẽ tự lo tiếp khi nó tới.
                return
            # Hết hạn chờ mà turn vẫn ngắn hơn ngưỡng -> tiếng động/backchannel, discard
            # hẳn thay vì emit turn rác (mục người dùng báo: "dạ dạ" liên tục do nhiễu).
            # Log DEBUG: nếu đây là audio user nói thật (không phải backchannel), câu đó
            # biến mất hoàn toàn không có turn nào — guard_extra_s (post_bot_guard) có thể
            # là nguyên nhân nếu candidate bắt đầu ngay sau khi bot vừa dứt lời.
            logger.debug(
                "turn_controller: discard candidate on timeout text=%r duration_required_s=%.2f "
                "guard_extra_s=%.2f",
                candidate.text,
                self._min_speech_s + candidate.guard_extra_s,
                candidate.guard_extra_s,
            )
            self._reset_candidate()
            return
        # Timeout hết hạn -> không còn cơ hội nào khác chờ thêm event mới cho candidate
        # này -> cơ hội cuối, Validator không được WAIT nữa (xem docstring __init__).
        self._try_emit(allow_partial=True, is_last_chance=True)

    def _cancel_timeout(self) -> None:
        if self._timeout_task is not None and not self._timeout_task.done():
            self._timeout_task.cancel()
        self._timeout_task = None

    def _reset_candidate(self) -> None:
        self._cancel_timeout()
        self._candidate = _Candidate()

    def has_pending_turn(self) -> bool:
        """True nếu còn UserTurnCompleted chưa được tiêu thụ — dùng để caller
        (STTPipeline.stream) biết khi nào an toàn dừng lắng nghe sau khi audio kết thúc."""
        return not self._queue.empty()

    async def get_turn(self) -> UserTurnCompleted:
        """Chờ turn kế tiếp. An toàn gọi lặp lại — không như một generator dùng chung,
        mỗi lời gọi độc lập nên có thể bọc trong `asyncio.ensure_future` rồi `cancel()`
        mà không làm hỏng trạng thái nội bộ của các lần gọi sau."""
        return await self._queue.get()

    async def turns(self) -> AsyncIterator[UserTurnCompleted]:
        while True:
            yield await self.get_turn()
