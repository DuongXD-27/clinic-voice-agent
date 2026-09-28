"""Closed, JSON-ready DTOs for voice observability queries."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from typing import Any


def _json_ready(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {key: _json_ready(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


class JsonReadyModel:
    """Small dependency-free serialization contract shared by public DTOs."""

    def to_dict(self) -> dict[str, Any]:
        result = _json_ready(self)
        assert isinstance(result, dict)
        return result


@dataclass(frozen=True, slots=True)
class SourceDiagnostics(JsonReadyModel):
    files_read: int = 0
    files_skipped: int = 0
    records_seen: int = 0
    records_yielded: int = 0
    records_skipped: int = 0
    unsupported_records: int = 0


@dataclass(frozen=True, slots=True)
class LatencyStats(JsonReadyModel):
    count: int
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    min_ms: float | None
    max_ms: float | None
    mean_ms: float | None


@dataclass(frozen=True, slots=True)
class RateMetric(JsonReadyModel):
    numerator: int
    denominator: int
    rate: float | None


@dataclass(frozen=True, slots=True)
class ComponentMetrics(JsonReadyModel):
    component: str
    count: int
    error_count: int
    error_rate: RateMetric
    latency: LatencyStats


@dataclass(frozen=True, slots=True)
class ProviderModelMetrics(JsonReadyModel):
    component: str
    provider: str
    model: str
    count: int
    error_count: int
    error_rate: RateMetric
    latency: LatencyStats


@dataclass(frozen=True, slots=True)
class ErrorBreakdown(JsonReadyModel):
    component: str
    provider: str
    model: str
    error_code: str | None
    count: int


@dataclass(frozen=True, slots=True)
class HourlyBucket(JsonReadyModel):
    start_time: str
    turn_count: int
    turn_error_count: int
    slow_turn_count: int
    turn_p95_ms: float | None
    stt_count: int
    stt_p95_ms: float | None
    core_count: int
    core_p95_ms: float | None
    tts_count: int
    tts_p95_ms: float | None
    stt_empty: RateMetric


@dataclass(frozen=True, slots=True)
class StageSummary(JsonReadyModel):
    component: str
    operation: str
    duration_ms: float
    provider: str | None
    model: str | None
    status: str
    error_code: str | None

    # Typed extension points. They remain unset until real spans provide the signals;
    # this layer deliberately does not derive them from other timings or statuses.
    confidence_bucket: str | None = None
    vad_end_reason: str | None = None
    provider_http_status: int | None = None
    retry_count: int | None = None
    was_split: bool | None = None
    barge_in: bool | None = None


@dataclass(frozen=True, slots=True)
class TurnExecution(JsonReadyModel):
    call_key: str
    turn: int
    trace_id: str
    start_time: str
    duration_ms: float
    status: str
    replayed: bool | None
    stt: StageSummary | None
    core: StageSummary | None
    tts: StageSummary | None
    clinic: tuple[StageSummary, ...]
    error_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CallDetail(JsonReadyModel):
    call_key: str
    turns: tuple[TurnExecution, ...]
    total_executions: int


@dataclass(frozen=True, slots=True)
class QualityIssue(JsonReadyModel):
    code: str
    label: str
    severity: str
    affected_count: int
    eligible_count: int
    rate: float | None


@dataclass(frozen=True, slots=True)
class QualityCoverage(JsonReadyModel):
    metric: str
    instrumentation_status: str
    detail: str


@dataclass(frozen=True, slots=True)
class QualityCandidate(JsonReadyModel):
    call_key: str
    turn: int
    trace_id: str
    issue_code: str
    issue_label: str
    safe_value: str
    status: str


@dataclass(frozen=True, slots=True)
class QualityResult(JsonReadyModel):
    component: str
    aggregation: str
    eligible_count: int
    affected_count: int
    clean_count: int
    affected_rate: float | None
    issues: tuple[QualityIssue, ...]
    coverage: tuple[QualityCoverage, ...]
    candidates: tuple[QualityCandidate, ...]


@dataclass(frozen=True, slots=True)
class OverviewResult(JsonReadyModel):
    start_time: str
    end_time: str
    slow_turn_threshold_ms: float
    turn_count: int
    turn_latency: LatencyStats
    stt_latency: LatencyStats
    core_latency: LatencyStats
    tts_latency: LatencyStats
    clinic_latency: LatencyStats
    turn_errors: RateMetric
    slow_turns: RateMetric
    stt_empty: RateMetric
    component_metrics: tuple[ComponentMetrics, ...]
    provider_model_metrics: tuple[ProviderModelMetrics, ...]
    hourly: tuple[HourlyBucket, ...]
    diagnostics: SourceDiagnostics
