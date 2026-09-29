"""AI Callbot Engine: Session Manager, Information Extraction, Policy, Verification, Dialogue & LLM."""

import logging
from typing import Optional

from pydantic import ValidationError

from callbot.engine.dialogue import DialogueManager
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
from callbot.engine.extraction.name_slot_filling import NameSlotFiller
from callbot.engine.extraction.semantic import LLMSemanticExtractor, SemanticExtractor
from callbot.engine.orchestrator import CallOrchestrator, Tracer
from callbot.engine.policy import PolicyEngine
from callbot.engine.session import RedisSessionStore, SessionManager, SessionStore
from callbot.engine.session.retention import RetentionPolicy
from callbot.engine.session.settings import SessionSettings
from callbot.engine.settings import EngineSettings
from callbot.engine.tools import ClinicAPI, ClinicGateway
from callbot.engine.types import BotAction, CallerInput, CallStart
from callbot.engine.verification import IdentityVerifier
from callbot.tracing import Tracer as SpanTracer
from callbot.tracing import null_tracer
from inference.llm.config import OpenAIConfig
from inference.llm.gateway import create_gateway
from inference.llm.prompt.semantic import (
    PROMPT_VERSION,
    PROMPT_VERSION_CANCEL_CONFIRM,
    PROMPT_VERSION_LUNA,
)


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


logger = logging.getLogger(__name__)


def _semantic_extractor(settings: EngineSettings) -> Optional[SemanticExtractor]:
    """Tầng ngữ nghĩa dùng cấu hình RIÊNG, không đọc `NAME_FALLBACK_*`.

    Giá trị truyền tường minh nên thắng alias env của `ProviderConfig` (pydantic-settings ưu tiên
    init kwargs); `tests/llm/test_semantic_config.py` khóa hành vi đó. Provider cố định OpenAI
    trong đợt này — đổi provider là thay đổi phạm vi, không phải đổi biến môi trường.
    """
    if not settings.semantic_fallback_enabled:
        return None
    try:
        config = OpenAIConfig(
            model=settings.semantic_fallback_model,
            timeout_s=settings.semantic_fallback_timeout_s,
            max_completion_tokens=settings.semantic_fallback_max_tokens,
        )
    except ValidationError:
        # Thiếu OPENAI_API_KEY: chạy chỉ-luật; các câu lâm sàng ngoài luật sẽ không được model phân loại.
        # Không để cả server không khởi động được.
        logger.warning("Tầng ngữ nghĩa đang bật nhưng thiếu OPENAI_API_KEY; chạy chỉ bằng luật")
        return None
    return LLMSemanticExtractor(
        create_gateway("openai", config=config),
        max_input_chars=settings.semantic_fallback_max_input_chars,
        max_completion_tokens=settings.semantic_fallback_max_tokens,
        # Flag tắt: đúng prompt semantic_v5 như trước. Khi bật, Luna dùng prompt gọn chuyên biệt;
        # model khác giữ semantic_v6 để không đổi hành vi ngoài phạm vi tối ưu này.
        prompt_version=(
            (
                PROMPT_VERSION_LUNA
                if settings.semantic_fallback_model.startswith("gpt-6-luna")
                else PROMPT_VERSION_CANCEL_CONFIRM
            )
            if settings.cancel_semantic_confirm_enabled
            else PROMPT_VERSION
        ),
    )


def create_orchestrator(
    clinic_api: ClinicAPI,
    settings: Optional[EngineSettings] = None,
    tracer: Optional[Tracer] = None,
    store: Optional[SessionStore] = None,
) -> CallOrchestrator:
    """Use the shared Redis session store unless an explicit test/application store is supplied."""
    settings = settings or EngineSettings()
    span_tracer = tracer if isinstance(tracer, SpanTracer) else null_tracer()
    gateway = ClinicGateway(clinic_api, clinic_id=settings.clinic_id, tracer=span_tracer)
    name_fallback = None
    if settings.name_fallback_provider != "none":
        name_fallback = NameSlotFiller(create_gateway(settings.name_fallback_provider))
    return CallOrchestrator(
        sessions=SessionManager(store if store is not None else _default_session_store()),
        extractor=InformationExtractor(
            fallback=name_fallback,
            name_fallback=name_fallback is not None,
            semantic=_semantic_extractor(settings),
            cancel_semantic_confirm=settings.cancel_semantic_confirm_enabled,
        ),
        policy=PolicyEngine(settings),
        dialogue=DialogueManager(gateway, IdentityVerifier(gateway)),
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
