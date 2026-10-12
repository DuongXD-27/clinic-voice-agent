"""Strict allowlists for data that may enter trace records."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from types import MappingProxyType
from typing import Any, Mapping

from callbot.tracing.errors import ERROR_CODES, ERROR_TYPES, RESULT_CODES
from callbot.tracing.models import CompletedSpan

COMPONENTS = frozenset(
    {"TURN", "CORE", "EXTRACTION", "DIALOGUE", "GUARD", "CLINIC", "STT", "TTS", "LLM"}
)
OPERATIONS = frozenset(
    {
        "http.call_turn",
        "http.start_call",
        "livekit.call_turn",
        "livekit.start_call",
        "livekit.close_call",
        "livekit.tts_recovery",
        "core.handle_turn",
        "core.start_call",
        "core.close_call",
        "core.system_error",
        "core.extract",
        "core.dialogue",
        "core.output_guard",
        "clinic.find_patient_by_phone",
        "clinic.get_appointment",
        "clinic.get_slots",
        "clinic.create_appointment",
        "clinic.confirm_appointment",
        "clinic.cancel_appointment",
        "clinic.reschedule_appointment",
        "clinic.transfer_appointment",
        "clinic.mark_unreachable",
        "speech.stt.transcribe",
        "speech.tts.synthesize",
        "llm.semantic_extract",
        "llm.name_slot_fill",
    }
)
EVENT_FIELDS: dict[str, frozenset[str]] = {
    "ie.model": frozenset({"model", "latency_ms", "model_result"}),
    "session.admitted": frozenset({"replayed", "terminal", "storage_status", "turn_ordering"}),
    "session.replayed": frozenset({"replayed", "terminal", "storage_status", "turn_ordering"}),
    "session.committed": frozenset({"replayed", "terminal", "storage_status", "turn_ordering"}),
    "session.close_requested": frozenset({"storage_status"}),
    "session.closed": frozenset({"replayed", "terminal", "storage_status"}),
    "clinic.write_blocked": frozenset({"write_operation", "decision_reason"}),
    "call.hangup": frozenset({"decision_reason", "turns_dropped"}),
    "call.event_ignored": frozenset({"stage", "decision_reason"}),
    "tts.playback_failed": frozenset({"provider_error_code", "error_class", "decision_reason"}),
    "tts.fallback_played": frozenset({"played", "decision_reason", "audio_duration_ms"}),
    "call.handoff_requested": frozenset(
        {"transfer_reason", "preserve_business_outcome", "reconciliation_required"}
    ),
    "call.cleanup": frozenset(
        {
            "timers_stopped",
            "input_stopped",
            "tts_closed",
            "queue_cleared",
            "audio_closed",
            "session_closed",
        }
    ),
    "policy.decision": frozenset({"stage", "decision", "decision_reason"}),
    "fsm.transition": frozenset(
        {"state_before", "state_after", "outcome", "status", "error_type", "error_code"}
    ),
    "guardrail.blocked": frozenset({"status", "error_type", "error_code"}),
    "output_guard.blocked": frozenset({"guard_rule", "error_type", "error_code"}),
    "output_guard.replaced": frozenset({"guard_rule", "outcome", "write_operation"}),
    "clinic.attempt": frozenset(
        {"attempt", "http_status", "latency_ms", "error_code", "version_conflict"}
    ),
}
SPAN_FIELDS = frozenset(
    {
        "route_template",
        "http_method",
        "http_status",
        "state_before",
        "state_after",
        "final_state",
        "outcome",
        "decision",
        "decision_reason",
        "replayed",
        "silent",
        "dialogue_action",
        "clinic_call_count",
        "guardrail_code",
        "guard_verdict",
        "guard_rule",
        "render_count",
        "write_attempted",
        "write_succeeded",
        "write_operation",
        "write_status_match",
        "error_type",
        "error_code",
        "question_id",
        "question_before",
        "question_after",
        "understanding",
        "full_name_presence",
        "full_name_provenance",
        "dob_classification",
        "dob_provenance",
        "intent_label",
        "intent_provenance",
        "agreement_label",
        "agreement_provenance",
        "clinical_label",
        "clinical_provenance",
        "cancel_reason_label",
        "cancel_reason_provenance",
        "line_signal_label",
        "line_signal_provenance",
        "slot_choice_kind",
        "candidate_count",
        "endpoint_template",
        "attempt_count",
        "version_conflict",
        "idempotency_used",
        "latency_ms",
        "result_code",
        "provider",
        "model",
        "input_tokens",
        "output_tokens",
        "config_version",
        "voice",
        "audio_duration_ms",
        "sample_rate_hz",
        "first_partial_ms",
        "final_ms",
        "partial_count",
        "streaming",
        "silence_detected",
        "transcript_empty",
        "confidence_bucket",
        "vad_end_reason",
        "decode_error",
        "complete_ms",
        "bytes",
        "chunks",
        "was_split",
        "split_count",
        "text_length_bucket",
        "barge_in",
        "cancelled",
        "provider_http_status",
        "retry_count",
        "token_count",
        "timeout",
        "provider_status",
        "direction",
        "mode",
        "ended",
        "result",
        "error_class",
        "configured_model",
        "actual_model",
        "total_tokens",
        "cached_input_tokens",
        "reasoning_tokens",
        "cost_usd",
        "provider_latency_ms",
        "model_call_latency_ms",
        "confidence",
        "input_mode",
        "provider_requested",
        "provider_actual",
        "fallback_used",
        "fallback_reason",
        "character_count",
        "cache_hit",
        "cache_key",
        "catalog_version",
        "billed_characters",
        "ttfa_ms",
        "audio_format",
        "interrupted",
        "truncated",
        "if_match_used",
        "misunderstanding_count",
        "silence_count",
        "identity_result",
        "confirmation_result",
        "released_fields",
        "provider_error_code",
        "model_result",
    }
)
_ROUTES = frozenset({"/v1/calls", "/v1/calls/{call_id}/turn"})
_ENDPOINTS = frozenset(
    {
        "/patients",
        "/slots",
        "/appointments",
        "/appointments/{id}",
        "/appointments/{id}/confirm",
        "/appointments/{id}/cancel",
        "/appointments/{id}/reschedule",
        "/appointments/{id}/transfer",
        "/appointments/{id}/unreachable",
    }
)
_SEMANTIC_FIELDS = frozenset(
    {
        "state_before",
        "state_after",
        "final_state",
        "outcome",
        "decision",
        "decision_reason",
        "dialogue_action",
        "guardrail_code",
        "guard_verdict",
        "guard_rule",
        "write_operation",
        "question_id",
        "question_before",
        "question_after",
        "understanding",
        "full_name_provenance",
        "dob_classification",
        "dob_provenance",
        "intent_label",
        "intent_provenance",
        "agreement_label",
        "agreement_provenance",
        "clinical_label",
        "clinical_provenance",
        "cancel_reason_label",
        "cancel_reason_provenance",
        "line_signal_label",
        "line_signal_provenance",
        "slot_choice_kind",
        "result_code",
        "stage",
        "storage_status",
        "turn_ordering",
        "status",
        "confidence_bucket",
        "vad_end_reason",
        "text_length_bucket",
        "provider_status",
        "direction",
        "mode",
        "result",
        "error_class",
        "input_mode",
        "fallback_reason",
        "audio_format",
        "identity_result",
        "confirmation_result",
        "released_fields",
        "provider_error_code",
    }
)
_SEMANTIC_VALUE = re.compile(r"^[A-Za-z0-9_.:-]+$")
_SAFE_LABEL = re.compile(r"^[A-Za-z0-9_.:/+-]{1,100}$")
_SENSITIVE_LABEL = re.compile(r"(?i)(?:patient|appointment|apt|phone|dob)[_:-]|\+?\d{7,}")
_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
_SPAN_ID = re.compile(r"^[0-9a-f]{16}$")
_CALL_KEY = re.compile(r"^ck_[A-Za-z0-9_-]+_[A-Za-z0-9_-]+$")
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
_SAFE_ATTRIBUTES_TOKEN = object()


class UnsafeTraceData(ValueError):
    pass


def _safe_value(value: Any) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    return isinstance(value, float) and value == value and abs(value) != float("inf")


def _validate(values: Mapping[str, Any], allowlist: frozenset[str]) -> dict[str, Any]:
    unknown = set(values) - allowlist
    if unknown:
        raise UnsafeTraceData(f"trace attribute keys are not allowlisted: {sorted(unknown)!r}")
    result: dict[str, Any] = {}
    for key, value in values.items():
        if value is None:
            continue
        if not _safe_value(value):
            raise UnsafeTraceData(f"trace attribute {key!r} must be a primitive safe value")
        if key == "error_type" and value not in ERROR_TYPES:
            raise UnsafeTraceData("unknown trace error type")
        if key in {"error_code", "guardrail_code"} and value not in ERROR_CODES:
            raise UnsafeTraceData("unknown trace error code")
        if key == "result_code" and value not in RESULT_CODES:
            raise UnsafeTraceData("unknown trace result code")
        if key == "model_result" and value not in {"OK", "TIMEOUT", "ERROR", "INVALID"}:
            raise UnsafeTraceData("unknown IE model result")
        if key == "route_template" and value not in _ROUTES:
            raise UnsafeTraceData("unknown HTTP route template")
        if key == "endpoint_template" and value not in _ENDPOINTS:
            raise UnsafeTraceData("unknown Clinic endpoint template")
        if key == "http_method" and value not in {"GET", "POST", "PATCH", "PUT", "DELETE"}:
            raise UnsafeTraceData("unknown HTTP method")
        if key in _SEMANTIC_FIELDS and (
            not isinstance(value, str) or _SEMANTIC_VALUE.fullmatch(value) is None
        ):
            raise UnsafeTraceData("trace semantic value is invalid")
        if key in {
            "provider",
            "model",
            "voice",
            "config_version",
            "configured_model",
            "actual_model",
            "provider_requested",
            "provider_actual",
            "catalog_version",
        } and (
            not isinstance(value, str)
            or _SAFE_LABEL.fullmatch(value) is None
            or "://" in value
            or _SENSITIVE_LABEL.search(value) is not None
        ):
            raise UnsafeTraceData("trace label value is invalid")
        if key in {
            "http_status",
            "attempt",
            "candidate_count",
            "clinic_call_count",
            "partial_count",
            "bytes",
            "chunks",
            "split_count",
            "provider_http_status",
            "retry_count",
            "token_count",
            "sample_rate_hz",
            "render_count",
            "write_attempted",
            "write_succeeded",
            "total_tokens",
            "cached_input_tokens",
            "reasoning_tokens",
            "character_count",
            "billed_characters",
            "misunderstanding_count",
            "silence_count",
        } and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            raise UnsafeTraceData("trace numeric value is invalid")
        if key == "cache_hit" and not isinstance(value, bool):
            raise UnsafeTraceData("trace cache hit is invalid")
        if key == "cache_key" and (
            not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None
        ):
            raise UnsafeTraceData("trace static cache key is invalid")
        if key == "confidence" and value > 1:
            raise UnsafeTraceData("trace confidence is invalid")
        if key in {
            "latency_ms",
            "audio_duration_ms",
            "first_partial_ms",
            "final_ms",
            "complete_ms",
            "provider_latency_ms",
            "model_call_latency_ms",
            "ttfa_ms",
            "cost_usd",
            "confidence",
        } and (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not isfinite(value)
            or value < 0
        ):
            raise UnsafeTraceData("trace numeric value is invalid")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True, init=False)
class SafeAttributes:
    values: Mapping[str, Any]

    def __init__(self, values: Mapping[str, Any], *, _token: object | None = None) -> None:
        if _token is not _SAFE_ATTRIBUTES_TOKEN:
            raise UnsafeTraceData("SafeAttributes must be created by an allowlisted factory")
        object.__setattr__(self, "values", MappingProxyType(dict(values)))

    @classmethod
    def for_span(cls, **values: Any) -> SafeAttributes:
        return cls(_validate(values, SPAN_FIELDS), _token=_SAFE_ATTRIBUTES_TOKEN)

    @classmethod
    def for_event(cls, name: str, **values: Any) -> SafeAttributes:
        if name not in EVENT_FIELDS:
            raise UnsafeTraceData("unknown trace event")
        return cls(_validate(values, EVENT_FIELDS[name]), _token=_SAFE_ATTRIBUTES_TOKEN)


def validate_component_operation(component: str, operation: str) -> None:
    if component not in COMPONENTS or operation not in OPERATIONS:
        raise UnsafeTraceData("unknown trace component or operation")


def _validate_timestamp(value: object) -> None:
    if not isinstance(value, str) or _TIMESTAMP.fullmatch(value) is None:
        raise UnsafeTraceData("trace timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise UnsafeTraceData("trace timestamp is invalid") from exc
    if parsed.tzinfo != timezone.utc:
        raise UnsafeTraceData("trace timestamp is invalid")


def validate_completed_span(span: CompletedSpan) -> None:
    """Revalidate the final export boundary so sinks cannot bypass the privacy contract."""
    validate_component_operation(span.component, span.operation)
    if _TRACE_ID.fullmatch(span.trace_id) is None:
        raise UnsafeTraceData("trace id is invalid")
    if _SPAN_ID.fullmatch(span.span_id) is None:
        raise UnsafeTraceData("span id is invalid")
    if span.parent_span_id is not None and _SPAN_ID.fullmatch(span.parent_span_id) is None:
        raise UnsafeTraceData("parent span id is invalid")
    if _CALL_KEY.fullmatch(span.call_key) is None or len(span.call_key) > 200:
        raise UnsafeTraceData("call key is invalid")
    if not isinstance(span.turn, int) or isinstance(span.turn, bool) or span.turn < 0:
        raise UnsafeTraceData("turn is invalid")
    if span.status not in {"OK", "ERROR", "CANCELLED"}:
        raise UnsafeTraceData("trace status is invalid")
    if span.observation_type not in {"SPAN", "GENERATION"}:
        raise UnsafeTraceData("trace observation type is invalid")
    if span.observation_type == "GENERATION" and span.component != "LLM":
        raise UnsafeTraceData("generation must be an LLM observation")
    _validate_timestamp(span.start_time)
    _validate_timestamp(span.end_time)
    if (
        not isinstance(span.duration_ms, (int, float))
        or isinstance(span.duration_ms, bool)
        or not isfinite(span.duration_ms)
        or span.duration_ms < 0
    ):
        raise UnsafeTraceData("trace duration is invalid")
    SafeAttributes.for_span(**span.attributes)
    for event in span.events:
        _validate_timestamp(event.timestamp)
        SafeAttributes.for_event(event.name, **event.attributes)
