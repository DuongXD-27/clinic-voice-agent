"""Điều phối một lượt: Session -> Policy -> Extraction -> Policy -> Dialogue -> Policy -> Session.

SessionManager lo khóa, thứ tự lượt, replay và commit; orchestrator chỉ xử lý nội dung lượt.
Trace xuất SAU khi commit: lỗi trace không làm lượt đã commit chạy lại.

R-01: mọi câu bot nói — kể cả lời mở đầu, câu fallback và câu thay thế — đi qua Output Guard ở đây,
trước commit. HTTP và LiveKit cùng gọi orchestrator nên dùng chung đúng một chốt kiểm tra đầu ra;
lượt replay trả lại action đã được guard lúc commit.
"""

import logging
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional, Protocol, TypeVar

from callbot.engine.diagnostics import build_diagnostics
from callbot.engine.dialogue import templates as t
from callbot.engine.dialogue.manager import DialogueManager, Reply
from callbot.engine.errors import (
    TURN_ABORTING_ERRORS,
    CallStartBlocked,
    EngineError,
    WriteOutcomeUnknown,
)
from callbot.engine.extraction.extractor import InformationExtractor
from callbot.engine.extraction.schema import ExtractionResult, QuestionId, TurnContext, to_local
from callbot.engine.journal import turn_entries
from callbot.engine.policy import output_guard
from callbot.engine.policy.guardrails import SevereFailureBlocked
from callbot.engine.policy.output_guard import GuardInput, GuardVerdict, Receipt
from callbot.engine.policy.policy_engine import (
    LOOKUP_TRANSFER_REASON,
    PolicyDecision,
    PolicyEngine,
)
from callbot.engine.policy.sources import SourceRegistry, bind_sources
from callbot.engine.policy.utterances import RenderRecord, bind_ledger
from callbot.engine.session.context import CallContext, Question
from callbot.engine.session.manager import SessionManager, TurnOutcome, TurnRun
from callbot.engine.types import BotAction, CallerInput, CallStart
from callbot.tracing import SpanHandle, current_span, null_tracer, trace_event
from callbot.tracing import Tracer as SpanTracer
from callbot.tracing.errors import classify_guardrail

logger = logging.getLogger(__name__)
T = TypeVar("T", BotAction, Reply)


@dataclass
class _TurnOutput:
    """Dữ liệu Output Guard đối chiếu, chụp ở ĐẦU lượt trước khi Dialogue chạy."""

    prior_question: Optional[Question]
    sources: SourceRegistry
    ledger: list[RenderRecord] = field(default_factory=list)


def _transfer_system_error() -> BotAction:
    """Hằng cuối cùng khi cả câu fallback cũng không qua guard — không đệ quy, không ghi thêm."""
    return BotAction(
        t.TRANSFER, "ENDED", ended=True, outcome="TRANSFERRED", transfer_reason="SYSTEM_ERROR"
    )


def _lookup_transfer_text(ctx: CallContext, decision: PolicyDecision) -> Optional[str]:
    """Inbound tra hồ sơ theo số không được: lượt 1 chuyển máy kèm lý do (§1.1.9).

    Chỉ khi chính kết quả tra cứu sinh ra quyết định chuyển máy, chưa hỏi danh tính nên không lộ gì.
    """
    if ctx.call.direction != "inbound" or ctx.identity_verified:
        return None
    if decision.transfer_reason != LOOKUP_TRANSFER_REASON.get(ctx.identity_lookup):
        return None
    return t.LOOKUP_TRANSFER.get(ctx.identity_lookup)


class Tracer(Protocol):
    """callbot.tracing.JsonlLogger thoả mãn Protocol này."""

    def log(self, call_id: str, turn: int, event: dict[str, Any]) -> None: ...


def _value(value: object) -> object:
    return value.value if isinstance(value, Enum) else value


def _question(ctx: CallContext) -> str | None:
    try:
        return ctx.question.question_id.value if ctx.question is not None else None
    except Exception:
        logger.warning("TRACE_QUESTION_METADATA_REJECTED")
        return None


def _extraction_attributes(extraction: ExtractionResult) -> dict[str, object]:
    from datetime import date

    dob = extraction.dob
    dob_classification = (
        "INVALID"
        if dob.value == "INVALID"
        else "PRESENT"
        if isinstance(dob.value, date)
        else "NONE"
    )
    choice = extraction.slot_choice.value
    return {
        "question_id": extraction.question_id.value if extraction.question_id else None,
        "silent": extraction.silent,
        "full_name_presence": extraction.full_name.found,
        "full_name_provenance": extraction.full_name.provenance.value,
        "dob_classification": dob_classification,
        "dob_provenance": dob.provenance.value,
        "intent_label": _value(extraction.intent.value),
        "intent_provenance": extraction.intent.provenance.value,
        "agreement_label": _value(extraction.agreement.value),
        "agreement_provenance": extraction.agreement.provenance.value,
        "clinical_label": _value(extraction.clinical.value),
        "clinical_provenance": extraction.clinical.provenance.value,
        "cancel_reason_label": _value(extraction.cancel_reason.value),
        "cancel_reason_provenance": extraction.cancel_reason.provenance.value,
        "line_signal_label": _value(extraction.line_signal.value),
        "line_signal_provenance": extraction.line_signal.provenance.value,
        "slot_choice_kind": choice.kind if choice is not None else None,
        "candidate_count": len(choice.slot_ids) if choice is not None else 0,
    }


def build_turn_context(
    ctx: CallContext, turn: int, received_at: datetime, asr_confidence: Optional[float] = None
) -> TurnContext:
    """Những gì IE được biết (nguyên tắc 2): KHÔNG có hồ sơ bệnh nhân, tên / ngày sinh, `verify.*`."""
    question = ctx.question
    return TurnContext(
        turn=turn,
        question_id=question.question_id if question else None,
        direction=ctx.call.direction,
        now=to_local(received_at),
        asr_confidence=asr_confidence,
        slots=tuple(dict(slot) for slot in ctx.slots),
        presented_slot_ids=tuple(ctx.presented_slot_ids),
        pending_action=ctx.pending_action,
        question_turn=question.turn if question else None,
        # Câu bot thật sự đã nói (kể cả sau nhắc im lặng / chưa hiểu); các câu hỏi khác không cần
        question_text=(
            question.text
            if question and question.question_id is QuestionId.ASK_NAME and question.text
            else None
        ),
    )


class CallOrchestrator:
    def __init__(
        self,
        sessions: SessionManager,
        extractor: InformationExtractor,
        policy: PolicyEngine,
        dialogue: DialogueManager,
        tracer: Optional[Tracer] = None,
    ) -> None:
        self._sessions = sessions
        self._extractor = extractor
        self._policy = policy
        self._dialogue = dialogue
        self._tracer = tracer
        self._span_tracer = tracer if isinstance(tracer, SpanTracer) else null_tracer()

    @property
    def sessions(self) -> SessionManager:
        return self._sessions

    @property
    def tracer(self) -> SpanTracer:
        return self._span_tracer

    def start_call(self, call: CallStart) -> BotAction:
        with self._span_tracer.span(component="CORE", operation="core.start_call") as core:
            action, replayed = self._sessions.open(call, self._opening)
            core.enrich(
                state_after=action.state,
                outcome=action.outcome,
                replayed=replayed,
                dialogue_action=self._trace_dialogue_action(action, None),
            )
            core.enrich_ancestor("TURN", replayed=replayed)
        if not replayed:
            self._trace(
                call.call_id,
                0,
                {"event": "call_started", "direction": call.direction, "state": action.state},
            )
        return action

    def _opening(self, ctx: CallContext) -> BotAction:
        """Lời mở đầu qua Output Guard TRƯỚC khi SessionManager tạo phiên (R-01 §3.7).

        Bước mở đầu không có nhật ký lệnh và không đặt chỗ lượt, nên không bao giờ chuyển máy hay ghi
        Clinic: bị chặn thì không tạo phiên, không nói gì — gửi lại cùng `call_id` sau khi sửa lỗi.
        """
        root = current_span()
        if root is not None:
            root.enrich(direction=ctx.call.direction)
        action = self._dialogue_step(ctx, self._dialogue.opening)
        with self._span_tracer.span(component="GUARD", operation="core.output_guard") as span:
            verdict = output_guard.check_opening(action, ctx)
            if verdict.ok:
                span.enrich(guard_verdict="PASS", render_count=0)
                return action
            self._trace_guard_block(span, verdict)
        assert verdict.code is not None
        logger.error("Output Guard chặn lời mở đầu %s (%s)", ctx.call_id, verdict.rule)
        raise CallStartBlocked(verdict.code)

    def handle_turn(self, call_id: str, caller: CallerInput) -> BotAction:
        return self.handle_turn_with_details(call_id, caller).action

    def handle_turn_with_details(
        self,
        call_id: str,
        caller: CallerInput,
        *,
        resolve_input: Optional[Callable[[], CallerInput]] = None,
    ) -> TurnRun:
        """Run a turn and retain its extraction trace for transport-level diagnostics."""
        with self._span_tracer.span(component="CORE", operation="core.handle_turn") as core:
            run = self._sessions.run_turn(
                call_id, caller, self._process, resolve_input=resolve_input
            )
            core.enrich(
                state_after=run.action.state,
                outcome=run.action.outcome,
                replayed=run.replayed,
                silent=caller.is_silence,
                dialogue_action=self._trace_dialogue_action(run.action, None),
            )
            core.enrich_ancestor("TURN", replayed=run.replayed)
        if not run.replayed:
            self._trace(
                call_id,
                caller.turn,
                {
                    "event": "turn",
                    "state": run.action.state,
                    "outcome": run.action.outcome,
                    "transfer_reason": run.action.transfer_reason,
                    "unreachable_reason": run.action.unreachable_reason,
                },
            )
        return run

    def _process(self, ctx: CallContext, caller: CallerInput, received_at: datetime) -> TurnOutcome:
        """Kiểm tra preconditions -> extract -> policy / dialogue.

        `extraction` nằm ở scope này (vẫn trong `try`): lỗi xảy ra SAU khi trích vẫn giữ được kết quả đã
        trích cho trace và chẩn đoán. Preconditions chặn lượt, hoặc extractor chưa xong, thì là None.
        """
        core = current_span()
        state_before = ctx.state
        if core is not None and core.component == "CORE":
            core.enrich(state_before=state_before, silent=caller.is_silence)
            core.enrich_ancestor("TURN", direction=ctx.call.direction, state_before=state_before)
        ctx.turn = caller.turn
        ctx.business_write_blocked = False
        ctx.record("caller", caller.transcript)
        # R-01: chụp đầu lượt (deepcopy) — câu hỏi đang chờ và slot vừa nạp từ store
        turn = _TurnOutput(deepcopy(ctx.question), SourceRegistry(ctx.slots))
        extraction: Optional[ExtractionResult] = None
        action: Optional[BotAction] = None
        handled: Optional[Exception] = None
        with bind_sources(turn.sources), bind_ledger(turn.ledger):
            try:
                decision = self._policy.check_preconditions(ctx)
                self._policy_event("preconditions", decision)
                if decision.kind != "CONTINUE":
                    action = self._execute(ctx, decision, _lookup_transfer_text(ctx, decision))
                elif caller.phone_status is not None:
                    decision = self._policy.check_phone_status(ctx, caller.phone_status)
                    self._policy_event("phone_status", decision)
                    action = self._execute(ctx, decision)
                else:
                    with self._span_tracer.span(
                        component="EXTRACTION", operation="core.extract"
                    ) as span:
                        extraction = self._extractor.extract(
                            build_turn_context(
                                ctx, caller.turn, received_at, caller.asr_confidence
                            ),
                            caller.transcript,
                            silence_ms=caller.silence_ms,
                        )
                        ctx.business_write_blocked = extraction.model_failed
                        try:
                            span.enrich(**_extraction_attributes(extraction))
                        except Exception:
                            logger.warning("TRACE_EXTRACTION_METADATA_REJECTED")
                    action = self._decide(ctx, extraction, received_at)
            except TURN_ABORTING_ERRORS as exc:
                self._annotate(exc, extraction)
                raise
            except SevereFailureBlocked as blocked:
                self._trace_guardrail(core, blocked.code)
                logger.error("Chặn severe failure %s tại %s", blocked.code, ctx.call_id)
                handled = blocked
            except Exception as exc:
                if core is not None and core.component == "CORE":
                    core.set_error(exc)
                logger.error("Lỗi xử lý lượt %s của %s", caller.turn, ctx.call_id)
                handled = exc
            action, handled = self._settle(ctx, action, handled, extraction, turn)

        self._apply(ctx, action)
        if core is not None and core.component == "CORE":
            core.enrich(
                state_before=state_before,
                state_after=ctx.state,
                outcome=action.outcome,
                dialogue_action=self._trace_dialogue_action(action, _question(ctx)),
                misunderstanding_count=ctx.failed_understandings,
                silence_count=ctx.silent_turns,
                identity_result="MATCH"
                if ctx.identity_verified
                else ctx.identity_result or "UNKNOWN",
            )
            core.enrich_ancestor(
                "TURN", state_after=ctx.state, ended=action.ended, outcome=action.outcome
            )
        trace = extraction.to_trace() if extraction else None
        diagnostics = build_diagnostics(
            trace, transfer_reason=action.transfer_reason, error=handled
        )
        return TurnOutcome(action, trace, diagnostics)

    def _decide(
        self, ctx: CallContext, extraction: ExtractionResult, received_at: datetime
    ) -> BotAction:
        decision = self._policy.check_silence(ctx, extraction)
        self._policy_event("silence", decision)
        if decision.kind == "REPROMPT":
            return self._dialogue_step(ctx, self._dialogue.silence)
        if decision.kind != "CONTINUE":
            return self._execute(ctx, decision)

        decision = self._policy.check_signals(ctx, extraction)
        self._policy_event("signals", decision)
        if decision.kind != "CONTINUE":
            return self._execute(ctx, decision)

        reply = self._dialogue_step(
            ctx, lambda item: self._dialogue.respond(item, extraction, received_at)
        )
        decision = self._policy.register_understanding(ctx, reply.understanding)
        self._policy_event("understanding", decision)
        if decision.kind == "TRANSFER":
            return self._execute(ctx, decision)
        return reply.action

    def _settle(
        self,
        ctx: CallContext,
        action: Optional[BotAction],
        error: Optional[Exception],
        extraction: Optional[ExtractionResult],
        turn: _TurnOutput,
    ) -> tuple[BotAction, Optional[Exception]]:
        """Receipt gate đi trước mọi fallback (R-01 §3.5), rồi Output Guard (§3.6).

        Đã có lệnh ghi thành công thì lỗi sau đó (vd. render câu báo lỗi) không được biến thành chuyển
        máy: báo đúng kết quả đã ghi bằng câu không chi tiết.
        """
        receipt = self._receipt(extraction)
        if error is not None:
            turn.sources.restore_slots(ctx)
            if receipt is not None:
                with self._span_tracer.span(
                    component="GUARD", operation="core.output_guard"
                ) as span:
                    self._trace_writes(span, turn)
                    span.enrich(guard_verdict="REPLACE")
                    return self._replace(ctx, receipt, turn, None), error
            fallback = self._fallback_transfer(ctx, extraction, error, turn)
            guarded, _ = self._guard(ctx, fallback, extraction, turn, fallback=True)
            return guarded, error
        assert action is not None
        guarded, blocked = self._guard(ctx, action, extraction, turn, fallback=False)
        return guarded, blocked

    def _guard(
        self,
        ctx: CallContext,
        action: BotAction,
        extraction: Optional[ExtractionResult],
        turn: _TurnOutput,
        *,
        fallback: bool,
    ) -> tuple[BotAction, Optional[SevereFailureBlocked]]:
        receipt = self._receipt(extraction)
        output_guard.normalize_question(ctx, action)
        with self._span_tracer.span(component="GUARD", operation="core.output_guard") as span:
            verdict = self._check(ctx, action, receipt, turn)
            self._trace_writes(span, turn)
            if receipt is not None:
                if verdict.ok and output_guard.matches_receipt(action, receipt):
                    span.enrich(guard_verdict="PASS")
                    return action, None
                # Đã ghi thành công: cấm chuyển máy / ghi thêm, thay bằng câu báo đúng receipt
                rule = verdict.rule or "OG-5"
                span.enrich(guard_verdict="REPLACE", guard_rule=rule)
                return self._replace(ctx, receipt, turn, rule), None
            if verdict.ok:
                span.enrich(guard_verdict="PASS")
                return action, None
            self._trace_guard_block(span, verdict)
        assert verdict.code is not None
        blocked = SevereFailureBlocked(verdict.code, f"Output Guard {verdict.rule}")
        self._trace_guardrail(current_span(), verdict.code)
        logger.error("Output Guard chặn %s (%s) tại %s", verdict.rule, verdict.code, ctx.call_id)
        # Fallback không giữ trạng thái đang vi phạm: khôi phục slot gốc, chuẩn hóa rồi mới kiểm lại
        turn.sources.restore_slots(ctx)
        replacement = (
            _transfer_system_error()
            if fallback
            else self._fallback_transfer(ctx, extraction, blocked, turn)
        )
        receipt = self._receipt(extraction)
        output_guard.normalize_question(ctx, replacement)
        if receipt is not None:
            if not (
                self._check(ctx, replacement, receipt, turn).ok
                and output_guard.matches_receipt(replacement, receipt)
            ):
                replacement = self._replace(ctx, receipt, turn, verdict.rule or "OG-5")
        elif not self._check(ctx, replacement, None, turn).ok:
            replacement = _transfer_system_error()
        return replacement, blocked

    def _fallback_transfer(
        self,
        ctx: CallContext,
        extraction: Optional[ExtractionResult],
        error: Exception,
        turn: _TurnOutput,
    ) -> BotAction:
        """Chuyển máy SYSTEM_ERROR; lỗi thường xảy ra SAU khi /transfer đã ghi thành công không được làm
        mất kết quả đó (receipt gate áp cả cho fallback).

        Lỗi chặn lượt (TURN_ABORTING_ERRORS) giữ nguyên đường đối soát. Chưa có lệnh thành công thì lỗi
        đi tiếp như trước; còn lệnh chưa rõ kết quả thì `_receipt` chặn đối soát.
        """
        try:
            return self._transfer_after_error(ctx, extraction, error)
        except TURN_ABORTING_ERRORS:
            raise
        except Exception:
            receipt = self._receipt(extraction)
            if receipt is None:
                raise
            logger.error(
                "Lỗi sau khi ghi %s tại %s, giữ kết quả đã ghi", receipt.outcome, ctx.call_id
            )
            return self._replace(ctx, receipt, turn, None)

    def _replace(
        self, ctx: CallContext, receipt: Receipt, turn: _TurnOutput, rule: Optional[str]
    ) -> BotAction:
        """`rule` là luật guard đã trượt; None khi thay vì lỗi xử lý sau lệnh ghi thành công."""
        safe = output_guard.safe_action(receipt)
        turn.sources.restore_slots(ctx)
        output_guard.normalize_question(ctx, safe)
        trace_event(
            "output_guard.replaced",
            guard_rule=rule,
            outcome=receipt.outcome,
            write_operation=receipt.command.operation,
        )
        if not self._check(ctx, safe, receipt, turn).ok:
            # Hằng DONE_SAFE vẫn được dùng: không đệ quy, không chuyển máy sau khi đã ghi thành công
            logger.error(
                "Câu thay thế %s không qua Output Guard tại %s", receipt.outcome, ctx.call_id
            )
        return safe

    @staticmethod
    def _check(
        ctx: CallContext, action: BotAction, receipt: Optional[Receipt], turn: _TurnOutput
    ) -> GuardVerdict:
        return output_guard.check(
            GuardInput(action, ctx, turn.prior_question, turn.ledger, turn.sources, receipt)
        )

    def _receipt(self, extraction: Optional[ExtractionResult]) -> Optional[Receipt]:
        try:
            return output_guard.receipt_gate(turn_entries())
        except WriteOutcomeUnknown as exc:
            # Không gọi _transfer_after_error: chuyển máy là một lệnh ghi mới
            self._annotate(exc, extraction)
            raise

    @staticmethod
    def _trace_writes(span: SpanHandle, turn: _TurnOutput) -> None:
        writes = output_guard.summarize_writes(turn_entries())
        span.enrich(
            render_count=len(turn.ledger),
            write_attempted=writes.attempted,
            write_succeeded=writes.succeeded,
            write_operation=writes.operation,
            write_status_match=writes.status_match,
        )

    @staticmethod
    def _trace_guard_block(span: SpanHandle, verdict: GuardVerdict) -> None:
        assert verdict.code is not None
        error = classify_guardrail(verdict.code)
        span.enrich(guard_verdict="BLOCK", guard_rule=verdict.rule)
        span.set_error_code(error.error_type, error.error_code)
        span.event(
            "output_guard.blocked",
            guard_rule=verdict.rule,
            error_type=error.error_type,
            error_code=error.error_code,
        )

    @staticmethod
    def _trace_guardrail(core: Optional[SpanHandle], code: str) -> None:
        error = classify_guardrail(code)
        trace_event(
            "guardrail.blocked",
            status="ERROR",
            error_type=error.error_type,
            error_code=error.error_code,
        )
        if core is not None and core.component == "CORE":
            core.set_error_code(error.error_type, error.error_code)
            core.enrich(guardrail_code=error.error_code)

    def _transfer_after_error(
        self, ctx: CallContext, extraction: Optional[ExtractionResult], error: Exception
    ) -> BotAction:
        """Lỗi nghiệp vụ -> chuyển máy SYSTEM_ERROR; chỉ báo TRANSFERRED khi /transfer thành công."""
        try:
            return self._dialogue_step(
                ctx, lambda item: self._dialogue.transfer(item, "SYSTEM_ERROR")
            )
        except EngineError as exc:
            self._annotate(exc, extraction, transfer_reason="SYSTEM_ERROR")
            raise

    @staticmethod
    def _annotate(
        error: BaseException,
        extraction: Optional[ExtractionResult],
        transfer_reason: Optional[str] = None,
    ) -> None:
        """Gắn chẩn đoán không PII vào exception có kiểu để transport vẫn trả được extraction."""
        if not isinstance(error, EngineError) or error.diagnostics is not None:
            return
        reason = transfer_reason or error.transfer_reason
        trace = extraction.to_trace() if extraction else None
        error.extraction = trace
        error.diagnostics = build_diagnostics(trace, transfer_reason=reason, error=error)

    def _execute(
        self, ctx: CallContext, decision: PolicyDecision, text: Optional[str] = None
    ) -> BotAction:
        if decision.kind == "UNREACHABLE" and decision.unreachable_reason:
            return self._dialogue_step(
                ctx, lambda item: self._dialogue.unreachable(item, decision.unreachable_reason)
            )
        reason = decision.transfer_reason or "SYSTEM_ERROR"
        if text is None:
            return self._dialogue_step(ctx, lambda item: self._dialogue.transfer(item, reason))
        return self._dialogue_step(ctx, lambda item: self._dialogue.transfer(item, reason, text))

    def _policy_event(self, stage: str, decision: PolicyDecision) -> None:
        reason = decision.transfer_reason or decision.unreachable_reason
        trace_event("policy.decision", stage=stage, decision=decision.kind, decision_reason=reason)
        core = current_span()
        if core is not None and core.component == "CORE":
            core.enrich(decision=decision.kind, decision_reason=reason)

    def _dialogue_step(self, ctx: CallContext, operation: Callable[[CallContext], T]) -> T:
        state_before = ctx.state
        question_before = _question(ctx)
        with self._span_tracer.span(component="DIALOGUE", operation="core.dialogue") as span:
            result = operation(ctx)
            action = result.action if isinstance(result, Reply) else result
            question_after = _question(ctx)
            span.enrich(
                state_before=state_before,
                state_after=action.state,
                question_before=question_before,
                question_after=question_after,
                dialogue_action=self._trace_dialogue_action(action, question_after),
                understanding=result.understanding if isinstance(result, Reply) else None,
                outcome=action.outcome,
            )
            return result

    @staticmethod
    def _dialogue_action(action: BotAction, question: str | None) -> str:
        if action.transfer_reason is not None:
            return "TRANSFER"
        if action.ended and action.outcome is not None:
            return f"END_{action.outcome}"
        return question or "RESPOND"

    def _trace_dialogue_action(self, action: BotAction, question: str | None) -> str | None:
        try:
            return self._dialogue_action(action, question)
        except Exception:
            logger.warning("TRACE_DIALOGUE_METADATA_REJECTED")
            return None

    def _apply(self, ctx: CallContext, action: BotAction) -> None:
        """Mọi thay đổi state, kể cả kết thúc phiên, đi qua FSM."""
        ctx.record("bot", action.utterance)
        if action.ended:
            assert action.outcome is not None
            self._sessions.close(
                ctx, action.outcome, action.transfer_reason, action.unreachable_reason
            )
        else:
            self._sessions.transition(ctx, action.state)

    def _trace(self, call_id: str, turn: int, event: dict[str, Any]) -> None:
        if self._tracer is None or isinstance(self._tracer, SpanTracer):
            return
        try:
            self._tracer.log(call_id, turn, event)
        except Exception:
            logger.error("Xuất trace lỗi cho %s lượt %s", call_id, turn)
