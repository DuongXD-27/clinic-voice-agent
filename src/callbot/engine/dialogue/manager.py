"""Dialogue Manager: sinh phản hồi, điều phối hội thoại theo kịch bản, gọi tools khi cần.

Mỗi handler trả về BotAction, hoặc None nếu câu người gọi không dùng được cho bước
hiện tại — orchestrator giao cho Policy quyết định hỏi lại hay chuyển máy (§1.1.5).
"""

import logging
from datetime import datetime
from typing import Any, Optional

from callbot.engine.dialogue import templates as t
from callbot.engine.dialogue.llm.base import LLMClient
from callbot.engine.nlu.schema import Intent, NLUResult
from callbot.engine.session.context import CallContext
from callbot.engine.tools.clinic_gateway import ClinicGateway
from callbot.engine.types import BotAction, TransferReason
from callbot.engine.verification.identity import IdentityVerifier, VerificationStatus

logger = logging.getLogger(__name__)

MAX_SLOTS_PRESENTED = 3
_PERIOD_HOURS = {"MORNING": range(0, 12), "AFTERNOON": range(12, 18), "EVENING": range(18, 24)}
_INTENT_FOR_ACTION = {
    "CONFIRM": Intent.CONFIRM_ATTENDANCE,
    "CANCEL": Intent.CANCEL,
    "RESCHEDULE": Intent.RESCHEDULE,
    "BOOK": Intent.BOOK,
}


class DialogueManager:
    def __init__(
        self,
        gateway: ClinicGateway,
        verifier: IdentityVerifier,
        llm: Optional[LLMClient] = None,
    ) -> None:
        self._gateway = gateway
        self._verifier = verifier
        # TODO: dùng LLM để diễn đạt tự nhiên hơn; mọi câu LLM sinh phải qua guardrails.assert_no_clinical_advice
        self._llm = llm

    # --- Mở đầu / kết thúc -----------------------------------------------------

    def opening(self, ctx: CallContext) -> BotAction:
        greeting = t.GREETING_OUTBOUND if ctx.call.direction == "outbound" else t.GREETING_INBOUND
        return BotAction(utterance=greeting, state="AWAITING_IDENTITY")

    def reprompt(self, ctx: CallContext, silence: bool = False) -> BotAction:
        if silence:
            return BotAction(utterance=t.SILENCE, state=ctx.state)
        if ctx.state == "AWAITING_IDENTITY":
            text = t.ASK_NAME_AGAIN if ctx.identity_step == "ASK_NAME" else t.ASK_DOB_AGAIN
            return BotAction(utterance=text, state=ctx.state)
        return BotAction(utterance=t.NOT_UNDERSTOOD, state=ctx.state)

    def transfer(self, ctx: CallContext, reason: TransferReason) -> BotAction:
        if ctx.target_appointment_id:
            try:
                self._gateway.transfer(ctx, reason)
            except Exception:
                logger.exception("Ghi TRANSFERRED thất bại cho %s", ctx.call_id)
        # TODO: inbound chưa tạo appointment (vd. PATIENT_NOT_FOUND) — contract chưa nêu ghi vào đâu
        return BotAction(t.TRANSFER, "ENDED", ended=True, outcome="TRANSFERRED", transfer_reason=reason)

    def unreachable(self, ctx: CallContext) -> BotAction:
        """§1.1.7: không để lại chi tiết lịch hẹn trên voicemail."""
        try:
            self._gateway.mark_unreachable(ctx)
        except NotImplementedError:
            logger.warning("mark_unreachable chưa được hỗ trợ bởi contract §4.2")
        return BotAction(t.GOODBYE_UNREACHABLE, "ENDED", ended=True, outcome="UNREACHABLE")

    # --- Điều phối theo state ---------------------------------------------------

    def respond(self, ctx: CallContext, nlu: NLUResult) -> Optional[BotAction]:
        handlers = {
            "AWAITING_IDENTITY": self._handle_identity,
            "AWAITING_INTENT": self._handle_intent,
            "AWAITING_CONFIRMATION": self._handle_confirmation,
            "OFFERING_SLOTS": self._handle_slot_choice,
        }
        handler = handlers.get(ctx.state)
        return handler(ctx, nlu) if handler else None

    def _handle_identity(self, ctx: CallContext, nlu: NLUResult) -> Optional[BotAction]:
        if ctx.identity_step == "ASK_NAME":
            if not nlu.entities.full_name:
                return None
            ctx.claimed_name = nlu.entities.full_name
            ctx.identity_step = "ASK_DOB"
            return BotAction(t.ASK_DOB, "AWAITING_IDENTITY")

        if not nlu.entities.dob:
            return None
        ctx.claimed_dob = nlu.entities.dob
        result = self._verifier.verify(ctx)
        if result.status is not VerificationStatus.VERIFIED:
            return self.transfer(ctx, result.transfer_reason or "IDENTITY_FAILED")

        ctx.identity_step = "VERIFIED"
        ctx.patient_id = result.patient_id
        if ctx.call.direction == "inbound":
            return BotAction(t.ASK_INTENT_INBOUND, "AWAITING_INTENT")
        appointment = self._gateway.get_appointment(ctx)
        return BotAction(t.appointment_summary(ctx, appointment), "AWAITING_INTENT")

    def _handle_intent(self, ctx: CallContext, nlu: NLUResult) -> Optional[BotAction]:
        outbound = ctx.call.direction == "outbound"
        if outbound and nlu.intent in (Intent.CONFIRM_ATTENDANCE, Intent.AFFIRM):
            ctx.pending_action = "CONFIRM"
            appointment = self._gateway.get_appointment(ctx)
            return BotAction(t.attendance_readback(ctx, appointment), "AWAITING_CONFIRMATION")
        if outbound and nlu.intent is Intent.CANCEL:
            ctx.pending_action = "CANCEL"
            ctx.cancel_confirmations = 1
            return BotAction(t.CANCEL_RECONFIRM, "AWAITING_CONFIRMATION")
        if outbound and nlu.intent is Intent.RESCHEDULE:
            ctx.pending_action = "RESCHEDULE"
            return self._offer_slots(ctx, nlu)
        if not outbound and nlu.intent in (Intent.BOOK, Intent.AFFIRM):
            ctx.pending_action = "BOOK"
            return self._offer_slots(ctx, nlu)
        return None

    def _handle_confirmation(self, ctx: CallContext, nlu: NLUResult) -> Optional[BotAction]:
        if nlu.intent is Intent.DENY:
            return self._abort_pending(ctx)
        action = ctx.pending_action
        accepted = {Intent.AFFIRM, _INTENT_FOR_ACTION.get(action)}
        if nlu.intent not in accepted:
            return None

        if action == "CONFIRM":
            self._gateway.confirm(ctx)
            return BotAction(t.done("CONFIRMED"), "ENDED", ended=True, outcome="CONFIRMED")
        if action == "CANCEL":
            ctx.cancel_confirmations = 2
            self._gateway.cancel(ctx, nlu.entities.cancel_reason or "UNSPECIFIED")
            return BotAction(t.done("CANCELLED"), "ENDED", ended=True, outcome="CANCELLED")
        if action in ("RESCHEDULE", "BOOK") and ctx.pending_slot_id:
            slot = self._presented_slot(ctx, ctx.pending_slot_id)
            # TODO: bắt 409 SLOT_TAKEN -> đọc lại /slots và đề xuất lại
            if action == "RESCHEDULE":
                self._gateway.reschedule(ctx, ctx.pending_slot_id)
                return BotAction(t.done("RESCHEDULED", slot), "ENDED", ended=True, outcome="RESCHEDULED")
            self._gateway.book(ctx, ctx.pending_slot_id)
            return BotAction(t.done("BOOKED", slot), "ENDED", ended=True, outcome="BOOKED")
        return None

    def _handle_slot_choice(self, ctx: CallContext, nlu: NLUResult) -> Optional[BotAction]:
        if nlu.intent is Intent.DENY:
            return self._abort_pending(ctx)
        index = nlu.entities.slot_choice_index
        slot: Optional[dict[str, Any]] = None
        if index is not None and 1 <= index <= len(ctx.presented_slots):
            slot = ctx.presented_slots[index - 1]
        elif nlu.entities.preferred_period:
            slot = next(iter(_filter_by_period(ctx.presented_slots, nlu.entities.preferred_period)), None)
        if slot is None:
            return None
        ctx.pending_slot_id = slot["slot_id"]
        return BotAction(t.slot_readback(ctx, slot), "AWAITING_CONFIRMATION")

    # --- Helpers ---------------------------------------------------------------

    def _offer_slots(self, ctx: CallContext, nlu: NLUResult) -> BotAction:
        slots = self._gateway.list_open_slots(ctx)
        if nlu.entities.preferred_period:
            slots = _filter_by_period(slots, nlu.entities.preferred_period) or slots
        # TODO: lọc theo department / preferred_date; loại slot trùng lịch cũ khi reschedule
        ctx.presented_slots = slots[:MAX_SLOTS_PRESENTED]
        if not ctx.presented_slots:
            return self.transfer(ctx, "OUT_OF_SCOPE")
        return BotAction(t.offer_slots(ctx, ctx.presented_slots), "OFFERING_SLOTS")

    def _abort_pending(self, ctx: CallContext) -> BotAction:
        ctx.pending_action = None
        ctx.pending_slot_id = None
        ctx.cancel_confirmations = 0
        return BotAction(t.KEEP_APPOINTMENT, "AWAITING_INTENT")

    @staticmethod
    def _presented_slot(ctx: CallContext, slot_id: str) -> Optional[dict[str, Any]]:
        return next((s for s in ctx.presented_slots if s["slot_id"] == slot_id), None)


def _filter_by_period(slots: list[dict[str, Any]], period: str) -> list[dict[str, Any]]:
    hours = _PERIOD_HOURS.get(period, range(24))
    return [s for s in slots if datetime.fromisoformat(s["starts_at"]).hour in hours]
