"""Dialogue Manager: chọn câu hỏi tiếp theo, gọi tools khi đủ điều kiện, đặt `question_id`.

Nhận thẳng `ExtractionResult` (thiết kế IE v1.1). Mỗi phản hồi kèm `Understanding` để Policy đếm §1.1.5;
Dialogue không tự quyết chuyển máy vì không hiểu.

Quy ước:
- Mỗi câu hỏi nghiệp vụ đi qua `_ask`, lưu `question_id` + nội dung + lượt. Câu "em chưa hiểu" không
  đổi câu hỏi đang chờ; nhắc im lặng và xin nhắc lại thì hỏi lại nguyên văn câu đó ở lượt hiện tại.
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
from callbot.engine.errors import (
    TURN_ABORTING_ERRORS,
    AppointmentUnusable,
    ClinicWriteRejected,
    EngineError,
    SlotTaken,
    WriteOutcomeUnknown,
)
from callbot.engine.extraction.cancel_reason import DEFAULT as DEFAULT_CANCEL_REASON
from callbot.engine.extraction.greeting import is_greeting, is_identity_question
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
# Lời chào ("alo", "hi em") ở bước danh tính không tính §1.1.5 tới mức này: đường truyền kém hay bot
# nói chồng làm người nghe chào lại nhiều lần. Quá mức thì mới là chưa hiểu, để bước này không lặp mãi.
MAX_NEUTRAL_GREETINGS = 2
# Nhu cầu người gọi nói ở bước danh tính: chỉ để trả lời "cần xác minh trước", không dùng sau xác minh
_BUSINESS_INTENTS = frozenset({Intent.CONFIRM, Intent.CANCEL, Intent.RESCHEDULE, Intent.BOOK})
# Clinic chắc chắn không ghi lệnh kết thúc: vẫn chuyển máy để nhân viên xử lý
_CLINIC_FAILURES = (ClinicWriteRejected, SevereFailureBlocked, AppointmentUnusable)


@dataclass(frozen=True)
class Reply:
    action: BotAction
    understanding: Understanding = "UNDERSTOOD"


class DialogueManager:
    def __init__(
        self,
        gateway: ClinicGateway,
        verifier: IdentityVerifier,
    ) -> None:
        self._gateway = gateway
        self._verifier = verifier

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
        """Kiến trúc §3.3: nhắc rồi hỏi lại câu đang chờ ở bước hiện tại (T-08).

        Câu hỏi được hỏi lại ở lượt này, nên câu trả lời lượt sau ứng với câu hỏi vừa nhắc nguyên văn,
        không phải với "còn nghe máy không" (guardrail chỉ nhận xác nhận cho câu hỏi ở lượt ngay trước).
        """
        if ctx.question is None:
            return BotAction(utterance=t.SILENCE, state=ctx.state)
        ctx.question = replace(ctx.question, turn=ctx.turn)
        return BotAction(utterance=f"{t.SILENCE} {ctx.question.text}", state=ctx.state)

    def transfer(self, ctx: CallContext, reason: TransferReason) -> BotAction:
        """Luôn chuyển máy: Clinic lỗi thì nhân viên vẫn xử lý được cuộc gọi.

        Rev 1.1 §2.1: inbound chưa tạo lịch thì Gateway không ghi gì (trả None).
        Không ghi được TRANSFERRED (từ chối, lịch không còn thao tác được, phản hồi hỏng) -> vẫn trả
        TRANSFERRED, ghi log để vận hành đối soát. Chỉ lỗi chưa rõ kết quả mới chặn lượt.
        """
        if not ctx.ended:
            try:
                written = self._gateway.transfer(ctx, reason)
            except TURN_ABORTING_ERRORS as exc:
                if isinstance(exc, EngineError) and exc.transfer_reason is None:
                    exc.transfer_reason = reason
                raise
            except _CLINIC_FAILURES as exc:
                logger.error(
                    "Ghi TRANSFERRED thất bại cho %s (%s), vẫn chuyển máy",
                    ctx.call_id,
                    type(exc).__name__,
                )
                written = None
            if written is not None and written.get("status") != "TRANSFERRED":
                raise WriteOutcomeUnknown(
                    f"{ctx.call_id}: transfer trả status {written.get('status')}"
                )
        return BotAction(
            t.TRANSFER, "ENDED", ended=True, outcome="TRANSFERRED", transfer_reason=reason
        )

    def unreachable(self, ctx: CallContext, reason: UnreachableReason) -> BotAction:
        """§1.1.7: không để lại chi tiết lịch hẹn trên voicemail.

        Không ghi được UNREACHABLE -> chuyển máy SYSTEM_ERROR (có ghi /transfer), không báo UNREACHABLE.
        """
        try:
            written = self._gateway.mark_unreachable(ctx, reason)
        except TURN_ABORTING_ERRORS:
            raise
        except _CLINIC_FAILURES as exc:
            logger.error(
                "Ghi UNREACHABLE thất bại cho %s (%s), chuyển máy", ctx.call_id, type(exc).__name__
            )
            return self.transfer(ctx, "SYSTEM_ERROR")
        if written.get("status") != "UNREACHABLE":
            raise WriteOutcomeUnknown(
                f"{ctx.call_id}: unreachable trả status {written.get('status')}"
            )
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
            # Đọc lại đúng câu đang chờ, hỏi lại ở lượt này; không tính là không hiểu (thiết kế §6.1)
            ctx.question = replace(ctx.question, turn=ctx.turn)
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

        if is_greeting(ex.transcript) and ctx.neutral_greetings < MAX_NEUTRAL_GREETINGS:
            # "Alo" chưa nghe rõ: hỏi lại, không tính §1.1.5. Đáp câu chào mở đầu (kể cả khi câu chào
            # được nhắc lại sau im lặng) thì chào lại một lần. Hỏi "ai đấy" vẫn được giới thiệu lại.
            ctx.neutral_greetings += 1
            opening = ctx.question is not None and ctx.question.text == t.greeting(
                ctx.call.direction
            )
            if is_identity_question(ex.transcript):
                # "Ai đấy?" là câu hỏi cần trả lời, kể cả sau reprompt / đã nhận tên.
                text = (
                    t.greeting_back(ctx.call.direction) if ask_name else t.INTRODUCE_AGAIN_ASK_DOB
                )
            elif not ask_name:
                text = t.ASK_DOB_AGAIN
            elif opening:
                text = t.greeting_back(ctx.call.direction)
            else:
                text = t.ASK_NAME_AGAIN
            return Reply(self._ask(ctx, question, text, "AWAITING_IDENTITY"), "NEUTRAL")
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
        appointment = self._gateway.get_actionable_appointment(ctx)
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
        if agreement is Agreement.AGREE and self._answers_last_question(ctx):
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
            appointment = self._gateway.get_actionable_appointment(ctx)
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
                appointment = self._gateway.get_actionable_appointment(ctx)
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
            # `set_pending` xóa bằng chứng VÀ lý do của hành động cũ: yêu cầu hủy mới bắt đầu từ
            # trắng, mặc định UNSPECIFIED nếu lượt này không nêu lý do (T-05 §3.2.1)
            ctx.set_pending("CANCEL")
            ctx.add_evidence(self._evidence(ctx, ex, "REQUEST", ex.intent))
            self._update_cancel_reason(ctx, ex)
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
        if agreement is Agreement.AGREE and self._answers_last_question(ctx):
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
        if agreement is Agreement.AGREE and self._answers_last_question(ctx):
            # IE chỉ trả AGREE ở đây khi có động từ hủy tường minh (SF-05); "vâng" là UNCLEAR
            self._record_confirmation(ctx, ex)
            self._update_cancel_reason(ctx, ex)
            written = self._gateway.cancel(ctx, ctx.cancel_reason or DEFAULT_CANCEL_REASON)
            if written.get("status") != "CANCELLED":
                # Như T-04: Mock nhận lệnh (2xx) nhưng bản ghi không ở CANCELLED thì không báo đã hủy,
                # cũng không ghi /transfer thay thế — chặn lượt để đối soát.
                raise WriteOutcomeUnknown(
                    f"{ctx.call_id}: cancel trả status {written.get('status')}"
                )
            return Reply(self._finish("CANCELLED", t.done("CANCELLED")))
        if ex.intent.value is Intent.RESCHEDULE:
            # Xét TRƯỚC nhánh REFUSE chung: "không hủy nữa, tôi muốn đổi lịch" là từ chối hủy kèm
            # yêu cầu đổi lịch, không phải muốn giữ lịch (T-05 §3.3). `_start` xóa dữ liệu hủy.
            return self._start(ctx, Intent.RESCHEDULE, ex, now)
        if agreement is Agreement.REFUSE:
            return self._abandon(ctx)

        # Chưa xác nhận: lý do vẫn được ghi nhận ở mọi lượt, nhưng ghi nhận lý do không phải đồng ý hủy
        had_reason = ctx.cancel_reason not in (None, DEFAULT_CANCEL_REASON)
        noted = self._update_cancel_reason(ctx, ex)
        if ex.agreement.found:
            # Có tín hiệu đồng ý / mâu thuẫn / ngập ngừng nhưng dưới ngưỡng hủy: hỏi lại bằng câu
            # lựa chọn, kể cả khi lượt đó có nêu lý do (§3.2.6)
            return Reply(self._ask_cancel_again(ctx, t.CANCEL_CHOICE), "UNCLEAR")
        if noted:
            # Chỉ lý do đầu tiên là tiến triển. Đổi sang lý do khác mà vẫn né xác nhận thì tính
            # UNCLEAR, nếu không "bận" / "hết tiền" luân phiên sẽ reset bộ đếm mãi, không bao giờ
            # chuyển máy. Lý do mới vẫn được ghi nhận.
            return Reply(
                self._ask_cancel_again(ctx, t.CANCEL_REASON_NOTED),
                "UNCLEAR" if had_reason else "UNDERSTOOD",
            )
        if ex.cancel_reason.found:
            # Lặp lại lý do cũ, hoặc nhiều lý do không chọn được, mà vẫn né xác nhận: hỏi lại rõ
            # hủy / giữ và tính UNCLEAR để Policy không để vòng lặp kéo dài
            return Reply(self._ask_cancel_again(ctx, t.CANCEL_CHOICE), "UNCLEAR")
        return self._not_understood(ctx)

    def _ask_cancel_again(self, ctx: CallContext, text: str) -> BotAction:
        return self._ask(
            ctx, QuestionId.CANCEL_RECONFIRM, text, "AWAITING_CONFIRMATION", action="CANCEL"
        )

    @staticmethod
    def _update_cancel_reason(ctx: CallContext, ex: ExtractionResult) -> bool:
        """Ghi nhận lý do hủy của lượt này; trả về True khi xác định được MỘT lý do mới (§3.2.3).

        `cancel_reason.found` nghĩa là lượt này có nội dung lý do. Nêu nhiều lý do không chọn được
        thì IE trả `UNSPECIFIED` kèm provenance: thay lý do cũ (không giữ ngầm) nhưng chưa xác định
        được gì nên không tính là tiến triển. Lượt không nói lý do giữ nguyên giá trị hiện tại.
        """
        if not ex.cancel_reason.found:
            return False
        reason = ex.cancel_reason.value or DEFAULT_CANCEL_REASON
        determined = reason != DEFAULT_CANCEL_REASON and reason != ctx.cancel_reason
        ctx.cancel_reason = reason
        return determined

    # --- Helpers ---------------------------------------------------------------------------

    def _abandon(self, ctx: CallContext) -> Reply:
        """Người gọi từ chối: bỏ hành động chờ, không ghi gì."""
        ctx.clear_pending()
        if ctx.call.direction == "inbound":
            return Reply(
                self._ask(ctx, QuestionId.ASK_INTENT, t.BOOKING_ABANDONED, "AWAITING_INTENT")
            )
        appointment = self._gateway.get_actionable_appointment(ctx)
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

    @staticmethod
    def _answers_last_question(ctx: CallContext) -> bool:
        """AGREE chỉ mở khóa lệnh ghi khi câu hỏi xác nhận được nói ở lượt ngay trước (T-08).

        Sau câu "em chưa hiểu" (không nhắc lại câu hỏi), "vâng" trả lời câu nhắc đó: đi nhánh chưa rõ,
        hỏi lại câu xác nhận — không gọi lệnh ghi để guardrail chặn thành SYSTEM_ERROR.
        """
        return ctx.question is not None and ctx.question.turn == ctx.turn - 1

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
