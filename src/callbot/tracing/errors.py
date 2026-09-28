"""Stable, privacy-safe trace error classification."""

from __future__ import annotations

from dataclasses import dataclass

TRACE_STATUSES = frozenset({"OK", "ERROR", "CANCELLED"})
ERROR_TYPES = frozenset(
    {"VALIDATION", "UPSTREAM", "TIMEOUT", "VERSION_CONFLICT", "PROVIDER", "STORAGE", "INTERNAL"}
)
ERROR_CODES = frozenset(
    {
        "TURN_OUT_OF_ORDER",
        "TURN_CONFLICT",
        "CALL_CONFLICT",
        "SESSION_NOT_FOUND",
        "SESSION_STORE_UNAVAILABLE",
        "CALL_ENDED",
        "CALL_BUSY",
        "RECONCILIATION_REQUIRED",
        "FSM_ILLEGAL_TRANSITION",
        "GUARDRAIL_SF_01",
        "GUARDRAIL_SF_02",
        "GUARDRAIL_SF_03",
        "GUARDRAIL_SF_04",
        "GUARDRAIL_SF_05",
        "GUARDRAIL_CONFIRMATION",
        "CLINIC_TIMEOUT",
        "CLINIC_CONNECT_ERROR",
        "CLINIC_VERSION_CONFLICT",
        "CLINIC_REJECTED",
        "PROVIDER_TIMEOUT",
        "PROVIDER_CONNECT_ERROR",
        "PROVIDER_RATE_LIMITED",
        "PROVIDER_DECODE_ERROR",
        "PROVIDER_REJECTED",
        "STT_TIMEOUT",
        "STT_DECODE_ERROR",
        "STT_PROVIDER_ERROR",
        "TTS_TIMEOUT",
        "TTS_PROVIDER_ERROR",
        "TTS_STORAGE_ERROR",
        "TRACE_SINK_WRITE_FAILED",
        "INTERNAL_ERROR",
    }
)
RESULT_CODES = frozenset(
    {
        "CLINIC_OK",
        "CLINIC_REJECTED",
        "CLINIC_TIMEOUT",
        "CLINIC_CONNECT_ERROR",
        "CLINIC_VERSION_CONFLICT",
    }
)

_GUARDRAIL_CODES = {
    "SF-01": "GUARDRAIL_SF_01",
    "SF-02": "GUARDRAIL_SF_02",
    "SF-03": "GUARDRAIL_SF_03",
    "SF-04": "GUARDRAIL_SF_04",
    "SF-05": "GUARDRAIL_SF_05",
    "CONFIRMATION": "GUARDRAIL_CONFIRMATION",
}


@dataclass(frozen=True, slots=True)
class ErrorInfo:
    error_type: str
    error_code: str


_EXCEPTION_MAP = {
    "TurnOutOfOrder": ErrorInfo("VALIDATION", "TURN_OUT_OF_ORDER"),
    "TurnConflict": ErrorInfo("VERSION_CONFLICT", "TURN_CONFLICT"),
    "CallConflict": ErrorInfo("VALIDATION", "CALL_CONFLICT"),
    "SessionNotFound": ErrorInfo("VALIDATION", "SESSION_NOT_FOUND"),
    "SessionStoreUnavailable": ErrorInfo("STORAGE", "SESSION_STORE_UNAVAILABLE"),
    "CallEnded": ErrorInfo("VALIDATION", "CALL_ENDED"),
    "CallBusy": ErrorInfo("VERSION_CONFLICT", "CALL_BUSY"),
    "ReconciliationRequired": ErrorInfo("STORAGE", "RECONCILIATION_REQUIRED"),
    "IllegalTransition": ErrorInfo("INTERNAL", "FSM_ILLEGAL_TRANSITION"),
    "TimeoutError": ErrorInfo("TIMEOUT", "CLINIC_TIMEOUT"),
    "ConnectError": ErrorInfo("UPSTREAM", "CLINIC_CONNECT_ERROR"),
    "ConnectTimeout": ErrorInfo("TIMEOUT", "CLINIC_TIMEOUT"),
    "ReadTimeout": ErrorInfo("TIMEOUT", "CLINIC_TIMEOUT"),
}


def classify_exception(exc: BaseException) -> ErrorInfo:
    for exception_type in type(exc).__mro__:
        mapped = _EXCEPTION_MAP.get(exception_type.__name__)
        if mapped is not None:
            return mapped
    if type(exc).__name__ in {"ClinicWriteRejected", "SlotTaken", "ClinicAPIError"}:
        status = getattr(exc, "status", None)
        code = getattr(exc, "code", None)
        if code == "TIMEOUT":
            return ErrorInfo("TIMEOUT", "CLINIC_TIMEOUT")
        if code == "CONNECT_ERROR":
            return ErrorInfo("UPSTREAM", "CLINIC_CONNECT_ERROR")
        if status == 409 or code == "VERSION_CONFLICT":
            return ErrorInfo("VERSION_CONFLICT", "CLINIC_VERSION_CONFLICT")
        return ErrorInfo("UPSTREAM", "CLINIC_REJECTED")
    if type(exc).__name__ == "WriteOutcomeUnknown":
        if exc.__cause__ is not None:
            return classify_exception(exc.__cause__)
        return ErrorInfo("UPSTREAM", "CLINIC_REJECTED")
    if isinstance(exc, (ValueError, TypeError)):
        return ErrorInfo("VALIDATION", "INTERNAL_ERROR")
    return ErrorInfo("INTERNAL", "INTERNAL_ERROR")


def classify_guardrail(code: str) -> ErrorInfo:
    """Map business guardrails to a closed, privacy-safe trace registry."""
    return ErrorInfo("INTERNAL", _GUARDRAIL_CODES.get(code, "INTERNAL_ERROR"))
