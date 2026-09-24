"""Vendor-neutral voice observability aggregation and query API."""

from callbot.observability.aggregate import (
    MetricsAggregator,
    latency_stats,
    percentile,
    rate_metric,
)
from callbot.observability.models import (
    CallDetail,
    ComponentMetrics,
    ErrorBreakdown,
    HourlyBucket,
    LatencyStats,
    OverviewResult,
    ProviderModelMetrics,
    QualityCandidate,
    QualityCoverage,
    QualityIssue,
    QualityResult,
    RateMetric,
    SourceDiagnostics,
    StageSummary,
    TurnExecution,
)
from callbot.observability.query import MetricsQueryService
from callbot.observability.source import JsonlSpanSource, SpanSource

__all__ = [
    "CallDetail",
    "ComponentMetrics",
    "ErrorBreakdown",
    "HourlyBucket",
    "JsonlSpanSource",
    "LatencyStats",
    "MetricsAggregator",
    "MetricsQueryService",
    "OverviewResult",
    "ProviderModelMetrics",
    "QualityCandidate",
    "QualityCoverage",
    "QualityIssue",
    "QualityResult",
    "RateMetric",
    "SourceDiagnostics",
    "SpanSource",
    "StageSummary",
    "TurnExecution",
    "latency_stats",
    "percentile",
    "rate_metric",
]
