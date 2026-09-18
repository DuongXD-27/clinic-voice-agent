"""Dialogue Manager: chọn câu hỏi tiếp theo, gọi tools khi đủ điều kiện, đặt `question_id`.

Nhận thẳng `ExtractionResult` (thiết kế IE v1.1). Mỗi phản hồi kèm `Understanding` để Policy đếm §1.1.5;
Dialogue không tự quyết chuyển máy vì không hiểu.

Quy ước:
- Mỗi câu hỏi nghiệp vụ đi qua `_ask`, lưu `question_id` + nội dung + lượt. Câu nhắc chung
  (im lặng, "em chưa hiểu") không đổi câu hỏi đang chờ, nên không tạo được bằng chứng xác nhận.
- Chỉ `agreement == AGREE` cho đúng câu hỏi xác nhận mới tạo bằng chứng và gọi lệnh ghi;
  REFUSE bỏ hành động chờ; UNCLEAR hỏi lại — câu đến khám thì đọc lại ngày, giờ, cơ sở bằng câu
  có / không (T-04), câu hủy / chọn slot thì bằng câu lựa chọn A/B.
- Slot chỉ lấy từ GET /slots của cuộc gọi; lời người gọi chỉ là tiêu chí lọc.
"""

import logging
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any, Optional

from callbot.engine.dialogue import templates as t
from callbot.engine.dialogue.llm.base import LLMClient
from callbot.engine.errors import (
    TURN_ABORTING_ERRORS,
    ClinicWriteRejected,
    SlotTaken,
    WriteOutcomeUnknown,
)
from callbot.engine.extraction.schema import (
    INVALID,
    Agreement,
    ExtractionResult,
    Field,
    Intent,
    QuestionId,
)
from callbot.engine.extraction.slot_choice import filter_slots, parse_slot_criteria
from callbot.engine.policy.guardrails import SevereFailureBlocked
from callbot.engine.policy.policy_engine import Understanding
from callbot.engine.session.context import ActionEvidence, CallContext, PendingAction, Question
from callbot.engine.tools.clinic_gateway import ClinicGateway
from callbot.engine.types import (
    BotAction,
    CallState,
    Outcome,
    TransferReason,
    UnreachableReason,
)
from callbot.engine.verification.identity import IdentityVerifier, VerificationStatus

logger = logging.getLogger(__name__)

MAX_SLOTS_PRESENTED = 3
# Nhu cầu người gọi nói ở bước danh tính: chỉ để trả lời "cần xác minh trước", không dùng sau xác minh
_BUSINESS_INTENTS = frozenset({Intent.CONFIRM, Intent.CANCEL, Intent.RESCHEDULE, Intent.BOOK})


@dataclass(frozen=True)
class Reply:
    action: BotAction
    understanding: Understanding = "UNDERSTOOD"


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
        # Luồng PDF: đọc hồ sơ ở lượt 0 và giữ dữ liệu chuẩn trong Session (T-01). Không ném lỗi.
        prepare = self._verifier.prepare(ctx)
        if prepare.transfer_reason is not None:
            # Không có hồ sơ để đối chiếu: không hỏi tên. Listing 1 không cho kết thúc ở lượt 0,
            # nên Policy.check_preconditions chuyển máy ở lượt 1.
            return BotAction(t.greeting_handoff(ctx.call.direction), "AWAITING_IDENTITY")
        return self._ask(
            ctx, QuestionId.ASK_NAME, t.greeting(ctx.call.direction), "AWAITING_IDENTITY"
        )

    def silence(self, ctx: CallContext) -> BotAction:
        # Không đổi câu hỏi đang chờ: "Alo, còn nghe máy không" không phải câu hỏi xác nhận
        return BotAction(utterance=t.SILENCE, state=ctx.state)

    def transfer(self, ctx: CallContext, reason: TransferReason) -> BotAction:
        # Rev 1.1 §2.1: inbound chưa tạo lịch thì Gateway không ghi gì (trả None), chỉ trả outcome
        if not ctx.ended:
            try:
                self._gateway.transfer(ctx, reason)
            except TURN_ABORTING_ERRORS:
                raise
            except (ClinicWriteRejected, SevereFailureBlocked):
                logger.error("Ghi TRANSFERRED thất bại cho %s", ctx.call_id)
        return BotAction(
            t.TRANSFER, "ENDED", ended=True, outcome="TRANSFERRED", transfer_reason=reason
        )

    def unreachable(self, ctx: CallContext, reason: UnreachableReason) -> BotAction:
        """§1.1.7: không để lại chi tiết lịch hẹn trên voicemail."""
        try:
            self._gateway.mark_unreachable(ctx, reason)
        except TURN_ABORTING_ERRORS:
            raise
        except (ClinicWriteRejected, SevereFailureBlocked):
            logger.error("Ghi UNREACHABLE thất bại cho %s", ctx.call_id)
        return BotAction(
            t.GOODBYE_UNREACHABLE,
            "ENDED",
            ended=True,
            outcome="UNREACHABLE",
            unreachable_reason=reason,
        )

    # --- Điều phối theo câu hỏi đang chờ -------------------------------------------

    def respond(self, ctx: CallContext, extraction: ExtractionResult, now: datetime) -> Reply:
        if extraction.intent.value is Intent.REPEAT_REQUEST and ctx.question is not None:
            # Đọc lại đúng câu đang chờ; không tính là không hiểu (thiết kế §6.1)
            return Reply(BotAction(ctx.question.text, ctx.state), "NEUTRAL")

        question = ctx.question.question_id if ctx.question else None
        if question in (QuestionId.ASK_NAME, QuestionId.ASK_DOB):
            return self._identity(ctx, extraction)
        if question is QuestionId.CONFIRM_READBACK:
            return self._attendance(ctx, extraction, now)
        if question is QuestionId.ASK_INTENT:
            return self._intent(ctx, extraction, now)
        if question is QuestionId.OFFER_SLOTS:
            return self._slot_choice(ctx, extraction, now)
        if question is QuestionId.SLOT_READBACK:
            return self._slot_readback(ctx, extraction, now)
        if question is QuestionId.CANCEL_RECONFIRM:
            return self._cancel_reconfirm(ctx, extraction, now)
        return self._not_understood(ctx)

    # --- Danh tính ---------------------------------------------------------------------

    def _identity(self, ctx: CallContext, ex: ExtractionResult) -> Reply:
        """Hỏi mở tên, ngày sinh (§1.1.2); nhận phần còn thiếu, kể cả khi người gọi nói gộp hai thứ.

        Chỉ tính là hiểu khi điền được trường CÒN THIẾU — nhắc lại điều đã có không reset bộ đếm §1.1.5,
        nên bước này không lặp vô hạn. Đủ hai trường thì đối chiếu một lần; không khớp thì chuyển ngay.
        """
        progressed = False
        if ctx.claimed_name is None and ex.full_name.found and ex.full_name.value:
            # Lưu đúng điều người gọi nói — không "sửa" theo hồ sơ; Verifier đối chiếu riêng
            ctx.claimed_name = ex.full_name.value
            progressed = True
        if ctx.claimed_dob is None and isinstance(ex.dob.value, date):
            ctx.claimed_dob = ex.dob.value
            progressed = True
        if ctx.claimed_name is not None and ctx.claimed_dob is not None:
            return self._verify(ctx)

        ask_name = ctx.claimed_name is None
        ctx.identity_step = "ASK_NAME" if ask_name else "ASK_DOB"
        question = QuestionId.ASK_NAME if ask_name else QuestionId.ASK_DOB
        dob_invalid = ex.dob.value == INVALID
        if progressed:
            text = (
                t.ASK_NAME_AFTER_DOB
                if ask_name
                else t.ASK_DOB_INVALID
                if dob_invalid
                else t.ASK_DOB
            )
            return Reply(self._ask(ctx, question, text, "AWAITING_IDENTITY"))

        if not ask_name and dob_invalid:
            # Người gọi đã cố đọc ngày sinh: câu hỏi lại cụ thể hữu ích hơn, dù câu có kèm nhu cầu khác
            return self._not_understood(ctx, question, t.ASK_DOB_INVALID)
        intent = ex.intent.value
        if intent is Intent.CANNOT_PROVIDE:
            text = t.ASK_NAME_DECLINED if ask_name else t.ASK_DOB_DECLINED
            return Reply(self._ask(ctx, question, text, "AWAITING_IDENTITY"), "DECLINED")
        if intent in _BUSINESS_INTENTS:
            # Nói nhu cầu trước khi xác minh: lần đầu không tính là không hiểu, không dùng nhu cầu này
            text = t.ASK_NAME_FOR_REQUEST if ask_name else t.ASK_DOB_FOR_REQUEST
            return Reply(self._ask(ctx, question, text, "AWAITING_IDENTITY"), "UNCLEAR")
        return self._not_understood(
            ctx, question, t.ASK_NAME_AGAIN if ask_name else t.ASK_DOB_AGAIN
        )

    def _verify(self, ctx: CallContext) -> Reply:
        result = self._verifier.verify(ctx)
        if result.status is not VerificationStatus.VERIFIED:
            # Không hỏi lại, không nói yếu tố nào sai — "ngày sinh chưa khớp" xác nhận tên đúng (§1.1.2)
            return Reply(self.transfer(ctx, result.transfer_reason or "IDENTITY_FAILED"))
        if not result.patient_id:
            logger.error("Xác minh %s không có patient_id", ctx.call_id)
            return Reply(self.transfer(ctx, "SYSTEM_ERROR"))

        ctx.identity_step = "VERIFIED"
        ctx.patient_id = result.patient_id
        if ctx.call.direction == "inbound":
            return Reply(
                self._ask(ctx, QuestionId.ASK_INTENT, t.ASK_INTENT_INBOUND, "AWAITING_INTENT")
            )
        appointment = self._gateway.get_appointment(ctx)
        return Reply(
            self._ask(
                ctx,
                QuestionId.CONFIRM_READBACK,
                t.appointment_summary(ctx, appointment),
                "AWAITING_INTENT",
                action="CONFIRM",
            )
        )

    # --- Outbound: đến khám được không ----------------------------------------------------

    def _attendance(self, ctx: CallContext, ex: ExtractionResult, now: datetime) -> Reply:
        """§1.1.3: chỉ ghi CONFIRMED khi người gọi đồng ý đúng câu đọc lại ngày, giờ, cơ sở (T-04).

        AGREE gồm cả "vâng / dạ / ừ" và câu khẳng định sẽ đến ("tôi sẽ đến" — Bảng 1); IE đã hạ câu
        ngập ngừng, câu hỏi đuôi, "nhưng ..." xuống UNCLEAR.
        """
        intent = ex.intent.value
        if intent in (Intent.CANCEL, Intent.RESCHEDULE):
            return self._start(ctx, intent, ex, now)

        agreement = ex.agreement.value
        if agreement is Agreement.AGREE:
            ctx.set_pending("CONFIRM")
            self._record_confirmation(ctx, ex)
            written = self._gateway.confirm(ctx)
            if written.get("status") != "CONFIRMED":
                # Mock nhận lệnh (2xx) nhưng bản ghi không ở CONFIRMED: không báo thành công, cũng không
                # ghi /transfer thay thế (lệnh đã commit, phiên đã khóa) — chặn lượt để đối soát.
                raise WriteOutcomeUnknown(
                    f"{ctx.call_id}: confirm trả status {written.get('status')}"
                )
            return Reply(self._finish("CONFIRMED", t.confirmed(ctx, written)))
        if agreement is Agreement.REFUSE:
            ctx.clear_pending()
            return Reply(
                self._ask(ctx, QuestionId.ASK_INTENT, t.ASK_CHANGE_OR_CANCEL, "AWAITING_INTENT")
            )
        if ex.agreement.found or intent is Intent.CONFIRM:
            # Chưa rõ: đọc lại ngày, giờ, cơ sở bằng câu có / không (kiến trúc §3.2), chưa ghi
            appointment = self._gateway.get_appointment(ctx)
            return Reply(
                self._ask(
                    ctx,
                    QuestionId.CONFIRM_READBACK,
                    t.attendance_reread(ctx, appointment),
                    ctx.state,
                    action="CONFIRM",
                ),
                "UNCLEAR",
            )
        return self._not_understood(ctx)

    # --- Câu hỏi ý định mở ---------------------------------------------------------------

    def _intent(self, ctx: CallContext, ex: ExtractionResult, now: datetime) -> Reply:
        intent = ex.intent.value
        if ctx.call.direction == "outbound":
            if intent is Intent.CONFIRM:
                ctx.set_pending("CONFIRM")
                appointment = self._gateway.get_appointment(ctx)
                return Reply(
                    self._ask(
                        ctx,
                        QuestionId.CONFIRM_READBACK,
                        t.attendance_readback(ctx, appointment),
                        "AWAITING_CONFIRMATION",
                        action="CONFIRM",
                    )
                )
            if intent in (Intent.CANCEL, Intent.RESCHEDULE):
                return self._start(ctx, intent, ex, now)
            return self._not_understood(ctx)

        if intent is Intent.BOOK:
            return self._start(ctx, intent, ex, now)
        if intent in (Intent.CONFIRM, Intent.CANCEL, Intent.RESCHEDULE):
            # Inbound chỉ có kịch bản đặt lịch mới (§1); việc với lịch có sẵn -> chuyển ngay (§1.1.5)
            return Reply(self.transfer(ctx, "OUT_OF_SCOPE"))
        return self._not_understood(ctx)

    def _start(
        self, ctx: CallContext, intent: Intent, ex: ExtractionResult, now: datetime
    ) -> Reply:
        if intent is Intent.CANCEL:
            ctx.set_pending("CANCEL")
            ctx.add_evidence(self._evidence(ctx, ex, "REQUEST", ex.intent))
            if ex.cancel_reason.found:
                ctx.cancel_reason = ex.cancel_reason.value
            return Reply(
                self._ask(
                    ctx,
                    QuestionId.CANCEL_RECONFIRM,
                    t.CANCEL_RECONFIRM,
                    "AWAITING_CONFIRMATION",
                    action="CANCEL",
                )
            )
        action: PendingAction = "RESCHEDULE" if intent is Intent.RESCHEDULE else "BOOK"
        ctx.set_pending(action)
        return self._offer_slots(ctx, now, criteria_text=ex.transcript)

    # --- Chọn slot -----------------------------------------------------------------------

    def _slot_choice(self, ctx: CallContext, ex: ExtractionResult, now: datetime) -> Reply:
        choice = ex.slot_choice.value
        if choice is not None and choice.kind == "MATCH":
            slot = ctx.find_slot(choice.slot_id)
            assert slot is not None and ctx.pending_action is not None
            ctx.select_slot(slot["slot_id"])
            return Reply(
                self._ask(
                    ctx,
                    QuestionId.SLOT_READBACK,
                    t.slot_readback(ctx, slot),
                    "AWAITING_CONFIRMATION",
                    action=ctx.pending_action,
                    slot_id=slot["slot_id"],
                )
            )
        if choice is not None and choice.kind == "AMBIGUOUS":
            # Không tự chọn slot đầu: đọc tối đa 3 slot trong số khớp, hỏi lại
            candidates = [s for s in ctx.slots if s["slot_id"] in choice.slot_ids]
            return Reply(self._present(ctx, candidates, t.SLOT_AMBIGUOUS), "NEUTRAL")
        if ex.agreement.value is Agreement.REFUSE:
            return self._abandon(ctx)
        if ctx.call.direction == "outbound" and ex.intent.value is Intent.CANCEL:
            return self._start(ctx, Intent.CANCEL, ex, now)
        if ex.slot_choice.found:
            # NO_MATCH có tiêu chí: đọc lại các khung đang có, tính là không hiểu (thiết kế §6.1)
            return Reply(self._present(ctx, ctx.slots, t.SLOT_NO_MATCH), "NOT_UNDERSTOOD")
        return self._not_understood(ctx)

    def _slot_readback(self, ctx: CallContext, ex: ExtractionResult, now: datetime) -> Reply:
        action, slot_id = ctx.pending_action, ctx.selected_slot_id
        slot = ctx.find_slot(slot_id)
        assert action in ("RESCHEDULE", "BOOK") and slot is not None and slot_id is not None

        agreement = ex.agreement.value
        if agreement is Agreement.AGREE:
            self._record_confirmation(ctx, ex)
            try:
                if action == "RESCHEDULE":
                    self._gateway.reschedule(ctx, slot_id)
                else:
                    self._gateway.book(ctx, slot_id)
            except SlotTaken:
                # Đọc lại /slots, đề xuất lại và cần xác nhận mới — không retry mù
                ctx.select_slot(None)
                return self._offer_slots(ctx, now, prefix=t.SLOT_TAKEN)
            outcome: Outcome = "RESCHEDULED" if action == "RESCHEDULE" else "BOOKED"
            return Reply(self._finish(outcome, t.done(outcome, slot)))
        if agreement is Agreement.REFUSE:
            if ex.intent.value in (Intent.RESCHEDULE, Intent.BOOK):
                # "không, khung khác" — vẫn đổi / đặt, chỉ bỏ slot này
                ctx.select_slot(None)
                return Reply(self._present(ctx, ctx.slots))
            return self._abandon(ctx)
        if ctx.call.direction == "outbound" and ex.intent.value is Intent.CANCEL:
            return self._start(ctx, Intent.CANCEL, ex, now)
        if ex.agreement.found:
            return Reply(
                self._ask(
                    ctx,
                    QuestionId.SLOT_READBACK,
                    t.slot_choice(ctx, slot),
                    "AWAITING_CONFIRMATION",
                    action=action,
                    slot_id=slot_id,
                ),
                "UNCLEAR",
            )
        return self._not_understood(ctx)

    # --- Hủy lịch --------------------------------------------------------------------------

    def _cancel_reconfirm(self, ctx: CallContext, ex: ExtractionResult, now: datetime) -> Reply:
        agreement = ex.agreement.value
        if agreement is Agreement.AGREE:
            # IE chỉ trả AGREE ở đây khi có động từ hủy tường minh (SF-05); "vâng" là UNCLEAR
            self._record_confirmation(ctx, ex)
            if ctx.cancel_reason is None and ex.cancel_reason.found:
                ctx.cancel_reason = ex.cancel_reason.value
            self._gateway.cancel(ctx, ctx.cancel_reason or "UNSPECIFIED")
            return Reply(self._finish("CANCELLED", t.done("CANCELLED")))
        if agreement is Agreement.REFUSE:
            return self._abandon(ctx)
        if ex.intent.value is Intent.RESCHEDULE:
            return self._start(ctx, Intent.RESCHEDULE, ex, now)
        if ex.agreement.found:
            return Reply(
                self._ask(
                    ctx,
                    QuestionId.CANCEL_RECONFIRM,
                    t.CANCEL_CHOICE,
                    "AWAITING_CONFIRMATION",
                    action="CANCEL",
                ),
                "UNCLEAR",
            )
        return self._not_understood(ctx)

    # --- Helpers ---------------------------------------------------------------------------

    def _abandon(self, ctx: CallContext) -> Reply:
        """Người gọi từ chối: bỏ hành động chờ, không ghi gì."""
        ctx.clear_pending()
        if ctx.call.direction == "inbound":
            return Reply(
                self._ask(ctx, QuestionId.ASK_INTENT, t.BOOKING_ABANDONED, "AWAITING_INTENT")
            )
        appointment = self._gateway.get_appointment(ctx)
        return Reply(
            self._ask(
                ctx,
                QuestionId.CONFIRM_READBACK,
                t.keep_appointment(ctx, appointment),
                "AWAITING_INTENT",
                action="CONFIRM",
            )
        )

    def _offer_slots(
        self,
        ctx: CallContext,
        now: datetime,
        criteria_text: Optional[str] = None,
        prefix: str = "",
    ) -> Reply:
        slots = self._gateway.list_open_slots(ctx, now)
        if not slots:
            ctx.clear_pending()
            return Reply(self.transfer(ctx, "OUT_OF_SCOPE"))
        candidates = slots
        if criteria_text:
            # "đổi sang buổi chiều": lọc trước khi đọc; thứ tự ("khung 2") chưa có nghĩa ở lượt này
            criteria = replace(parse_slot_criteria(criteria_text, now), ordinal=None)
            if not criteria.empty:
                candidates = filter_slots(slots, criteria) or slots
        return Reply(self._present(ctx, candidates, prefix))

    def _present(
        self, ctx: CallContext, candidates: list[dict[str, Any]], prefix: str = ""
    ) -> BotAction:
        presented = candidates[:MAX_SLOTS_PRESENTED]
        ctx.presented_slot_ids = [slot["slot_id"] for slot in presented]
        assert ctx.pending_action is not None
        return self._ask(
            ctx,
            QuestionId.OFFER_SLOTS,
            t.offer_slots(ctx, presented, prefix),
            "OFFERING_SLOTS",
            action=ctx.pending_action,
        )

    def _not_understood(
        self,
        ctx: CallContext,
        question_id: Optional[QuestionId] = None,
        text: str = t.NOT_UNDERSTOOD,
    ) -> Reply:
        if question_id is not None:
            # Hỏi lại cùng một câu hỏi danh tính bằng lời khác
            return Reply(self._ask(ctx, question_id, text, ctx.state), "NOT_UNDERSTOOD")
        return Reply(BotAction(text, ctx.state), "NOT_UNDERSTOOD")

    def _record_confirmation(self, ctx: CallContext, ex: ExtractionResult) -> None:
        ctx.add_evidence(self._evidence(ctx, ex, "CONFIRMATION", ex.agreement))

    @staticmethod
    def _evidence(
        ctx: CallContext, ex: ExtractionResult, kind: Any, source: Field[Any]
    ) -> ActionEvidence:
        assert ctx.pending_action is not None and source.value is not None
        return ActionEvidence(
            kind=kind,
            action=ctx.pending_action,
            slot_id=ctx.selected_slot_id,
            turn=ex.turn,
            question_id=ex.question_id,
            question_turn=ctx.question.turn if ctx.question else None,
            transcript=ex.transcript,
            label=source.value.value,
            provenance=source.provenance.value,
            span=source.span,
        )

    @staticmethod
    def _ask(
        ctx: CallContext,
        question_id: QuestionId,
        text: str,
        state: CallState,
        action: Optional[PendingAction] = None,
        slot_id: Optional[str] = None,
    ) -> BotAction:
        ctx.question = Question(question_id, text, ctx.turn, action=action, slot_id=slot_id)
        return BotAction(text, state)

    @staticmethod
    def _finish(outcome: Outcome, text: str) -> BotAction:
        return BotAction(text, "ENDED", ended=True, outcome=outcome)
