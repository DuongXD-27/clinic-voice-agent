"""Closed HTTP response schemas for the internal Voice Observability API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from callbot.observability.models import (
    CallDetail,
    ErrorBreakdown,
    HourlyBucket,
    LatencyStats,
    OverviewResult,
    ProviderModelMetrics,
    QualityResult,
    RateMetric,
    SourceDiagnostics,
    StageSummary,
    TurnExecution,
)


class TimeRangeResponse(BaseModel):
    start: str
    end: str


class LatencyStatsResponse(BaseModel):
    count: int
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    min_ms: float | None
    max_ms: float | None
    mean_ms: float | None

    @classmethod
    def from_dto(cls, value: LatencyStats) -> LatencyStatsResponse:
        return cls(**value.to_dict())


class RateResponse(BaseModel):
    count: int
    denominator: int
    rate: float | None

    @classmethod
    def from_dto(cls, value: RateMetric) -> RateResponse:
        return cls(count=value.numerator, denominator=value.denominator, rate=value.rate)


class SttEmptyResponse(BaseModel):
    empty_count: int
    eligible_count: int
    rate: float | None

    @classmethod
    def from_dto(cls, value: RateMetric) -> SttEmptyResponse:
        return cls(
            empty_count=value.numerator,
            eligible_count=value.denominator,
            rate=value.rate,
        )


class ComponentErrorResponse(BaseModel):
    component: str
    count: int
    error_count: int
    error_rate: float | None


class ProviderModelResponse(BaseModel):
    component: str
    provider: str
    model: str
    count: int
    error_count: int
    error_rate: float | None
    latency: LatencyStatsResponse

    @classmethod
    def from_dto(cls, value: ProviderModelMetrics) -> ProviderModelResponse:
        return cls(
            component=value.component,
            provider=value.provider,
            model=value.model,
            count=value.count,
            error_count=value.error_count,
            error_rate=value.error_rate.rate,
            latency=LatencyStatsResponse.from_dto(value.latency),
        )


class HourlyBucketResponse(BaseModel):
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
    stt_empty: SttEmptyResponse

    @classmethod
    def from_dto(cls, value: HourlyBucket) -> HourlyBucketResponse:
        return cls(
            start_time=value.start_time,
            turn_count=value.turn_count,
            turn_error_count=value.turn_error_count,
            slow_turn_count=value.slow_turn_count,
            turn_p95_ms=value.turn_p95_ms,
            stt_count=value.stt_count,
            stt_p95_ms=value.stt_p95_ms,
            core_count=value.core_count,
            core_p95_ms=value.core_p95_ms,
            tts_count=value.tts_count,
            tts_p95_ms=value.tts_p95_ms,
            stt_empty=SttEmptyResponse.from_dto(value.stt_empty),
        )


class DiagnosticsResponse(BaseModel):
    records_processed: int
    records_skipped: int
    unsupported_records: int
    files_read: int
    files_skipped: int

    @classmethod
    def from_dto(cls, value: SourceDiagnostics) -> DiagnosticsResponse:
        return cls(
            records_processed=value.records_yielded,
            records_skipped=value.records_skipped,
            unsupported_records=value.unsupported_records,
            files_read=value.files_read,
            files_skipped=value.files_skipped,
        )


class OverviewResponse(BaseModel):
    time_range: TimeRangeResponse
    turn_count: int
    turn_latency: LatencyStatsResponse
    stt_latency: LatencyStatsResponse = Field(
        description="STT observation span duration; not provider inference latency. Use extended.stt_provider_latency for measured batch inference."
    )
    core_latency: LatencyStatsResponse
    tts_latency: LatencyStatsResponse
    clinic_latency: LatencyStatsResponse
    turn_error: RateResponse
    slow_turn: RateResponse
    stt_empty: SttEmptyResponse
    component_errors: list[ComponentErrorResponse]
    provider_model_breakdown: list[ProviderModelResponse]
    hourly: list[HourlyBucketResponse]
    diagnostics: DiagnosticsResponse
    extended: dict[str, Any] | None = None

    @classmethod
    def from_dto(cls, value: OverviewResult) -> OverviewResponse:
        return cls(
            time_range=TimeRangeResponse(start=value.start_time, end=value.end_time),
            turn_count=value.turn_count,
            turn_latency=LatencyStatsResponse.from_dto(value.turn_latency),
            stt_latency=LatencyStatsResponse.from_dto(value.stt_latency),
            core_latency=LatencyStatsResponse.from_dto(value.core_latency),
            tts_latency=LatencyStatsResponse.from_dto(value.tts_latency),
            clinic_latency=LatencyStatsResponse.from_dto(value.clinic_latency),
            turn_error=RateResponse.from_dto(value.turn_errors),
            slow_turn=RateResponse.from_dto(value.slow_turns),
            stt_empty=SttEmptyResponse.from_dto(value.stt_empty),
            component_errors=[
                ComponentErrorResponse(
                    component=item.component,
                    count=item.count,
                    error_count=item.error_count,
                    error_rate=item.error_rate.rate,
                )
                for item in value.component_metrics
            ],
            provider_model_breakdown=[
                ProviderModelResponse.from_dto(item) for item in value.provider_model_metrics
            ],
            hourly=[HourlyBucketResponse.from_dto(item) for item in value.hourly],
            diagnostics=DiagnosticsResponse.from_dto(value.diagnostics),
            extended=value.extended,
        )


class StageResponse(BaseModel):
    component: str
    operation: str
    duration_ms: float
    provider: str | None
    model: str | None
    status: str
    error_code: str | None

    @classmethod
    def from_dto(cls, value: StageSummary | None) -> StageResponse | None:
        if value is None:
            return None
        return cls(
            component=value.component,
            operation=value.operation,
            duration_ms=value.duration_ms,
            provider=value.provider,
            model=value.model,
            status=value.status,
            error_code=value.error_code,
        )


class StageBreakdownResponse(BaseModel):
    stt: StageResponse | None
    core: StageResponse | None
    tts: StageResponse | None


class TurnExecutionResponse(BaseModel):
    call_key: str
    turn: int
    trace_id: str
    start_time: str
    duration_ms: float
    status: str
    replayed: bool | None
    stages: StageBreakdownResponse
    clinic: list[StageResponse]
    error_codes: list[str]

    @classmethod
    def from_dto(cls, value: TurnExecution) -> TurnExecutionResponse:
        return cls(
            call_key=value.call_key,
            turn=value.turn,
            trace_id=value.trace_id,
            start_time=value.start_time,
            duration_ms=value.duration_ms,
            status=value.status,
            replayed=value.replayed,
            stages=StageBreakdownResponse(
                stt=StageResponse.from_dto(value.stt),
                core=StageResponse.from_dto(value.core),
                tts=StageResponse.from_dto(value.tts),
            ),
            clinic=[stage for item in value.clinic if (stage := StageResponse.from_dto(item))],
            error_codes=list(value.error_codes),
        )


class CallDetailResponse(BaseModel):
    call_key: str
    executions: list[TurnExecutionResponse]
    total_executions: int
    limit: int
    offset: int

    @classmethod
    def from_dto(cls, value: CallDetail, *, limit: int, offset: int) -> CallDetailResponse:
        return cls(
            call_key=value.call_key,
            executions=[TurnExecutionResponse.from_dto(item) for item in value.turns],
            total_executions=value.total_executions,
            limit=limit,
            offset=offset,
        )


class SlowTurnResponse(BaseModel):
    call_key: str
    turn: int
    trace_id: str
    start_time: str
    duration_ms: float
    stt_ms: float | None
    core_ms: float | None
    tts_ms: float | None
    status: str
    error_codes: list[str]

    @classmethod
    def from_dto(cls, value: TurnExecution) -> SlowTurnResponse:
        return cls(
            call_key=value.call_key,
            turn=value.turn,
            trace_id=value.trace_id,
            start_time=value.start_time,
            duration_ms=value.duration_ms,
            stt_ms=value.stt.duration_ms if value.stt is not None else None,
            core_ms=value.core.duration_ms if value.core is not None else None,
            tts_ms=value.tts.duration_ms if value.tts is not None else None,
            status=value.status,
            error_codes=list(value.error_codes),
        )


class SlowTurnListResponse(BaseModel):
    items: list[SlowTurnResponse]
    limit: int
    offset: int


class ErrorBreakdownResponse(BaseModel):
    component: str
    provider: str
    model: str
    error_code: str | None
    count: int

    @classmethod
    def from_dto(cls, value: ErrorBreakdown) -> ErrorBreakdownResponse:
        return cls(**value.to_dict())


class ErrorListResponse(BaseModel):
    items: list[ErrorBreakdownResponse]
    limit: int


class QualityIssueResponse(BaseModel):
    code: str
    label: str
    severity: str
    affected_count: int
    eligible_count: int
    rate: float | None


class QualityCoverageResponse(BaseModel):
    metric: str
    instrumentation_status: str
    detail: str


class QualityCandidateResponse(BaseModel):
    call_key: str
    turn: int
    trace_id: str
    issue_code: str
    issue_label: str
    safe_value: str
    status: str


class QualityResponse(BaseModel):
    component: str
    aggregation: str
    eligible_count: int
    affected_count: int
    clean_count: int
    affected_rate: float | None
    issues: list[QualityIssueResponse]
    coverage: list[QualityCoverageResponse]
    candidates: list[QualityCandidateResponse]

    @classmethod
    def from_dto(cls, value: QualityResult) -> QualityResponse:
        return cls(**value.to_dict())
