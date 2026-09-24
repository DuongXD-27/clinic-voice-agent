"""Read-only query service for future Voice Dashboard consumers.

The JSONL source streams files, while queries materialize only the requested UTC
window when hierarchy reconstruction or multi-metric grouping requires it. This is
intended for bounded POC/local dashboard windows, not unbounded warehouse workloads.
"""

from __future__ import annotations

from datetime import datetime

from callbot.observability.aggregate import MetricsAggregator
from callbot.observability.models import (
    CallDetail,
    ErrorBreakdown,
    OverviewResult,
    QualityResult,
    TurnExecution,
)
from callbot.observability.source import SpanSource, require_utc_range


class MetricsQueryService:
    def __init__(self, source: SpanSource, aggregator: MetricsAggregator | None = None) -> None:
        self._source = source
        self._aggregator = aggregator or MetricsAggregator()

    def get_overview(
        self,
        start_time: datetime,
        end_time: datetime,
        *,
        slow_turn_threshold_ms: float = 2000.0,
    ) -> OverviewResult:
        start, end = require_utc_range(start_time, end_time)
        spans = list(self._source.query(start, end))
        return self._aggregator.overview(
            spans,
            start_time=start,
            end_time=end,
            slow_turn_threshold_ms=slow_turn_threshold_ms,
            diagnostics=self._source.diagnostics,
        )

    def get_call(
        self,
        call_key: str,
        start_time: datetime,
        end_time: datetime,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> CallDetail:
        if limit is not None and limit <= 0:
            raise ValueError("limit must be positive")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        start, end = require_utc_range(start_time, end_time)
        detail = self._aggregator.call_detail(self._source.query(start, end), call_key)
        stop = None if limit is None else offset + limit
        return CallDetail(
            call_key=detail.call_key,
            turns=detail.turns[offset:stop],
            total_executions=detail.total_executions,
        )

    def get_turn(
        self, trace_id: str, start_time: datetime, end_time: datetime
    ) -> TurnExecution | None:
        start, end = require_utc_range(start_time, end_time)
        records = [span for span in self._source.query(start, end) if span.trace_id == trace_id]
        executions = self._aggregator.executions(records)
        return executions[0] if executions else None

    def top_errors(
        self,
        start_time: datetime,
        end_time: datetime,
        *,
        limit: int = 10,
    ) -> tuple[ErrorBreakdown, ...]:
        start, end = require_utc_range(start_time, end_time)
        return self._aggregator.top_errors(self._source.query(start, end), limit=limit)

    def get_quality(
        self,
        start_time: datetime,
        end_time: datetime,
        *,
        component: str,
        aggregation: str,
        candidate_limit: int = 100,
    ) -> QualityResult:
        start, end = require_utc_range(start_time, end_time)
        return self._aggregator.quality(
            self._source.query(start, end),
            component=component,
            aggregation=aggregation,
            candidate_limit=candidate_limit,
        )

    def list_slow_turns(
        self,
        start_time: datetime,
        end_time: datetime,
        *,
        slow_turn_threshold_ms: float = 2000.0,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[TurnExecution, ...]:
        if slow_turn_threshold_ms < 0:
            raise ValueError("slow_turn_threshold_ms must be non-negative")
        if limit is not None and limit <= 0:
            raise ValueError("limit must be positive")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        start, end = require_utc_range(start_time, end_time)
        executions = self._aggregator.executions(self._source.query(start, end))
        slow = sorted(
            (
                execution
                for execution in executions
                if execution.duration_ms >= slow_turn_threshold_ms
            ),
            key=lambda item: (-item.duration_ms, item.start_time, item.trace_id),
        )
        stop = None if limit is None else offset + limit
        return tuple(slow[offset:stop])
