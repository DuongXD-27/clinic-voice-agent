"""Điều phối một lượt: Session -> Policy -> NLU -> Dialogue -> Policy -> Session."""

import logging
from dataclasses import asdict
from typing import Any, Optional, Protocol

from callbot.engine.dialogue.manager import DialogueManager
from callbot.engine.dialogue.templates import CLOSED
from callbot.engine.nlu.extractor import InformationExtractor
from callbot.engine.policy.guardrails import SevereFailureBlocked
from callbot.engine.policy.policy_engine import PolicyDecision, PolicyEngine
from callbot.engine.session.context import CallContext
from callbot.engine.session.manager import SessionManager
from callbot.engine.types import BotAction, CallerInput, CallStart

logger = logging.getLogger(__name__)


class Tracer(Protocol):
    """callbot.tracing.JsonlLogger thoả mãn Protocol này."""

    def log(self, call_id: str, turn: int, event: dict[str, Any]) -> None: ...


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

    def start_call(self, call: CallStart) -> BotAction:
        ctx = self._sessions.open(call)
        action = self._dialogue.opening(ctx)
        ctx.record("bot", action.utterance)
        self._trace(ctx, {"event": "call_started", "call": asdict(call), "bot": action.utterance})
        return action

    def handle_turn(self, call_id: str, caller: CallerInput) -> BotAction:
        ctx = self._sessions.get(call_id)
        if ctx.ended:
            return BotAction(CLOSED, "ENDED", ended=True, outcome=ctx.outcome)

        ctx.turn = caller.turn
        ctx.record("caller", caller.text)
        nlu = None
        try:
            nlu, action = self._decide(ctx, caller)
        except SevereFailureBlocked as blocked:
            logger.error("Chặn severe failure %s tại %s", blocked.code, call_id)
            self._trace(ctx, {"event": "severe_failure_blocked", "code": blocked.code, "detail": str(blocked)})
            action = self._dialogue.transfer(ctx, "SYSTEM_ERROR")
        except Exception as exc:
            logger.exception("Lỗi xử lý lượt %s của %s", caller.turn, call_id)
            self._trace(ctx, {"event": "error", "detail": repr(exc)})
            action = self._dialogue.transfer(ctx, "SYSTEM_ERROR")

        self._apply(ctx, action)
        self._trace(
            ctx,
            {
                "event": "turn",
                "caller": asdict(caller),
                "intent": nlu.intent.value if nlu else None,
                "state": ctx.state,
                "bot": action.utterance,
                "outcome": action.outcome,
                "transfer_reason": action.transfer_reason,
            },
        )
        return action

    def _decide(self, ctx: CallContext, caller: CallerInput):
        decision = self._policy.check_preconditions(ctx)
        if decision.kind != "CONTINUE":
            return None, self._execute(ctx, decision)

        decision = self._policy.check_silence(ctx, caller)
        if decision.kind != "CONTINUE":
            return None, self._execute(ctx, decision, silence=True)

        nlu = self._extractor.extract(ctx, caller.text)
        decision = self._policy.check_exceptions(nlu)
        if decision.kind != "CONTINUE":
            return nlu, self._execute(ctx, decision)

        action = self._dialogue.respond(ctx, nlu)
        decision = self._policy.register_understanding(ctx, understood=action is not None)
        if action is None:
            action = self._execute(ctx, decision)
        return nlu, action

    def _execute(self, ctx: CallContext, decision: PolicyDecision, silence: bool = False) -> BotAction:
        if decision.kind == "TRANSFER":
            return self._dialogue.transfer(ctx, decision.transfer_reason or "SYSTEM_ERROR")
        if decision.kind == "UNREACHABLE":
            return self._dialogue.unreachable(ctx)
        return self._dialogue.reprompt(ctx, silence=silence)

    def _apply(self, ctx: CallContext, action: BotAction) -> None:
        ctx.record("bot", action.utterance)
        if action.ended and action.outcome:
            self._sessions.close(ctx, action.outcome)
        else:
            self._sessions.transition(ctx, action.state)
            self._sessions.save(ctx)

    def _trace(self, ctx: CallContext, event: dict[str, Any]) -> None:
        if self._tracer is not None:
            self._tracer.log(ctx.call_id, ctx.turn, event)
