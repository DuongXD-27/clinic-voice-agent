"""Policy: kiểm soát luồng nghiệp vụ, điều kiện thực thi, xử lý ngoại lệ (thiết kế IE v1.1 §6).

Nhận thẳng `ExtractionResult`; `transfer_reason` / `unreachable_reason` do Policy chọn, không do IE.
"""

from dataclasses import dataclass
from typing import Literal, Optional

from callbot.engine.extraction.schema import ClinicalLevel, ExtractionResult, Intent, LineSignal
from callbot.engine.session.context import CallContext
from callbot.engine.settings import EngineSettings
from callbot.engine.types import TransferReason, UnreachableReason

DecisionKind = Literal["CONTINUE", "REPROMPT", "TRANSFER", "UNREACHABLE"]

# Dialogue gắn cho mỗi phản hồi — Policy dùng để đếm §1.1.5 (thiết kế §6.1)
# UNDERSTOOD     hiểu được: reset bộ đếm không hiểu
# NOT_UNDERSTOOD không dùng được cho câu đang hỏi: tính vào bộ đếm
# UNCLEAR        agreement mơ hồ: lần đầu hỏi lại, từ lần thứ hai liên tiếp mới tính
# NEUTRAL        xin nhắc lại, slot khớp nhiều khung: không đổi bộ đếm
Understanding = Literal["UNDERSTOOD", "NOT_UNDERSTOOD", "UNCLEAR", "NEUTRAL"]


@dataclass(frozen=True)
class PolicyDecision:
    kind: DecisionKind
    transfer_reason: Optional[TransferReason] = None
    unreachable_reason: Optional[UnreachableReason] = None

    @classmethod
    def proceed(cls) -> "PolicyDecision":
        return cls("CONTINUE")

    @classmethod
    def transfer(cls, reason: TransferReason) -> "PolicyDecision":
        return cls("TRANSFER", reason)

    @classmethod
    def unreachable(cls, reason: UnreachableReason) -> "PolicyDecision":
        return cls("UNREACHABLE", unreachable_reason=reason)


_TRANSFER_CLINICAL = frozenset({ClinicalLevel.EMERGENCY, ClinicalLevel.ADVICE_REQUEST})

_UNREACHABLE_REASON: dict[Optional[LineSignal], UnreachableReason] = {
    LineSignal.VOICEMAIL: "VOICEMAIL",
    LineSignal.LINE_BUSY: "LINE_BUSY",
    LineSignal.NO_ANSWER: "NO_ANSWER",
}

# §1.2, thiết kế §6.3: các intent luôn chuyển máy, bất kể đang ở bước nào
_ALWAYS_TRANSFER: dict[Intent, TransferReason] = {
    Intent.REQUEST_HUMAN: "PATIENT_REQUEST",
    # Người nhà nghe máy: không tiết lộ, không xác minh thay (câu hỏi mở §10.8)
    Intent.NOT_PATIENT: "IDENTITY_FAILED",
    Intent.OUT_OF_SCOPE: "OUT_OF_SCOPE",
}


class PolicyEngine:
    def __init__(self, settings: EngineSettings) -> None:
        self._settings = settings

    def check_preconditions(self, ctx: CallContext) -> PolicyDecision:
        call = ctx.call
        if call.direction == "outbound" and not call.appointment_id:
            return PolicyDecision.transfer("SYSTEM_ERROR")
        if call.direction == "inbound" and call.appointment_id:
            # §1.1.8: inbound không có appointment_id — dữ liệu harness bất thường
            return PolicyDecision.transfer("SYSTEM_ERROR")
        if ctx.turn > call.max_turns:
            return PolicyDecision.transfer("NOT_UNDERSTOOD")
        return PolicyDecision.proceed()

    def check_silence(self, ctx: CallContext, extraction: ExtractionResult) -> PolicyDecision:
        """§1.1.7 rev 1.1: im lặng có bộ đếm riêng, không đụng bộ đếm không hiểu (§6.4)."""
        if not extraction.silent:
            ctx.silent_turns = 0
            return PolicyDecision.proceed()
        ctx.silent_turns += 1
        if ctx.silent_turns < self._settings.max_silent_turns:
            return PolicyDecision("REPROMPT")
        if ctx.call.direction == "outbound":
            return PolicyDecision.unreachable("SILENCE")
        # Inbound không bao giờ UNREACHABLE: chuyển máy, không tạo lịch (§6.3)
        return PolicyDecision.transfer("NOT_UNDERSTOOD")

    def check_signals(self, ctx: CallContext, extraction: ExtractionResult) -> PolicyDecision:
        """Tín hiệu đường dây, lâm sàng, xin gặp người thật, không phải bệnh nhân, ngoài phạm vi."""
        line = extraction.line_signal
        if ctx.call.direction == "outbound" and line.found and line.value is not LineSignal.NONE:
            # LineSignal trùng tên unreachable_reason (Phụ lục A rev 1.1)
            return PolicyDecision.unreachable(_UNREACHABLE_REASON[line.value])
        # SF-04: lâm sàng xét trước mọi intent; MENTION không chuyển máy (thiết kế §5.5)
        if extraction.clinical.value in _TRANSFER_CLINICAL:
            return PolicyDecision.transfer("CLINICAL_QUESTION")
        intent = extraction.intent.value
        if intent in _ALWAYS_TRANSFER:
            return PolicyDecision.transfer(_ALWAYS_TRANSFER[intent])
        return PolicyDecision.proceed()

    def register_understanding(
        self, ctx: CallContext, understanding: Understanding
    ) -> PolicyDecision:
        """§1.1.5: 2 lần liên tiếp không hiểu -> chuyển máy NOT_UNDERSTOOD (thiết kế §6.1)."""
        if understanding == "NEUTRAL":
            return PolicyDecision.proceed()
        if understanding == "UNDERSTOOD":
            ctx.failed_understandings = 0
            ctx.unclear_streak = 0
            return PolicyDecision.proceed()
        if understanding == "UNCLEAR":
            ctx.unclear_streak += 1
            if ctx.unclear_streak < 2:
                return PolicyDecision.proceed()
        else:
            ctx.unclear_streak = 0
        ctx.failed_understandings += 1
        if ctx.failed_understandings >= self._settings.max_failed_understandings:
            return PolicyDecision.transfer("NOT_UNDERSTOOD")
        return PolicyDecision("REPROMPT")
