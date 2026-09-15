"""Policy: kiểm soát luồng nghiệp vụ, điều kiện thực thi, xử lý ngoại lệ."""

from dataclasses import dataclass
from typing import Literal, Optional

from callbot.engine.nlu.schema import Intent, NLUResult
from callbot.engine.session.context import CallContext
from callbot.engine.settings import EngineSettings
from callbot.engine.types import CallerInput, TransferReason

DecisionKind = Literal["CONTINUE", "REPROMPT", "TRANSFER", "UNREACHABLE"]


@dataclass(frozen=True)
class PolicyDecision:
    kind: DecisionKind
    transfer_reason: Optional[TransferReason] = None

    @classmethod
    def proceed(cls) -> "PolicyDecision":
        return cls("CONTINUE")

    @classmethod
    def transfer(cls, reason: TransferReason) -> "PolicyDecision":
        return cls("TRANSFER", reason)


# §1.2: các intent luôn chuyển máy, bất kể đang ở bước nào
_ALWAYS_TRANSFER: dict[Intent, TransferReason] = {
    Intent.CLINICAL_QUESTION: "CLINICAL_QUESTION",
    Intent.REQUEST_HUMAN: "PATIENT_REQUEST",
    Intent.OUT_OF_SCOPE: "OUT_OF_SCOPE",
    Intent.ABUSIVE: "OUT_OF_SCOPE",
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

    def check_silence(self, ctx: CallContext, caller: CallerInput) -> PolicyDecision:
        """§1.1.7: 3 lượt im lặng liên tiếp -> UNREACHABLE."""
        if not caller.is_silence:
            ctx.silent_turns = 0
            return PolicyDecision.proceed()
        ctx.silent_turns += 1
        if ctx.silent_turns >= self._settings.max_silent_turns:
            return PolicyDecision("UNREACHABLE")
        return PolicyDecision("REPROMPT")

    def check_exceptions(self, nlu: NLUResult) -> PolicyDecision:
        """§1.1.5, §1.2.1: ngoài phạm vi / lâm sàng -> chuyển máy, không đoán, không tự trả lời."""
        reason = _ALWAYS_TRANSFER.get(nlu.intent)
        return PolicyDecision.transfer(reason) if reason else PolicyDecision.proceed()

    def register_understanding(self, ctx: CallContext, understood: bool) -> PolicyDecision:
        """§1.1.5: 2 lần liên tiếp không hiểu -> chuyển máy NOT_UNDERSTOOD."""
        if understood:
            ctx.failed_understandings = 0
            return PolicyDecision.proceed()
        ctx.failed_understandings += 1
        if ctx.failed_understandings >= self._settings.max_failed_understandings:
            return PolicyDecision.transfer("NOT_UNDERSTOOD")
        return PolicyDecision("REPROMPT")
