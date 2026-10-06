"""Dialogue Manager: chọn câu hỏi tiếp theo, gọi tools khi đủ điều kiện, đặt `question_id`.

Nhận thẳng `ExtractionResult` (thiết kế IE v1.1). Mỗi phản hồi kèm `Understanding` để Policy đếm §1.1.5;
Dialogue không tự quyết chuyển máy vì không hiểu.

Quy ước:
- Mỗi câu hỏi nghiệp vụ đi qua `questions.ask`, lưu `question_id` + nội dung + lượt. Câu "em chưa hiểu" không
  đổi câu hỏi đang chờ; nhắc im lặng và xin nhắc lại thì hỏi lại nguyên văn câu đó ở lượt hiện tại.
- Chỉ `agreement == AGREE` cho đúng câu hỏi xác nhận mới tạo bằng chứng và gọi lệnh ghi;
  REFUSE bỏ hành động chờ; UNCLEAR hỏi lại — câu đến khám và câu chốt slot thì đọc lại bằng câu
  có / không (T-04, T-10), câu hủy thì bằng câu lựa chọn A/B. Ở bước chọn slot, "không" trần không
  bỏ việc đổi / đặt mà hỏi A/B (T-10 Q-4).
- Slot chỉ lấy từ GET /slots của cuộc gọi; lời người gọi chỉ là tiêu chí lọc.
"""

import logging
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any, Optional

from callbot.engine.dialogue import inbound, outbound
from callbot.engine.dialogue import templates as t
from callbot.engine.dialogue.questions import ask
from callbot.engine.errors import (
    TURN_ABORTING_ERRORS,
    AppointmentUnusable,
    ClinicWriteRejected,
    EngineError,
    SlotTaken,
)
from callbot.engine.extraction.agreement import (
    gives_up_slot_change,
    is_bare_da,
    mentions_busy,
    mentions_cancel,
)
from callbot.engine.extraction.cancel_reason import DEFAULT as DEFAULT_CANCEL_REASON
from callbot.engine.extraction.greeting import (
    is_hold_request,
    is_identity_question,
    is_return_signal,
)
from callbot.engine.extraction.schema import (
    INVALID,
    Agreement,
    ExtractionResult,
    Field,
    IdentityStatus,
    IdentityValue,
    Intent,
    Provenance,
    QuestionId,
    SlotChoice,
    SlotCriteria,
)
from callbot.engine.extraction.slot_choice import (
    asks_back,
    filter_slots,
    parse_slot_criteria,
    requested_date,
    requested_slot_count,
    resolve_request,
)
from callbot.engine.policy.guardrails import SevereFailureBlocked
from callbot.engine.policy.policy_engine import Understanding
from callbot.engine.policy.sources import SourceRecorder
from callbot.engine.session.context import ActionEvidence, CallContext, PendingAction
from callbot.engine.tools.clinic_gateway import ClinicGateway
from callbot.engine.types import (
    BotAction,
    Outcome,
    TransferReason,
    UnreachableReason,
)
from callbot.engine.verification.identity import IdentityVerifier, VerificationStatus
from callbot.engine.verification.names import NameMatch

logger = logging.getLogger(__name__)

# PRD R-25: bot mời tối đa hai slot mỗi lượt; còn thì nói "còn N khung khác" (T-10)
MAX_SLOTS_PRESENTED = 2
# R-29: người gọi nêu tối đa 2 ngày / khoảng thời gian; ngày thứ ba -> giữ lịch cũ, PATIENT_REQUEST (D-5)
MAX_SLOT_ROUNDS = 2
# "Ai đấy?" ở bước danh tính là câu hỏi phải trả lời (R-26), không phải câu thiếu định danh: giới thiệu
# lại mà không dùng lượt hỏi lại R-40. Chỉ một lần mỗi cuộc gọi; lần sau tính ABSENT như lời chào.
MAX_IDENTITY_QUESTIONS = 1
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
        # Lệnh đọc dùng để NÓI đi qua SourceRecorder: Output Guard render lại từ đúng dữ liệu này (R-01)
        self._reads = SourceRecorder(gateway)
        self._verifier = verifier

    # --- Mở đầu / kết thúc -----------------------------------------------------

    def opening(self, ctx: CallContext) -> BotAction:
        """Chọn luồng mở đầu; mỗi hướng tự quyết định xử lý kết quả tra cứu."""
        flow = outbound if ctx.call.direction == "outbound" else inbound
        return flow.opening(ctx, self._verifier)

    def silence(self, ctx: CallContext) -> BotAction:
        """Kiến trúc §3.3: nhắc rồi hỏi lại câu đang chờ ở bước hiện tại (T-08).

        Câu hỏi được hỏi lại ở lượt này, nên câu trả lời lượt sau ứng với câu hỏi vừa nhắc nguyên văn,
        không phải với "còn nghe máy không" (guardrail chỉ nhận xác nhận cho câu hỏi ở lượt ngay trước).
        """
        if ctx.question is None:
            return BotAction(utterance=t.SILENCE, state=ctx.state)
        ctx.question = replace(ctx.question, turn=ctx.turn)
        return BotAction(utterance=t.silence_reprompt(ctx.question.text), state=ctx.state)

    def transfer(
        self, ctx: CallContext, reason: TransferReason, text: str = t.TRANSFER
    ) -> BotAction:
        """Luôn chuyển máy: Clinic lỗi thì nhân viên vẫn xử lý được cuộc gọi.

        Rev 1.1 §2.1: inbound chưa tạo lịch thì Gateway không ghi gì (trả None).
        Không ghi được TRANSFERRED (từ chối, lịch không còn thao tác được, phản hồi hỏng) -> vẫn trả
        TRANSFERRED, ghi log để vận hành đối soát. Chỉ lỗi chưa rõ kết quả mới chặn lượt.
        """
        if not ctx.ended:
            # Gateway chỉ trả về khi body ở đúng TRANSFERRED (T-12); sai trạng thái là WriteOutcomeUnknown
            try:
                self._gateway.transfer(ctx, reason)
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
        return BotAction(
            t.choose_static(ctx, text),
            "ENDED",
            ended=True,
            outcome="TRANSFERRED",
            transfer_reason=reason,
        )

    def unreachable(self, ctx: CallContext, reason: UnreachableReason) -> BotAction:
        """§1.1.7: không để lại chi tiết lịch hẹn trên voicemail.

        Không ghi được UNREACHABLE -> chuyển máy SYSTEM_ERROR (có ghi /transfer), không báo UNREACHABLE.
        """
        try:
            self._gateway.mark_unreachable(ctx, reason)
        except TURN_ABORTING_ERRORS:
            raise
        except _CLINIC_FAILURES as exc:
            logger.error(
                "Ghi UNREACHABLE thất bại cho %s (%s), chuyển máy", ctx.call_id, type(exc).__name__
            )
            return self.transfer(ctx, "SYSTEM_ERROR")
        return BotAction(
            t.choose_static(ctx, t.GOODBYE_UNREACHABLE),
            "ENDED",
            ended=True,
            outcome="UNREACHABLE",
            unreachable_reason=reason,
        )

    # --- Điều phối theo câu hỏi đang chờ -------------------------------------------

    def respond(self, ctx: CallContext, extraction: ExtractionResult, now: datetime) -> Reply:
        if extraction.model_failed:
            ctx.business_write_blocked = True
            if ctx.pending_action == "CANCEL" and extraction.cancel_reason.provenance in (
                Provenance.EXACT,
                Provenance.NORMALIZED,
            ):
                self._update_cancel_reason(ctx, extraction)
            return self._reask_confirmation(ctx, failed=True)
        if extraction.confirmation_conflict:
            if ctx.pending_action == "CANCEL":
                self._update_cancel_reason(ctx, extraction)
            return self._reask_confirmation(ctx)
        if is_hold_request(extraction.transcript):
            return Reply(BotAction(t.choose_static(ctx, t.HOLD), ctx.state), "NEUTRAL")
        if is_return_signal(extraction.transcript) and ctx.question is not None:
            ctx.question = replace(ctx.question, turn=ctx.turn)
            return Reply(BotAction(ctx.question.text, ctx.state), "NEUTRAL")
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
        if question is QuestionId.SLOT_REFUSE_CHOICE:
            return self._slot_refuse_choice(ctx, extraction, now)
        if question is QuestionId.ASK_SLOT_PREFERENCE:
            return self._slot_preference(ctx, extraction, now)
        if question is QuestionId.CANCEL_RECONFIRM:
            return self._cancel_reconfirm(ctx, extraction, now)
        return self._not_understood(ctx)

    def _reask_confirmation(self, ctx: CallContext, *, failed: bool = False) -> Reply:
        question = ctx.question
        if question is not None and question.question_id in (
            QuestionId.ASK_NAME,
            QuestionId.ASK_DOB,
        ):
            return self._retry_identity(ctx, question.question_id)
        if question is not None and question.action is not None:
            text = (
                t.CANCEL_CONFLICT
                if question.action == "CANCEL"
                else t.CONFIRM_CONFLICT
                if question.action == "CONFIRM"
                else t.SLOT_CONFLICT
            )
            return Reply(
                ask(
                    ctx,
                    question.question_id,
                    text,
                    ctx.state,
                    action=question.action,
                    slot_id=question.slot_id,
                ),
                "NOT_UNDERSTOOD" if failed else "UNCLEAR",
            )
        return self._not_understood(ctx)

    # --- Danh tính ---------------------------------------------------------------------

    def _identity(self, ctx: CallContext, ex: ExtractionResult) -> Reply:
        """R-40: only PRESENT values reach the verifier; each identifier gets one open retry."""
        name = ex.name_identity or self._legacy_identity(ex.full_name, ex.transcript)
        dob = ex.dob_identity or self._legacy_identity(ex.dob, ex.transcript)
        name_suspicious = False
        progressed = False
        if ctx.claimed_name is None and name.status is IdentityStatus.PRESENT:
            match = self._verifier.compare_name(ctx, name.value)
            if match is NameMatch.MISMATCH:
                return Reply(self.transfer(ctx, self._identity_failure_reason(ctx)))
            if match is NameMatch.SUSPICIOUS:
                name_suspicious = True
            else:
                ctx.claimed_name = name.value
                progressed = True
        if ctx.claimed_dob is None and dob.status is IdentityStatus.PRESENT:
            if not self._verifier.compare_dob(ctx, dob.value):
                return Reply(self.transfer(ctx, self._identity_failure_reason(ctx)))
            ctx.claimed_dob = dob.value
            progressed = True
        if ctx.claimed_name is not None and ctx.claimed_dob is not None:
            return self._verify(ctx)
        question = QuestionId.ASK_NAME if ctx.claimed_name is None else QuestionId.ASK_DOB
        ctx.identity_step = question.value
        if name_suspicious:
            return self._retry_identity(ctx, QuestionId.ASK_NAME, suspicious=True)
        if progressed:
            # Q-1: filling a missing identifier counts as understood, even when it was not the one
            # asked ("sinh ngày 14/3/1978" while asking the name). Only an unclear attempt at the
            # remaining identifier in the same turn spends its retry.
            pending = name if question is QuestionId.ASK_NAME else dob
            if pending.status in (IdentityStatus.UNCERTAIN, IdentityStatus.MULTIPLE):
                return self._retry_identity(ctx, question)
            text = t.ASK_NAME_AFTER_DOB if question is QuestionId.ASK_NAME else t.ASK_DOB
            return Reply(ask(ctx, question, text, "AWAITING_IDENTITY"))
        if is_identity_question(ex.transcript) and ctx.neutral_greetings < MAX_IDENTITY_QUESTIONS:
            ctx.neutral_greetings += 1
            text = (
                t.greeting_back(ctx.call.direction)
                if question is QuestionId.ASK_NAME
                else t.INTRODUCE_AGAIN_ASK_DOB
            )
            return Reply(ask(ctx, question, text, "AWAITING_IDENTITY"), "NEUTRAL")
        return self._retry_identity(ctx, question)

    @staticmethod
    def _legacy_identity(item: Field, transcript: str) -> IdentityValue:
        # Compatibility for explicitly injected extraction stubs; INVALID is never compared.
        if item.found and item.value not in (None, INVALID) and transcript:
            return IdentityValue(IdentityStatus.PRESENT, item.value, transcript)
        return IdentityValue(IdentityStatus.UNCERTAIN if item.found else IdentityStatus.ABSENT)

    @staticmethod
    def _identity_failure_reason(ctx: CallContext) -> TransferReason:
        return "PATIENT_NOT_FOUND" if ctx.call.direction == "inbound" else "IDENTITY_FAILED"

    def _retry_identity(
        self, ctx: CallContext, question: QuestionId, *, suspicious: bool = False
    ) -> Reply:
        key = question.value
        if ctx.identity_retries.get(key, 0) >= 1:
            reason = self._identity_failure_reason(ctx) if suspicious else "NOT_UNDERSTOOD"
            return Reply(self.transfer(ctx, reason))
        ctx.identity_retries[key] = 1
        text = t.ASK_NAME_AGAIN if question is QuestionId.ASK_NAME else t.ASK_DOB_AGAIN
        return Reply(ask(ctx, question, text, "AWAITING_IDENTITY"), "NOT_UNDERSTOOD")

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
            return Reply(ask(ctx, QuestionId.ASK_INTENT, t.ASK_INTENT_INBOUND, "AWAITING_INTENT"))
        appointment = self._reads.get_actionable_appointment(ctx)
        return Reply(
            ask(
                ctx,
                QuestionId.CONFIRM_READBACK,
                t.appointment_summary(
                    ctx, appointment, variant=t.choose_variant(ctx, "APPOINTMENT_SUMMARY")
                ),
                "AWAITING_INTENT",
                action="CONFIRM",
            )
        )

    # --- Outbound: đến khám được không ----------------------------------------------------

    def _attendance(self, ctx: CallContext, ex: ExtractionResult, now: datetime) -> Reply:
        """§1.1.3: chỉ ghi CONFIRMED khi người gọi đồng ý đúng câu đọc lại ngày, giờ, cơ sở (T-04).

        AGREE gồm "vâng / ừ" và câu khẳng định sẽ đến ("tôi sẽ đến" — Bảng 1); "dạ" không đủ. IE đã hạ câu
        ngập ngừng, câu hỏi đuôi, "nhưng ..." xuống UNCLEAR.
        """
        intent = ex.intent.value
        if intent in (Intent.CANCEL, Intent.RESCHEDULE):
            return self._start(ctx, intent, ex, now)

        agreement = ex.agreement.value
        if agreement is Agreement.AGREE and self._answers_last_question(ctx):
            ctx.set_pending("CONFIRM")
            self._record_confirmation(ctx, ex)
            # Gateway chỉ trả về khi bản ghi đã ở CONFIRMED (T-12); 2xx sai trạng thái -> đối soát
            written = self._gateway.confirm(ctx)
            return Reply(self._finish("CONFIRMED", t.confirmed(ctx, written)))
        if agreement is Agreement.REFUSE:
            ctx.clear_pending()
            self._update_cancel_reason(ctx, ex)
            return Reply(ask(ctx, QuestionId.ASK_INTENT, t.ASK_CHANGE_OR_CANCEL, "AWAITING_INTENT"))
        if ex.agreement.found or intent is Intent.CONFIRM:
            # Chưa rõ: đọc lại ngày, giờ, cơ sở bằng câu có / không (kiến trúc §3.2), chưa ghi
            appointment = self._reads.get_actionable_appointment(ctx)
            return Reply(
                ask(
                    ctx,
                    QuestionId.CONFIRM_READBACK,
                    t.attendance_reread(
                        ctx, appointment, variant=t.choose_variant(ctx, "ATTENDANCE_REREAD")
                    ),
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
                appointment = self._reads.get_actionable_appointment(ctx)
                return Reply(
                    ask(
                        ctx,
                        QuestionId.CONFIRM_READBACK,
                        t.attendance_readback(
                            ctx, appointment, variant=t.choose_variant(ctx, "ATTENDANCE_READBACK")
                        ),
                        "AWAITING_CONFIRMATION",
                        action="CONFIRM",
                    )
                )
            if intent in (Intent.CANCEL, Intent.RESCHEDULE):
                return self._start(ctx, intent, ex, now)
            if ex.cancel_reason.found:
                self._update_cancel_reason(ctx, ex)
            if ex.cancel_reason.found and ex.cancel_reason.value != DEFAULT_CANCEL_REASON:
                # "Đổi hay hủy?" -> "hôm đó tôi đi công tác": người gọi kể vì sao không đến nhưng
                # chưa chọn. Hỏi lại đúng câu đó; lần đầu không tính §1.1.5 (T-04 §8, Q-2).
                return Reply(
                    ask(ctx, QuestionId.ASK_INTENT, t.ASK_CHANGE_OR_CANCEL, "AWAITING_INTENT"),
                    "UNCLEAR",
                )
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
            # Lý do vừa nêu ở câu "đổi hay hủy" thuộc cùng yêu cầu. Không mang lý do
            # của một hành động hủy/đổi đã bỏ sang yêu cầu mới.
            prior_reason = (
                ctx.cancel_reason
                if ctx.pending_action is None
                and ctx.question is not None
                and ctx.question.question_id is QuestionId.ASK_INTENT
                else None
            )
            ctx.set_pending("CANCEL")
            ctx.cancel_reason = prior_reason
            ctx.add_evidence(self._evidence(ctx, ex, "REQUEST", ex.intent))
            self._update_cancel_reason(ctx, ex)
            return Reply(self._ask_cancel_readback(ctx))
        action: PendingAction = "RESCHEDULE" if intent is Intent.RESCHEDULE else "BOOK"
        ctx.set_pending(action)
        return self._new_request(ctx, now, ex.transcript)

    def _ask_cancel_readback(self, ctx: CallContext) -> BotAction:
        """Đọc lại đúng lịch sắp hủy trong câu xác nhận lần hai (§1.1.4)."""
        appointment = self._reads.get_actionable_appointment(ctx)
        return ask(
            ctx,
            QuestionId.CANCEL_RECONFIRM,
            t.cancel_readback(ctx, appointment, variant=t.choose_variant(ctx, "CANCEL_READBACK")),
            "AWAITING_CONFIRMATION",
            action="CANCEL",
        )

    # --- Chọn slot -----------------------------------------------------------------------

    def _slot_choice(self, ctx: CallContext, ex: ExtractionResult, now: datetime) -> Reply:
        choice = ex.slot_choice.value
        if _busy(ex.transcript):
            # Xét trước khi hiểu giờ trong câu là chọn khung: "10 giờ rưỡi tôi bận" là không nhận khung
            # 10 giờ rưỡi, không phải chọn nó (T-10 §3.8.1)
            return self._drop_busy_slots(ctx, ex, now)
        if choice is not None and _weekday_off_page(choice, ctx.presented_slot_ids):
            # "thứ Ba" / "chiều thứ Sáu" không khớp khung nào vừa đọc: yêu cầu mới, quy thứ trần theo
            # R-30 (tuần này; đã qua / hôm nay thì hỏi lại) — không tự hiểu thành thứ đó tuần sau
            # (GC-DATE-03, eval R142)
            return self._new_request(ctx, now, ex.transcript)
        picked = _picked(ctx, choice)
        if picked is not None:
            return Reply(self._read_back(ctx, picked))
        if choice is not None and choice.kind == "MORE":
            return self._offer_next(ctx, now, _more_prefix(ex))
        if choice is not None and choice.kind == "ANY" and ctx.presented_slot_ids:
            # "khung nào cũng được": người gọi để bot chọn — đọc câu chốt khung sớm nhất trang này,
            # vẫn phải đồng ý mới ghi (D-1)
            return Reply(self._read_back(ctx, ctx.presented_slot_ids[0]))
        if choice is not None and ex.slot_choice.found:
            if choice.kind == "AMBIGUOUS" and not _names_a_date(choice.criteria):
                # "cái 3 giờ", "buổi sáng": chỉ giờ / buổi / thứ, khớp nhiều khung đã có -> không tự chọn
                # (IE §5.7): đọc tối đa 2 khung khớp (R-25) rồi hỏi lại. Không coi là yêu cầu mới, nếu
                # không "3 giờ chiều thứ Tư" thành thứ Tư tuần này đã kín (eval R135). Khung đã từ
                # chối không đọc lại (V-9)
                candidates = [
                    s
                    for s in ctx.slots
                    if s["slot_id"] in choice.slot_ids and s["slot_id"] not in ctx.refused_slot_ids
                ]
                if len(candidates) > 1:
                    page = candidates[:MAX_SLOTS_PRESENTED]
                    return Reply(self._present(ctx, now, page, t.SLOT_AMBIGUOUS), "NEUTRAL")
                if candidates and candidates[0]["slot_id"] in _pickable(ctx):
                    return Reply(self._read_back(ctx, candidates[0]["slot_id"]))
            if _new_time_request(choice.criteria):
                # "ngày 19 thì sao": yêu cầu thời gian mới, lọc lại từ GET /slots (T-10 V-10)
                return self._new_request(ctx, now, ex.transcript)
            # "khung 3" khi mới đọc 2 khung: nói rõ rồi đọc lại trang, không tự chọn
            page = [s for s in ctx.slots if s["slot_id"] in ctx.presented_slot_ids]
            return Reply(self._present(ctx, now, page, t.SLOT_NOT_IN_PAGE), "UNCLEAR")
        if ex.agreement.value is Agreement.REFUSE:
            return self._refuse_slots(ctx, ex, now)
        if ctx.call.direction == "outbound" and ex.intent.value is Intent.CANCEL:
            return self._start(ctx, Intent.CANCEL, ex, now)
        return self._not_understood(ctx)

    def _drop_busy_slots(self, ctx: CallContext, ex: ExtractionResult, now: datetime) -> Reply:
        """Người gọi báo bận khi nghe các khung (T-10 §3.8.1).

        Có nhắc khung ("10 giờ rưỡi tôi bận", "chiều tôi bận", "khung 1 tôi bận"): bỏ các khung đó
        (V-9), đọc lại khung còn lại của trang vừa đọc. Không nhắc khung nào ("hôm đó tôi bận") hoặc
        trang không còn khung: không nhận các khung vừa đọc, hỏi A/B như "không" trần (Q-4).
        """
        busy_ids = _mentioned_slot_ids(ex.slot_choice.value)
        if busy_ids:
            _refuse(ctx, busy_ids)
            ctx.select_slot(None)
            left = [
                s
                for s in ctx.slots
                if s["slot_id"] in ctx.presented_slot_ids
                and s["slot_id"] not in ctx.refused_slot_ids
            ]
            if len(left) == 1:
                return Reply(self._offer_one(ctx, left[0]))
            if left:
                return Reply(self._present(ctx, now, left))
        return self._refuse_slots(ctx, ex, now)

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
                # Đọc lại /slots, đề xuất lại theo yêu cầu đang có (G-7) và cần xác nhận mới. Khung đã
                # đọc mà người gọi chưa từ chối được đọc lại (GC-RES-06); khung bị lấy không còn trong /slots
                ctx.select_slot(None)
                ctx.offered_slot_ids = []
                return self._offer_slots(ctx, now, prefix=t.SLOT_TAKEN)
            if action == "RESCHEDULE":
                return Reply(self._finish("RESCHEDULED", t.rescheduled_done(ctx, slot)))
            return Reply(self._finish("BOOKED", t.booked_done(ctx, slot)))

        choice = ex.slot_choice.value
        # "sao lại là thứ Sáu", "thứ Sáu à": hỏi lại câu vừa đọc, không phải chọn khung / ngày khác
        asking = asks_back(ex.transcript)
        # IE trả UNCLEAR cho câu kể hoàn cảnh (T-04 §8); ở câu chốt khung, "tôi bận" là không nhận khung.
        # Xét trước khi hiểu giờ trong câu là chọn khung: "10 giờ rưỡi tôi bận" không phải chọn 10 giờ rưỡi
        busy = agreement is not Agreement.AGREE and _busy(ex.transcript)
        busy_ids = _mentioned_slot_ids(choice) if busy else []
        if busy_ids and slot_id not in busy_ids:
            # Bận khung khác (không phải khung đang chốt): bỏ khung đó, hỏi lại có/không khung này
            _refuse(ctx, busy_ids)
            return self._reask_readback(ctx, slot, action, bare_da=False)
        picked = None if busy or asking else _picked(ctx, choice)
        if picked is not None and picked != slot_id:
            # "thôi lấy khung 2": đổi sang khung khác đã đọc, bằng chứng của khung cũ bị xóa
            return Reply(self._read_back(ctx, picked))
        # Nhắc lại chính khung đang chốt ("3 giờ rưỡi", "cái thứ Năm") là chưa trả lời có/không
        restates = choice is not None and slot_id in choice.slot_ids
        new_time = (
            choice is not None
            and ex.slot_choice.found
            and _new_time_request(choice.criteria)
            and not (asking or busy or restates)
        )
        more = choice is not None and choice.kind == "MORE"
        if agreement is Agreement.REFUSE or more or new_time or busy:
            # Bỏ khung này và các khung người gọi báo bận, không đọc lại (T-10 V-9). Các khung đã đọc
            # mà người gọi chưa từ chối vẫn là lựa chọn ("không, khung khác" -> khung còn lại cùng ngày)
            _refuse(ctx, [slot_id, *busy_ids])
            ctx.offered_slot_ids = []
            ctx.select_slot(None)
            if new_time:
                return self._new_request(ctx, now, ex.transcript)
            if more or ex.intent.value in (Intent.RESCHEDULE, Intent.BOOK):
                # "không, khung khác": vẫn đổi / đặt, đọc khung tiếp theo
                return self._offer_next(ctx, now, _more_prefix(ex))
            return self._refuse_slots(ctx, ex, now)
        if ctx.call.direction == "outbound" and ex.intent.value is Intent.CANCEL:
            return self._start(ctx, Intent.CANCEL, ex, now)
        bare_da = is_bare_da(ex.transcript)
        if (
            ex.agreement.found
            or restates
            or (choice is not None and choice.kind == "MATCH")
            or asking
            or bare_da
        ):
            return self._reask_readback(ctx, slot, action, bare_da)
        return self._not_understood(ctx)

    def _reask_readback(
        self, ctx: CallContext, slot: dict[str, Any], action: str, bare_da: bool
    ) -> Reply:
        """Chưa rõ: hỏi lại câu có/không cùng khung. "dạ" không phải đồng ý (PRD R-23, GC-CONF-01):
        nhắc người gọi nói "đồng ý" (T-10 D-2)."""
        reask = t.slot_readback_da if bare_da else t.slot_readback
        return Reply(
            ask(
                ctx,
                QuestionId.SLOT_READBACK,
                reask(ctx, slot, action),
                "AWAITING_CONFIRMATION",
                action=action,
                slot_id=slot["slot_id"],
            ),
            "UNCLEAR",
        )

    def _slot_refuse_choice(self, ctx: CallContext, ex: ExtractionResult, now: datetime) -> Reply:
        """Câu A/B "nghe khung khác hay giữ lịch cũ" sau lời từ chối trần (T-10 Q-4).

        Chỉ khung đã đọc và chưa bị từ chối mới chọn thẳng được; nêu thời gian khác là yêu cầu mới
        (tính vòng R-29, quy thứ R-30).
        """
        choice = ex.slot_choice.value
        if _busy(ex.transcript) and _mentioned_slot_ids(choice):
            # "chiều tôi bận": bỏ các khung đó (V-9), vẫn chưa biết nghe khung khác hay giữ lịch
            _refuse(ctx, _mentioned_slot_ids(choice))
            return self._refuse_slots(ctx, ex, now)
        picked = _picked(ctx, choice)
        if picked is not None:
            return Reply(self._read_back(ctx, picked))
        if choice is not None and ex.slot_choice.found and _new_time_request(choice.criteria):
            return self._new_request(ctx, now, ex.transcript)
        if choice is not None and choice.kind in ("MORE", "ANY"):
            return self._offer_next(ctx, now, _more_prefix(ex))
        if gives_up_slot_change(ex.transcript):
            return self._give_up(ctx)
        if ctx.call.direction == "outbound" and ex.intent.value is Intent.CANCEL:
            return self._start(ctx, Intent.CANCEL, ex, now)
        if ex.agreement.value is Agreement.REFUSE:
            # "không" trả lời câu A/B: vẫn chưa biết nghe khung khác hay giữ lịch -> hỏi lại, không đoán
            return self._refuse_slots(ctx, ex, now)
        return self._not_understood(ctx)

    def _slot_preference(self, ctx: CallContext, ex: ExtractionResult, now: datetime) -> Reply:
        """Đã đọc hết khung của yêu cầu: người gọi nêu ngày khác hoặc giữ lịch cũ (T-10 §3.2).

        Nêu ngày / giờ là yêu cầu mới kể cả khi khớp đúng một khung: tính vòng (R-29), quy thứ trần
        (R-30), bỏ khung đã từ chối (V-9). Chỉ khung đã đọc và chưa bị từ chối mới chọn thẳng được.
        """
        assert ctx.pending_action in ("RESCHEDULE", "BOOK")
        choice = ex.slot_choice.value
        if _busy(ex.transcript) and _mentioned_slot_ids(choice):
            # "thứ Sáu tôi bận": không phải xin thứ Sáu — bỏ các khung đó, hỏi lại ngày
            _refuse(ctx, _mentioned_slot_ids(choice))
            return self._ask_slot_preference(ctx)
        picked = _picked(ctx, choice)
        if picked is not None:
            return Reply(self._read_back(ctx, picked))
        if choice is not None and ex.slot_choice.found and _new_time_request(choice.criteria):
            return self._new_request(ctx, now, ex.transcript)
        if choice is not None and choice.kind == "ANY":
            # Đã đọc hết khung, người gọi "ngày nào cũng được": đọc lại từ khung sớm nhất. Tính 1 vòng
            # như nêu ngày mới, nếu không "khung khác" / "nào cũng được" luân phiên lặp mãi (§3.2)
            if ctx.slot_round >= MAX_SLOT_ROUNDS:
                return self._rounds_exhausted(ctx)
            ctx.slot_round += 1
            # Bỏ tiêu chí, ngày xin và các khung đã đọc; khung đã từ chối vẫn không đọc lại (V-9)
            ctx.reset_slot_request(None)
            return self._offer_slots(ctx, now)
        if gives_up_slot_change(ex.transcript):
            return self._give_up(ctx)
        if ctx.call.direction == "outbound" and ex.intent.value is Intent.CANCEL:
            return self._start(ctx, Intent.CANCEL, ex, now)
        if choice is not None and choice.kind == "MORE":
            # "ngày khác" mà chưa nói ngày nào: hỏi cụ thể
            return self._ask_slot_preference(ctx)
        return self._not_understood(ctx)

    def _ask_slot_preference(self, ctx: CallContext) -> Reply:
        action = ctx.pending_action
        assert action is not None
        text = t.ASK_SLOT_PREFERENCE[action]
        return Reply(
            ask(ctx, QuestionId.ASK_SLOT_PREFERENCE, text, ctx.state, action=action), "UNCLEAR"
        )

    # --- Hủy lịch --------------------------------------------------------------------------

    def _cancel_reconfirm(self, ctx: CallContext, ex: ExtractionResult, now: datetime) -> Reply:
        agreement = ex.agreement.value
        if agreement is Agreement.AGREE and self._answers_last_question(ctx):
            # IE chỉ trả AGREE ở đây khi có động từ hủy tường minh (SF-05); "vâng" là UNCLEAR
            self._record_confirmation(ctx, ex)
            self._update_cancel_reason(ctx, ex)
            # Như T-04: Gateway chỉ trả về khi bản ghi đã ở CANCELLED (T-12)
            self._gateway.cancel(ctx, ctx.cancel_reason or DEFAULT_CANCEL_REASON)
            return Reply(self._finish("CANCELLED", t.cancelled_done()))
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
        return ask(ctx, QuestionId.CANCEL_RECONFIRM, text, "AWAITING_CONFIRMATION", action="CANCEL")

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
            return Reply(ask(ctx, QuestionId.ASK_INTENT, t.BOOKING_ABANDONED, "AWAITING_INTENT"))
        appointment = self._reads.get_actionable_appointment(ctx)
        return Reply(
            ask(
                ctx,
                QuestionId.CONFIRM_READBACK,
                t.keep_appointment(
                    ctx, appointment, variant=t.choose_variant(ctx, "KEEP_APPOINTMENT")
                ),
                "AWAITING_INTENT",
                action="CONFIRM",
            )
        )

    def _new_request(self, ctx: CallContext, now: datetime, request: str) -> Reply:
        """Người gọi nêu thời gian: mỗi ngày / khoảng nêu ra là một vòng (R-29, T-10 §3.2 a, e).

        Câu không có tiêu chí (D-1: "tôi muốn đổi lịch") không tính vòng. Đã nêu đủ 2 ngày mà còn nêu
        ngày thứ ba -> không tra nữa, giữ lịch cũ, chuyển máy.
        """
        criteria = _criteria(request, now)
        if criteria.date_issue is not None:
            return self._ask_date_again(ctx, criteria)
        if not criteria.empty:
            if ctx.slot_round >= MAX_SLOT_ROUNDS:
                return self._rounds_exhausted(ctx)
            ctx.slot_round += 1
        return self._offer_slots(ctx, now, request=request)

    def _offer_slots(
        self,
        ctx: CallContext,
        now: datetime,
        request: Optional[str] = None,
        prefix: str = "",
    ) -> Reply:
        """Đọc lại GET /slots rồi đề xuất theo yêu cầu thời gian của người gọi.

        `request`: lời người gọi vừa nói — yêu cầu mới, các khung đã đọc / từ chối trước đó không còn
        áp dụng. `None` thì giữ yêu cầu đang có (đề xuất lại sau SLOT_TAKEN, G-7).
        Đổi lịch sang một ngày cụ thể: tìm từ ngày đó đến 7 ngày sau, đúng cơ sở của lịch hẹn (R-29).
        """
        criteria = _criteria(request if request is not None else ctx.slot_request or "", now)
        day, clinic_id = None, None
        if ctx.pending_action == "RESCHEDULE":
            if request is not None:
                day = requested_date(criteria, now)
            elif ctx.slot_day is not None:
                # Đề xuất lại (SLOT_TAKEN): tìm lại từ ngày người gọi xin, kể cả khi yêu cầu đã bỏ
                # tiêu chí vì ngày đó kín / không đúng giờ — không tra từ hôm nay (R-29)
                day = date.fromisoformat(ctx.slot_day)
            clinic_id = self._gateway.get_appointment(ctx).get("clinic_id")
        slots = self._reads.list_open_slots(ctx, now, date_from=day, clinic_id=clinic_id)
        taken = prefix == t.SLOT_TAKEN
        if not slots:
            # Hết sạch khung trống: nói lý do rồi chuyển máy (D-4)
            ctx.clear_pending()
            text = t.SLOT_TAKEN_NO_SLOTS_TRANSFER if taken else t.NO_SLOTS_TRANSFER
            return Reply(self.transfer(ctx, "OUT_OF_SCOPE", text))
        if request is not None:
            day_iso = day.isoformat() if day is not None else None
            if criteria.empty:
                # D-1: chưa nêu thời gian -> 2 khung sớm nhất + mời nêu ngày khác trong cùng câu
                ctx.reset_slot_request(None)
                return self._offer_next(ctx, now, invite=True)
            # Khung đã từ chối không tính là khớp (V-9): "10 giờ rưỡi" sau khi đã không nhận khung
            # 10 giờ rưỡi duy nhất là chưa có khung đúng giờ xin
            refused = set(ctx.refused_slot_ids)
            if filter_slots([s for s in slots if s["slot_id"] not in refused], criteria):
                ctx.reset_slot_request(request, day_iso)
            else:
                # Không có khung theo yêu cầu: nói rõ rồi đọc khung sớm nhất, không im lặng coi như
                # đúng ý (G-3). Xin giờ không có không phải hiểu sai (Q-3). Có ngày xin: báo ngày đó
                # kín rồi đọc khung gần ngày xin nhất — cửa sổ bắt đầu từ ngày xin nên sớm nhất là
                # gần nhất (GC-RES-02, D-3)
                ctx.reset_slot_request(None, day_iso)
                if day is not None and not filter_slots(slots, _dates_only(criteria)):
                    return self._offer_next(ctx, now, understanding="NEUTRAL", full_date=day)
                # Ngày xin còn khung nhưng không đúng giờ xin: cửa sổ bắt đầu từ ngày xin nên khung
                # đọc đầu tiên là khung của chính ngày đó (R-29)
                return self._offer_next(ctx, now, t.SLOT_NO_MATCH, "NEUTRAL")
        return self._offer_next(ctx, now, prefix)

    def _offer_next(
        self,
        ctx: CallContext,
        now: datetime,
        prefix: str = "",
        understanding: Understanding = "UNDERSTOOD",
        full_date: Optional[date] = None,
        invite: bool = False,
    ) -> Reply:
        """Đọc các khung chưa đọc / chưa bị từ chối của yêu cầu hiện tại, tối đa 2 khung (R-25)."""
        remaining = self._unoffered(ctx, now)
        if not remaining:
            return self._slots_exhausted(ctx, taken=prefix == t.SLOT_TAKEN)
        if len(remaining) == 1:
            # Chỉ còn một khung: đọc và hỏi có/không luôn (Hình 0), không hỏi "chọn khung nào"
            return Reply(self._offer_one(ctx, remaining[0], prefix, full_date), understanding)
        page = remaining[:MAX_SLOTS_PRESENTED]
        ctx.offered_slot_ids.extend(slot["slot_id"] for slot in page)
        return Reply(self._present(ctx, now, page, prefix, full_date, invite), understanding)

    def _unoffered(self, ctx: CallContext, now: datetime) -> list[dict[str, Any]]:
        candidates = ctx.slots
        if ctx.slot_request:
            candidates = filter_slots(ctx.slots, _criteria(ctx.slot_request, now))
        skipped = {*ctx.offered_slot_ids, *ctx.refused_slot_ids}
        return [slot for slot in candidates if slot["slot_id"] not in skipped]

    def _present(
        self,
        ctx: CallContext,
        now: datetime,
        page: list[dict[str, Any]],
        prefix: str = "",
        full_date: Optional[date] = None,
        invite: bool = False,
    ) -> BotAction:
        ctx.presented_slot_ids = [slot["slot_id"] for slot in page]
        action = ctx.pending_action
        assert action is not None
        remaining = len(self._unoffered(ctx, now))
        return ask(
            ctx,
            QuestionId.OFFER_SLOTS,
            t.offer_slots(
                ctx,
                page,
                prefix,
                remaining,
                full_date,
                action if invite else None,
                variant=t.choose_variant(ctx, "OFFER_SLOTS"),
            ),
            "OFFERING_SLOTS",
            action=ctx.pending_action,
        )

    def _offer_one(
        self,
        ctx: CallContext,
        slot: dict[str, Any],
        prefix: str = "",
        full_date: Optional[date] = None,
    ) -> BotAction:
        action = ctx.pending_action
        assert action is not None
        ctx.select_slot(slot["slot_id"])
        ctx.presented_slot_ids = [slot["slot_id"]]
        if slot["slot_id"] not in ctx.offered_slot_ids:
            ctx.offered_slot_ids.append(slot["slot_id"])
        return ask(
            ctx,
            QuestionId.SLOT_READBACK,
            t.slot_offer_readback(
                ctx,
                slot,
                action,
                prefix,
                full_date,
                variant=t.choose_variant(ctx, "SLOT_OFFER_READBACK"),
            ),
            "AWAITING_CONFIRMATION",
            action=action,
            slot_id=slot["slot_id"],
        )

    def _read_back(self, ctx: CallContext, slot_id: Optional[str]) -> BotAction:
        """Người gọi chọn một khung: đọc lại giờ, thứ, ngày, cơ sở rồi hỏi đồng ý (§1.1.6, §1.1.10)."""
        slot = ctx.find_slot(slot_id)
        action = ctx.pending_action
        assert slot is not None and action is not None
        ctx.select_slot(slot["slot_id"])
        return ask(
            ctx,
            QuestionId.SLOT_READBACK,
            t.slot_readback(ctx, slot, action, variant=t.choose_variant(ctx, "SLOT_READBACK")),
            "AWAITING_CONFIRMATION",
            action=action,
            slot_id=slot["slot_id"],
        )

    def _refuse_slots(self, ctx: CallContext, ex: ExtractionResult, now: datetime) -> Reply:
        """Q-4: chỉ bỏ đổi / đặt khi người gọi nói rõ ("thôi không đổi nữa", "giữ lịch cũ").

        "không" trần không được đoán (§1.1.5): còn khung thì hỏi A/B, hết khung thì hỏi ngày khác.
        """
        if gives_up_slot_change(ex.transcript):
            return self._give_up(ctx)
        if not self._unoffered(ctx, now):
            return self._slots_exhausted(ctx)
        action = ctx.pending_action
        assert action is not None
        return Reply(
            ask(
                ctx,
                QuestionId.SLOT_REFUSE_CHOICE,
                t.SLOT_REFUSE_CHOICE[action],
                "OFFERING_SLOTS",
                action=action,
            ),
            "UNCLEAR",
        )

    def _slots_exhausted(self, ctx: CallContext, taken: bool = False) -> Reply:
        """Đã đọc / bị từ chối hết khung của yêu cầu: hỏi ngày khác, vẫn giữ việc đổi / đặt (§3.2).

        Đã nêu đủ 2 ngày thì không hỏi ngày thứ ba: giữ lịch cũ, chuyển máy (§3.2 c).
        `taken`: khung vừa chốt có người đặt (G-7) — câu nói phải báo điều đó.
        """
        if ctx.slot_round >= MAX_SLOT_ROUNDS:
            return self._rounds_exhausted(ctx, taken)
        action = ctx.pending_action
        assert action is not None
        ctx.select_slot(None)
        ctx.presented_slot_ids = []
        return Reply(
            ask(
                ctx,
                QuestionId.ASK_SLOT_PREFERENCE,
                (t.SLOT_TAKEN_EXHAUSTED if taken else t.SLOT_EXHAUSTED)[action],
                "AWAITING_INTENT",
                action=action,
            )
        )

    def _ask_date_again(self, ctx: CallContext, criteria: SlotCriteria) -> Reply:
        """R-30: ngày đã qua / không tồn tại / quá rộng / trùng hôm nay -> nói lý do, hỏi lại ngày.

        Không tính vòng. D-6: lần đầu không tính §1.1.5, lần thứ hai liên tiếp mới tính (UNCLEAR).
        """
        action = ctx.pending_action
        assert action is not None and criteria.date_issue is not None
        ctx.select_slot(None)
        ctx.presented_slot_ids = []
        text = t.ask_date_again(ctx, criteria.date_issue, action, criteria.date_from)
        return Reply(
            ask(ctx, QuestionId.ASK_SLOT_PREFERENCE, text, "AWAITING_INTENT", action=action),
            "UNCLEAR",
        )

    def _give_up(self, ctx: CallContext) -> Reply:
        """ "Thôi không đổi nữa": vòng 0–1 giữ lịch cũ, hội thoại tiếp tục; vòng 2 chuyển máy (§3.2 d)."""
        if ctx.slot_round >= MAX_SLOT_ROUNDS:
            return self._rounds_exhausted(ctx)
        return self._abandon(ctx)

    def _rounds_exhausted(self, ctx: CallContext, taken: bool = False) -> Reply:
        """Hết 2 vòng (R-29, GC-RES-05): lịch cũ giữ nguyên, không ghi gì, chuyển PATIENT_REQUEST."""
        ctx.clear_pending()
        text = t.SLOT_TAKEN_ROUNDS_TRANSFER if taken else t.ROUNDS_EXHAUSTED_TRANSFER
        return Reply(self.transfer(ctx, "PATIENT_REQUEST", text))

    def _not_understood(
        self,
        ctx: CallContext,
        question_id: Optional[QuestionId] = None,
        text: str = t.NOT_UNDERSTOOD,
    ) -> Reply:
        if question_id is not None:
            # Hỏi lại cùng một câu hỏi danh tính bằng lời khác
            return Reply(ask(ctx, question_id, text, ctx.state), "NOT_UNDERSTOOD")
        return Reply(BotAction(t.choose_static(ctx, text), ctx.state), "NOT_UNDERSTOOD")

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
    def _finish(outcome: Outcome, text: str) -> BotAction:
        return BotAction(text, "ENDED", ended=True, outcome=outcome)


def _criteria(request: str, now: datetime) -> SlotCriteria:
    """Tiêu chí lọc của một yêu cầu thời gian; thứ tự ("khung 2") chỉ có nghĩa trên trang đang đọc.

    Thứ trần quy về tuần này theo R-30 ("thứ Sáu" = thứ Sáu tuần này).
    """
    return resolve_request(replace(parse_slot_criteria(request, now), ordinal=None), now)


def _busy(transcript: str) -> bool:
    """ "bận", "không đi được giờ này": không nhận khung vừa đọc. Có "hủy" thì để nhánh hủy xử lý."""
    return mentions_busy(transcript) and not mentions_cancel(transcript)


def _mentioned_slot_ids(choice: Optional[SlotChoice]) -> list[str]:
    """Các khung câu nói nhắc tới ("10 giờ rưỡi", "buổi chiều", "khung 1") trong các khung đã tải."""
    if choice is None or choice.kind not in ("MATCH", "AMBIGUOUS"):
        return []
    return list(choice.slot_ids)


def _refuse(ctx: CallContext, slot_ids: list[str]) -> None:
    for slot_id in slot_ids:
        if slot_id not in ctx.refused_slot_ids:
            ctx.refused_slot_ids.append(slot_id)


def _pickable(ctx: CallContext) -> set[str]:
    """Khung chọn thẳng được: đã đọc cho yêu cầu hiện tại (trang này hoặc trang trước), chưa bị từ chối."""
    return {*ctx.presented_slot_ids, *ctx.offered_slot_ids} - set(ctx.refused_slot_ids)


def _picked(ctx: CallContext, choice: Optional[SlotChoice]) -> Optional[str]:
    """Khung người gọi chọn trong các khung đã đọc.

    IE khớp trên mọi khung đã tải, nên MATCH một khung chưa đọc ("8 giờ sáng ngày 20" khi đang đọc
    ngày 15) hay đã từ chối là yêu cầu thời gian mới, không phải chọn: phải qua `_new_request` để tính
    vòng (R-29), quy thứ trần (R-30) và bỏ khung đã từ chối (V-9).
    """
    if choice is None or choice.kind != "MATCH":
        return None
    return choice.slot_id if choice.slot_id in _pickable(ctx) else None


def _weekday_off_page(choice: SlotChoice, presented: list[str]) -> bool:
    """Có thứ, không nêu ngày, và không khung khớp nào nằm trong trang vừa đọc."""
    return (
        choice.kind in ("MATCH", "AMBIGUOUS")
        and choice.criteria.weekday is not None
        and not _names_a_date(choice.criteria)
        and not set(choice.slot_ids) & set(presented)
    )


def _names_a_date(criteria: SlotCriteria) -> bool:
    """Câu nêu ngày / khoảng ngày (không chỉ giờ, buổi, thứ): là yêu cầu thời gian mới."""
    return any(
        value is not None
        for value in (criteria.day, criteria.month, criteria.date_from, criteria.date_issue)
    )


def _dates_only(criteria: SlotCriteria) -> SlotCriteria:
    """Chỉ phần ngày của yêu cầu: ngày xin còn khung nào không, bất kể giờ / buổi."""
    return replace(criteria, hours=None, minute=None, period=None)


def _more_prefix(ex: ExtractionResult) -> str:
    """ "Cho xem 4 khung khác": vẫn đọc tối đa 2 khung (R-25) và nói lý do, không lẳng lặng cắt bớt."""
    count = requested_slot_count(ex.transcript)
    return t.SLOT_TWO_AT_A_TIME if count is not None and count > MAX_SLOTS_PRESENTED else ""


def _new_time_request(criteria: SlotCriteria) -> bool:
    """Câu có tiêu chí thời gian (ngày, thứ, buổi, giờ), không chỉ thứ tự trong trang đang đọc."""
    return not replace(criteria, ordinal=None).empty
