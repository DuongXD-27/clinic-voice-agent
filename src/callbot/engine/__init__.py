"""AI Callbot Engine: Session Manager, Information Extraction, Policy, Verification, Dialogue & LLM."""

import logging
from collections.abc import Callable
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
from callbot.engine.extraction.semantic_failover import FailoverSemanticExtractor
from callbot.engine.extraction.semantic_jev import JevSemanticExtractor
from callbot.engine.extraction.slot_semantic import SlotSemanticReader
from callbot.engine.extraction.slot_semantic_jev import JevSlotSemanticExtractor
from callbot.engine.extraction.slot_semantic_luna import LunaSlotSemanticExtractor
from callbot.engine.orchestrator import CallOrchestrator, Tracer
from callbot.engine.policy import PolicyEngine
from callbot.engine.session import RedisSessionStore, SessionManager, SessionStore
from callbot.engine.session.retention import RetentionPolicy
from callbot.engine.session.settings import SessionSettings
from callbot.engine.settings import EngineSettings
from callbot.engine.tools import ClinicAPI, ClinicGateway
from callbot.engine.types import BotAction, CallerInput, CallStart, PhoneStatus
from callbot.engine.verification import IdentityVerifier
from callbot.tracing import Tracer as SpanTracer
from callbot.tracing import null_tracer
from inference.llm.config import OpenAIConfig, TypeSafeConfig
from inference.llm.gateway import create_gateway
from inference.llm.prompt.semantic import (
    PROMPT_VERSION,
    PROMPT_VERSION_CANCEL_CONFIRM,
    PROMPT_VERSION_LUNA,
)
from inference.llm.typesafe import TypeSafeClient


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
    init kwargs); `tests/llm/test_semantic_config.py` khóa hành vi đó.

    Provider chính `semantic_provider`, dự phòng `semantic_backup_provider` (cấu hình ở
    `config/engine.yaml`; mặc định jev, dự phòng openai). Thiếu khóa một bên thì chạy bên còn lại;
    thiếu cả hai thì chạy chỉ-luật, không chặn khởi động.
    """
    if not settings.semantic_fallback_enabled:
        return None
    primary = _SEMANTIC_PROVIDERS[settings.semantic_provider](settings)
    name = settings.semantic_backup_provider
    secondary = (
        _SEMANTIC_PROVIDERS[name](settings)
        if name != "none" and name != settings.semantic_provider
        else None
    )
    if primary is None:
        if secondary is not None:
            logger.warning(
                "Tầng ngữ nghĩa: provider chính %s thiếu khóa; dùng %s",
                settings.semantic_provider,
                name,
            )
        return secondary
    if secondary is None:
        return primary
    return FailoverSemanticExtractor(
        primary, secondary, min_secondary_s=settings.semantic_backup_min_remaining_s
    )


def _jev_semantic(settings: EngineSettings) -> Optional[JevSemanticExtractor]:
    try:
        typesafe = TypeSafeConfig(timeout_s=settings.semantic_fallback_timeout_s)
    except ValidationError:
        logger.warning("Tầng ngữ nghĩa: thiếu TYPESAFE_API_KEY, không dùng được jev")
        return None
    return JevSemanticExtractor(
        TypeSafeClient(typesafe),
        max_input_chars=settings.semantic_fallback_max_input_chars,
        min_confidence=settings.semantic_jev_min_confidence,
        min_noul=settings.semantic_jev_min_noul,
    )


def _openai_semantic(settings: EngineSettings) -> Optional[LLMSemanticExtractor]:
    try:
        config = OpenAIConfig(
            model=settings.semantic_openai_model,
            timeout_s=settings.semantic_fallback_timeout_s,
            max_completion_tokens=settings.semantic_openai_max_tokens,
        )
    except ValidationError:
        # Thiếu OPENAI_API_KEY: chạy chỉ-luật; các câu lâm sàng ngoài luật sẽ không được model phân loại.
        # Không để cả server không khởi động được.
        logger.warning("Tầng ngữ nghĩa: thiếu OPENAI_API_KEY, không dùng được openai")
        return None
    return LLMSemanticExtractor(
        create_gateway("openai", config=config),
        max_input_chars=settings.semantic_fallback_max_input_chars,
        max_completion_tokens=settings.semantic_openai_max_tokens,
        # Flag tắt: đúng prompt semantic_v5 như trước. Khi bật, Luna dùng prompt gọn chuyên biệt;
        # model khác giữ semantic_v6 để không đổi hành vi ngoài phạm vi tối ưu này.
        prompt_version=(
            (
                PROMPT_VERSION_LUNA
                if settings.semantic_openai_model.startswith("gpt-6-luna")
                else PROMPT_VERSION_CANCEL_CONFIRM
            )
            if settings.cancel_semantic_confirm_enabled
            else PROMPT_VERSION
        ),
    )


def _slot_semantic_reader(settings: EngineSettings) -> Optional[SlotSemanticReader]:
    """Tầng model của câu chọn khung (plan t10-slot-semantic-jev-2026-10-12.md §4.11): Jev chính, Luna
    khi câu không dấu hoặc Jev lỗi dịch vụ. Tắt cờ hoặc thiếu cả hai khóa: chỉ-luật."""
    if not settings.slot_semantic_enabled:
        return None
    jev = None
    try:
        typesafe = TypeSafeConfig(timeout_s=settings.slot_semantic_jev_timeout_s)
        jev = JevSlotSemanticExtractor(
            TypeSafeClient(typesafe),
            min_confidence=settings.semantic_jev_min_confidence,
        )
    except ValidationError:
        logger.warning("Tầng chọn khung: thiếu TYPESAFE_API_KEY, không dùng được jev")
    luna = None
    try:
        config = OpenAIConfig(
            model=settings.semantic_openai_model,
            timeout_s=settings.slot_semantic_luna_timeout_s,
            max_completion_tokens=settings.semantic_openai_max_tokens,
        )
        luna = LunaSlotSemanticExtractor(
            create_gateway("openai", config=config),
            max_completion_tokens=settings.semantic_openai_max_tokens,
        )
    except ValidationError:
        logger.warning("Tầng chọn khung: thiếu OPENAI_API_KEY, không có dự phòng Luna")
    if jev is None and luna is None:
        return None
    return SlotSemanticReader(jev, luna, budget_s=settings.slot_semantic_budget_s)


_SEMANTIC_PROVIDERS: dict[str, Callable[[EngineSettings], Optional[SemanticExtractor]]] = {
    "jev": _jev_semantic,
    "openai": _openai_semantic,
}


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
            slot_semantic=_slot_semantic_reader(settings),
        ),
        policy=PolicyEngine(settings),
        dialogue=DialogueManager(gateway, IdentityVerifier(gateway)),
        tracer=tracer,
    )


__all__ = [
    "PhoneStatus",
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
