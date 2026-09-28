"""Điều phối một lượt: Session -> Policy -> Extraction -> Policy -> Dialogue -> Policy -> Session.

SessionManager lo khóa, thứ tự lượt, replay và commit; orchestrator chỉ xử lý nội dung lượt.
Trace xuất SAU khi commit: lỗi trace không làm lượt đã commit chạy lại.
"""

import logging
from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import Any, Optional, Protocol, TypeVar

from callbot.engine.diagnostics import build_diagnostics
from callbot.engine.dialogue.manager import DialogueManager, Reply
from callbot.engine.errors import TURN_ABORTING_ERRORS, EngineError
from callbot.engine.extraction.extractor import InformationExtractor
from callbot.engine.extraction.schema import ExtractionResult, QuestionId, TurnContext, to_local
from callbot.engine.policy.guardrails import SevereFailureBlocked
from callbot.engine.policy.policy_engine import PolicyDecision, PolicyEngine
from callbot.engine.session.context import CallContext
from callbot.engine.session.manager import SessionManager, TurnOutcome, TurnRun
from callbot.engine.types import BotAction, CallerInput, CallStart
from callbot.tracing import Tracer as SpanTracer
from callbot.tracing import current_span, null_tracer, trace_event
from callbot.tracing.errors import classify_guardrail

logger = logging.getLogger(__name__)
T = TypeVar("T", BotAction, Reply)


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


def build_turn_context(ctx: CallContext, turn: int, received_at: datetime) -> TurnContext:
    """Những gì IE được biết (nguyên tắc 2): KHÔNG có hồ sơ bệnh nhân, tên / ngày sinh, `verify.*`."""
    question = ctx.question
    return TurnContext(
        turn=turn,
        question_id=question.question_id if question else None,
        direction=ctx.call.direction,
        now=to_local(received_at),
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
            action, replayed = self._sessions.open(
                call, lambda ctx: self._dialogue_step(ctx, self._dialogue.opening)
            )
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

    def handle_turn(self, call_id: str, caller: CallerInput) -> BotAction:
        return self.handle_turn_with_details(call_id, caller).action

    def handle_turn_with_details(self, call_id: str, caller: CallerInput) -> TurnRun:
        """Run a turn and retain its extraction trace for transport-level diagnostics."""
        with self._span_tracer.span(component="CORE", operation="core.handle_turn") as core:
            run = self._sessions.run_turn(call_id, caller, self._process)
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
        ctx.turn = caller.turn
        ctx.record("caller", caller.transcript)
        extraction: Optional[ExtractionResult] = None
        handled: Optional[Exception] = None
        try:
            decision = self._policy.check_preconditions(ctx)
            self._policy_event("preconditions", decision)
            if decision.kind != "CONTINUE":
                action = self._execute(ctx, decision)
            else:
                with self._span_tracer.span(
                    component="EXTRACTION", operation="core.extract"
                ) as span:
                    extraction = self._extractor.extract(
                        build_turn_context(ctx, caller.turn, received_at),
                        caller.transcript,
                        silence_ms=caller.silence_ms,
                    )
                    try:
                        span.enrich(**_extraction_attributes(extraction))
                    except Exception:
                        logger.warning("TRACE_EXTRACTION_METADATA_REJECTED")
                action = self._decide(ctx, extraction, received_at)
        except TURN_ABORTING_ERRORS as exc:
            self._annotate(exc, extraction)
            raise
        except SevereFailureBlocked as blocked:
            error = classify_guardrail(blocked.code)
            trace_event(
                "guardrail.blocked",
                status="ERROR",
                error_type=error.error_type,
                error_code=error.error_code,
            )
            if core is not None and core.component == "CORE":
                core.set_error_code(error.error_type, error.error_code)
                core.enrich(guardrail_code=error.error_code)
            logger.error("Chặn severe failure %s tại %s", blocked.code, ctx.call_id)
            handled = blocked
            action = self._transfer_after_error(ctx, extraction, blocked)
        except Exception as exc:
            if core is not None and core.component == "CORE":
                core.set_error(exc)
            logger.error("Lỗi xử lý lượt %s của %s", caller.turn, ctx.call_id)
            handled = exc
            action = self._transfer_after_error(ctx, extraction, exc)

        self._apply(ctx, action)
        if core is not None and core.component == "CORE":
            core.enrich(
                state_before=state_before,
                state_after=ctx.state,
                outcome=action.outcome,
                dialogue_action=self._trace_dialogue_action(action, _question(ctx)),
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

    def _execute(self, ctx: CallContext, decision: PolicyDecision) -> BotAction:
        if decision.kind == "UNREACHABLE" and decision.unreachable_reason:
            return self._dialogue_step(
                ctx, lambda item: self._dialogue.unreachable(item, decision.unreachable_reason)
            )
        return self._dialogue_step(
            ctx,
            lambda item: self._dialogue.transfer(item, decision.transfer_reason or "SYSTEM_ERROR"),
        )

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
