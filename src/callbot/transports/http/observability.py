"""Thin, read-only HTTP transport for vendor-neutral observability queries."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from callbot.observability import MetricsQueryService
from callbot.transports.http.observability_schemas import (
    CallDetailResponse,
    ErrorBreakdownResponse,
    ErrorListResponse,
    OverviewResponse,
    QualityResponse,
    SlowTurnListResponse,
    SlowTurnResponse,
    TurnExecutionResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/observability", tags=["internal-observability"])

_CALL_KEY = re.compile(r"^ck_[A-Za-z0-9_-]+_[A-Za-z0-9_-]+$")
_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
_DEFAULT_WINDOW = timedelta(hours=24)
_MAX_WINDOW = timedelta(days=31)
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 500
T = TypeVar("T")


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def get_observability_service(request: Request) -> MetricsQueryService:
    service = getattr(request.app.state, "observability_service", None)
    trace_dir = getattr(request.app.state, "observability_trace_dir", None)
    if not isinstance(service, MetricsQueryService) or not isinstance(trace_dir, Path):
        raise _error(503, "observability_unavailable", "Observability is unavailable")
    try:
        if trace_dir.exists() and not trace_dir.is_dir():
            raise _error(503, "observability_unavailable", "Observability is unavailable")
    except OSError as exc:
        raise _error(503, "observability_unavailable", "Observability is unavailable") from exc
    return service


ObservabilityService = Annotated[MetricsQueryService, Depends(get_observability_service)]
OptionalTimestamp = Annotated[datetime | None, Query()]
NonNegativeFloat = Annotated[float, Query(ge=0)]
BoundedLimit = Annotated[int, Query(ge=1, le=_MAX_LIMIT)]
NonNegativeOffset = Annotated[int, Query(ge=0)]


def _time_window(
    start: datetime | None,
    end: datetime | None,
) -> tuple[datetime, datetime]:
    resolved_end = end or datetime.now(timezone.utc)
    resolved_start = start or resolved_end - _DEFAULT_WINDOW
    if (
        resolved_start.tzinfo is None
        or resolved_start.utcoffset() is None
        or resolved_end.tzinfo is None
        or resolved_end.utcoffset() is None
    ):
        raise _error(422, "invalid_time_range", "Timestamps must include a timezone")
    resolved_start = resolved_start.astimezone(timezone.utc)
    resolved_end = resolved_end.astimezone(timezone.utc)
    if resolved_end <= resolved_start or resolved_end - resolved_start > _MAX_WINDOW:
        raise _error(422, "invalid_time_range", "Time range is invalid")
    return resolved_start, resolved_end


def _run_query(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("OBSERVABILITY_QUERY_FAILED:%s", type(exc).__name__)
        raise _error(503, "observability_unavailable", "Observability is unavailable") from exc


@router.get("/overview", response_model=OverviewResponse)
def overview(
    service: ObservabilityService,
    start: OptionalTimestamp = None,
    end: OptionalTimestamp = None,
    slow_threshold_ms: NonNegativeFloat = 2000.0,
) -> OverviewResponse:
    window_start, window_end = _time_window(start, end)
    result = _run_query(
        lambda: service.get_overview(
            window_start,
            window_end,
            slow_turn_threshold_ms=slow_threshold_ms,
        )
    )
    return OverviewResponse.from_dto(result)


@router.get("/calls/{call_key}", response_model=CallDetailResponse)
def call_detail(
    call_key: str,
    service: ObservabilityService,
    start: OptionalTimestamp = None,
    end: OptionalTimestamp = None,
    limit: BoundedLimit = _DEFAULT_LIMIT,
    offset: NonNegativeOffset = 0,
) -> CallDetailResponse:
    if len(call_key) > 200 or _CALL_KEY.fullmatch(call_key) is None:
        raise _error(422, "invalid_call_key", "Call key is invalid")
    window_start, window_end = _time_window(start, end)
    result = _run_query(
        lambda: service.get_call(
            call_key,
            window_start,
            window_end,
            limit=limit,
            offset=offset,
        )
    )
    if result.total_executions == 0:
        raise _error(404, "call_not_found", "Call was not found")
    return CallDetailResponse.from_dto(result, limit=limit, offset=offset)


@router.get("/turns/{trace_id}", response_model=TurnExecutionResponse)
def turn_detail(
    trace_id: str,
    service: ObservabilityService,
    start: OptionalTimestamp = None,
    end: OptionalTimestamp = None,
) -> TurnExecutionResponse:
    if _TRACE_ID.fullmatch(trace_id) is None:
        raise _error(422, "invalid_trace_id", "Trace ID is invalid")
    window_start, window_end = _time_window(start, end)
    result = _run_query(lambda: service.get_turn(trace_id, window_start, window_end))
    if result is None:
        raise _error(404, "turn_not_found", "Turn was not found")
    return TurnExecutionResponse.from_dto(result)


@router.get("/slow-turns", response_model=SlowTurnListResponse)
def slow_turns(
    service: ObservabilityService,
    start: OptionalTimestamp = None,
    end: OptionalTimestamp = None,
    threshold_ms: NonNegativeFloat = 2000.0,
    limit: BoundedLimit = _DEFAULT_LIMIT,
    offset: NonNegativeOffset = 0,
) -> SlowTurnListResponse:
    window_start, window_end = _time_window(start, end)
    result = _run_query(
        lambda: service.list_slow_turns(
            window_start,
            window_end,
            slow_turn_threshold_ms=threshold_ms,
            limit=limit,
            offset=offset,
        )
    )
    return SlowTurnListResponse(
        items=[SlowTurnResponse.from_dto(item) for item in result],
        limit=limit,
        offset=offset,
    )


@router.get("/errors", response_model=ErrorListResponse)
def errors(
    service: ObservabilityService,
    start: OptionalTimestamp = None,
    end: OptionalTimestamp = None,
    limit: BoundedLimit = _DEFAULT_LIMIT,
) -> ErrorListResponse:
    window_start, window_end = _time_window(start, end)
    result = _run_query(lambda: service.top_errors(window_start, window_end, limit=limit))
    return ErrorListResponse(
        items=[ErrorBreakdownResponse.from_dto(item) for item in result],
        limit=limit,
    )


@router.get("/quality", response_model=QualityResponse)
def quality(
    service: ObservabilityService,
    start: OptionalTimestamp = None,
    end: OptionalTimestamp = None,
    component: Literal["STT", "TTS"] = "STT",
    aggregation: Literal["call", "turn"] = "call",
    candidate_limit: BoundedLimit = 100,
) -> QualityResponse:
    window_start, window_end = _time_window(start, end)
    result = _run_query(
        lambda: service.get_quality(
            window_start,
            window_end,
            component=component,
            aggregation=aggregation,
            candidate_limit=candidate_limit,
        )
    )
    return QualityResponse.from_dto(result)
