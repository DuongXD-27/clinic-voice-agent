"""Điều phối một lượt: Session -> Policy -> Extraction -> Policy -> Dialogue -> Policy -> Session.

SessionManager lo khóa, thứ tự lượt, replay và commit; orchestrator chỉ xử lý nội dung lượt.
Trace xuất SAU khi commit: lỗi trace không làm lượt đã commit chạy lại.
"""

import logging
from datetime import datetime
from typing import Any, Optional, Protocol

from callbot.engine.dialogue.manager import DialogueManager
from callbot.engine.errors import TURN_ABORTING_ERRORS
from callbot.engine.extraction.extractor import InformationExtractor
from callbot.engine.extraction.schema import ExtractionResult, TurnContext, to_local
from callbot.engine.policy.guardrails import SevereFailureBlocked
from callbot.engine.policy.policy_engine import PolicyDecision, PolicyEngine
from callbot.engine.session.context import CallContext
from callbot.engine.session.manager import SessionManager, TurnOutcome
from callbot.engine.types import BotAction, CallerInput, CallStart

logger = logging.getLogger(__name__)


class Tracer(Protocol):
    """callbot.tracing.JsonlLogger thoả mãn Protocol này."""

    def log(self, call_id: str, turn: int, event: dict[str, Any]) -> None: ...


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

    @property
    def sessions(self) -> SessionManager:
        return self._sessions

    def start_call(self, call: CallStart) -> BotAction:
        action, replayed = self._sessions.open(call, self._dialogue.opening)
        if not replayed:
            self._trace(
                call.call_id,
                0,
                {"event": "call_started", "call": call.to_dict(), "bot": action.utterance},
            )
        return action

    def handle_turn(self, call_id: str, caller: CallerInput) -> BotAction:
        run = self._sessions.run_turn(call_id, caller, self._process)
        if not run.replayed:
            self._trace(
                call_id,
                caller.turn,
                {
                    "event": "turn",
                    "caller": caller.fingerprint(),
                    "extraction": run.extraction,
                    "bot": run.action.utterance,
                    "state": run.action.state,
                    "outcome": run.action.outcome,
                    "transfer_reason": run.action.transfer_reason,
                    "unreachable_reason": run.action.unreachable_reason,
                },
            )
        return run.action

    def _process(self, ctx: CallContext, caller: CallerInput, received_at: datetime) -> TurnOutcome:
        ctx.turn = caller.turn
        ctx.record("caller", caller.transcript)
        extraction: Optional[ExtractionResult] = None
        try:
            extraction, action = self._decide(ctx, caller, received_at)
        except TURN_ABORTING_ERRORS:
            raise
        except SevereFailureBlocked as blocked:
            logger.error("Chặn severe failure %s tại %s", blocked.code, ctx.call_id)
            action = self._dialogue.transfer(ctx, "SYSTEM_ERROR")
        except Exception:
            logger.exception("Lỗi xử lý lượt %s của %s", caller.turn, ctx.call_id)
            action = self._dialogue.transfer(ctx, "SYSTEM_ERROR")

        self._apply(ctx, action)
        return TurnOutcome(action, extraction.to_trace() if extraction else None)

    def _decide(
        self, ctx: CallContext, caller: CallerInput, received_at: datetime
    ) -> tuple[Optional[ExtractionResult], BotAction]:
        decision = self._policy.check_preconditions(ctx)
        if decision.kind != "CONTINUE":
            return None, self._execute(ctx, decision)

        extraction = self._extractor.extract(
            build_turn_context(ctx, caller.turn, received_at),
            caller.transcript,
            silence_ms=caller.silence_ms,
        )
        decision = self._policy.check_silence(ctx, extraction)
        if decision.kind == "REPROMPT":
            return extraction, self._dialogue.silence(ctx)
        if decision.kind != "CONTINUE":
            return extraction, self._execute(ctx, decision)

        decision = self._policy.check_signals(ctx, extraction)
        if decision.kind != "CONTINUE":
            return extraction, self._execute(ctx, decision)

        reply = self._dialogue.respond(ctx, extraction, received_at)
        decision = self._policy.register_understanding(ctx, reply.understanding)
        if decision.kind == "TRANSFER":
            return extraction, self._execute(ctx, decision)
        return extraction, reply.action

    def _execute(self, ctx: CallContext, decision: PolicyDecision) -> BotAction:
        if decision.kind == "UNREACHABLE" and decision.unreachable_reason:
            return self._dialogue.unreachable(ctx, decision.unreachable_reason)
        return self._dialogue.transfer(ctx, decision.transfer_reason or "SYSTEM_ERROR")

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
        if self._tracer is None:
            return
        try:
            self._tracer.log(call_id, turn, event)
        except Exception:
            logger.exception("Xuất trace lỗi cho %s lượt %s", call_id, turn)
