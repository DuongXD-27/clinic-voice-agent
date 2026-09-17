"""AI Callbot Engine: Session Manager, Information Extraction, Policy, Verification, Dialogue & LLM."""

from typing import Optional

from callbot.engine.dialogue import DialogueManager
from callbot.engine.dialogue.llm import create_llm
from callbot.engine.errors import (
    CallBusy,
    CallConflict,
    CallEnded,
    ReconciliationRequired,
    SessionNotFound,
    SessionStoreUnavailable,
    TurnConflict,
    TurnOutOfOrder,
)
from callbot.engine.extraction import InformationExtractor
from callbot.engine.orchestrator import CallOrchestrator, Tracer
from callbot.engine.policy import PolicyEngine
from callbot.engine.session import InMemorySessionStore, SessionManager, SessionStore
from callbot.engine.settings import EngineSettings
from callbot.engine.tools import ClinicAPI, ClinicGateway
from callbot.engine.types import BotAction, CallerInput, CallStart
from callbot.engine.verification import IdentityVerifier


def create_orchestrator(
    clinic_api: ClinicAPI,
    settings: Optional[EngineSettings] = None,
    tracer: Optional[Tracer] = None,
    store: Optional[SessionStore] = None,
) -> CallOrchestrator:
    """`store=None` dùng bộ nhớ process — chỉ cho test / công cụ một process.

    Ứng dụng HTTP luôn truyền PostgreSQL store (transports/http/main.py).
    """
    settings = settings or EngineSettings()
    gateway = ClinicGateway(clinic_api, clinic_id=settings.clinic_id)
    return CallOrchestrator(
        sessions=SessionManager(store if store is not None else InMemorySessionStore()),
        # LLM fallback chưa bật (F-04): chỉ tầng luật
        extractor=InformationExtractor(),
        policy=PolicyEngine(settings),
        dialogue=DialogueManager(gateway, IdentityVerifier(gateway), llm=create_llm(settings)),
        tracer=tracer,
    )


__all__ = [
    "BotAction",
    "CallBusy",
    "CallConflict",
    "CallEnded",
    "CallOrchestrator",
    "CallStart",
    "CallerInput",
    "ClinicAPI",
    "EngineSettings",
    "InMemorySessionStore",
    "ReconciliationRequired",
    "SessionNotFound",
    "SessionStore",
    "SessionStoreUnavailable",
    "TurnConflict",
    "TurnOutOfOrder",
    "create_orchestrator",
]
