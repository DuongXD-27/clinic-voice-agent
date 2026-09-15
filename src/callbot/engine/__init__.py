"""AI Callbot Engine: Session Manager, NLU, Policy, Verification, Dialogue Manager & LLM."""

from typing import Optional

from callbot.engine.dialogue import DialogueManager
from callbot.engine.dialogue.llm import create_llm
from callbot.engine.nlu import InformationExtractor, RuleBasedParser
from callbot.engine.orchestrator import CallOrchestrator, Tracer
from callbot.engine.policy import PolicyEngine
from callbot.engine.session import InMemorySessionRepository, SessionManager, SessionNotFound
from callbot.engine.settings import EngineSettings
from callbot.engine.tools import ClinicAPI, ClinicGateway
from callbot.engine.types import BotAction, CallerInput, CallStart
from callbot.engine.verification import IdentityVerifier


def create_orchestrator(
    clinic_api: ClinicAPI,
    settings: Optional[EngineSettings] = None,
    tracer: Optional[Tracer] = None,
) -> CallOrchestrator:
    settings = settings or EngineSettings()
    gateway = ClinicGateway(clinic_api, clinic_id=settings.clinic_id)
    return CallOrchestrator(
        sessions=SessionManager(InMemorySessionRepository()),
        extractor=InformationExtractor(RuleBasedParser()),
        policy=PolicyEngine(settings),
        dialogue=DialogueManager(gateway, IdentityVerifier(gateway), llm=create_llm(settings)),
        tracer=tracer,
    )


__all__ = [
    "BotAction",
    "CallOrchestrator",
    "CallStart",
    "CallerInput",
    "ClinicAPI",
    "EngineSettings",
    "SessionNotFound",
    "create_orchestrator",
]
