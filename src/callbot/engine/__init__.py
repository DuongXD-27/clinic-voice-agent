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
from callbot.engine.extraction.ner import NameNER
from callbot.engine.orchestrator import CallOrchestrator, Tracer
from callbot.engine.policy import PolicyEngine
from callbot.engine.session import RedisSessionStore, SessionManager, SessionStore
from callbot.engine.session.retention import RetentionPolicy
from callbot.engine.session.settings import SessionSettings
from callbot.engine.settings import EngineSettings
from callbot.engine.tools import ClinicAPI, ClinicGateway
from callbot.engine.types import BotAction, CallerInput, CallStart
from callbot.engine.verification import IdentityVerifier
from llm.gateway import create_gateway


def _default_session_store() -> SessionStore:
    config = SessionSettings()
    return RedisSessionStore.from_url(
        config.redis_url,
        retention=RetentionPolicy(config.session_idle_ttl_s, config.session_max_age_s),
        key_prefix=config.redis_key_prefix,
        tombstone_ttl_s=config.session_tombstone_ttl_s,
        max_session_bytes=config.session_max_bytes,
        lock_lease_s=config.session_lock_lease_s,
    )


def create_orchestrator(
    clinic_api: ClinicAPI,
    settings: Optional[EngineSettings] = None,
    tracer: Optional[Tracer] = None,
    store: Optional[SessionStore] = None,
) -> CallOrchestrator:
    """Use the shared Redis session store unless an explicit test/application store is supplied."""
    settings = settings or EngineSettings()
    gateway = ClinicGateway(clinic_api, clinic_id=settings.clinic_id)
    name_fallback = None
    if settings.name_fallback_provider != "none":
        name_fallback = NameNER(create_gateway(settings.name_fallback_provider))
    return CallOrchestrator(
        sessions=SessionManager(store if store is not None else _default_session_store()),
        extractor=InformationExtractor(
            fallback=name_fallback, name_fallback=name_fallback is not None
        ),
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
    "RedisSessionStore",
    "ReconciliationRequired",
    "SessionNotFound",
    "SessionStore",
    "SessionStoreUnavailable",
    "TurnConflict",
    "TurnOutOfOrder",
    "create_orchestrator",
]
