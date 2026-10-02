"""Deterministic aggregation of completed trace spans into dashboard DTOs."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from math import ceil, fsum

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
from callbot.observability.source import parse_timestamp
from callbot.tracing.models import CompletedSpan

_COMPONENTS = ("STT", "CORE", "TTS", "CLINIC")
_PROVIDER_COMPONENTS = frozenset({"STT", "TTS"})
_UNSPECIFIED = "UNSPECIFIED"
_QUALITY_DEFINITIONS = {
    "STT": (
        ("STT_EMPTY_TRANSCRIPT", "Transcript rỗng", "Cần xem"),
        ("STT_DECODE_ERROR", "Lỗi giải mã audio", "Lỗi"),
        ("STT_TIMEOUT", "STT quá thời gian", "Lỗi"),
        ("STT_PROVIDER_ERROR", "Lỗi nhà cung cấp STT", "Lỗi"),
    ),
    "TTS": (
        ("TTS_TIMEOUT", "TTS quá thời gian", "Lỗi"),
        ("TTS_PROVIDER_ERROR", "Lỗi nhà cung cấp TTS", "Lỗi"),
        ("TTS_STORAGE_ERROR", "Lỗi lưu audio TTS", "Lỗi"),
    ),
}
_QUALITY_COVERAGE = {
    "STT": (
        ("Confidence below threshold", "Confidence telemetry is not currently available."),
        ("R-22 identity result: suspicious", "No privacy-safe identity result is traced."),
        ("R-22 identity result: mismatch", "No privacy-safe identity result is traced."),
        ("STT first partial", "First-partial telemetry is not currently populated."),
        ("VAD end reason", "VAD end-reason telemetry is not currently populated."),
        ("429 breakdown", "Provider HTTP status is not currently populated."),
        ("Retry", "Retry telemetry is not currently populated."),
        ("Barge-in", "Barge-in telemetry is not currently populated."),
    ),
    "TTS": (
        ("TTS TTFA", "First-audio telemetry is not currently populated."),
        ("429 breakdown", "Provider HTTP status is not currently populated."),
        ("Retry", "Retry telemetry is not currently populated."),
        ("TTS split", "Split telemetry is not currently populated."),
        ("Barge-in", "Barge-in telemetry is not currently populated."),
    ),
}


def percentile(values: Sequence[float], quantile: float) -> float | None:
    """Return the deterministic nearest-rank percentile (rank = ceil(q * n))."""
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be between zero and one")
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    rank = max(1, ceil(quantile * len(ordered)))
    return ordered[rank - 1]


def latency_stats(values: Iterable[float]) -> LatencyStats:
    samples = [float(value) for value in values]
    if not samples:
        return LatencyStats(0, None, None, None, None, None, None)
    return LatencyStats(
        count=len(samples),
        p50_ms=percentile(samples, 0.50),
        p95_ms=percentile(samples, 0.95),
        p99_ms=percentile(samples, 0.99),
        min_ms=min(samples),
        max_ms=max(samples),
        mean_ms=fsum(samples) / len(samples),
    )


def rate_metric(numerator: int, denominator: int) -> RateMetric:
    return RateMetric(
        numerator=numerator,
        denominator=denominator,
        rate=None if denominator == 0 else numerator / denominator,
    )


def _label(span: CompletedSpan, field: str) -> str:
    value = span.attributes.get(field)
    return value if isinstance(value, str) else _UNSPECIFIED


def _error_code(span: CompletedSpan) -> str | None:
    value = span.attributes.get("error_code")
    return value if isinstance(value, str) else None


def _stage(span: CompletedSpan) -> StageSummary:
    return StageSummary(
        component=span.component,
        operation=span.operation,
        duration_ms=float(span.duration_ms),
        provider=span.attributes.get("provider")
        if isinstance(span.attributes.get("provider"), str)
        else None,
        model=span.attributes.get("model")
        if isinstance(span.attributes.get("model"), str)
        else None,
        status=span.status,
        error_code=_error_code(span),
    )


def _descendants(root_id: str, spans: Sequence[CompletedSpan]) -> set[str]:
    children: dict[str, list[str]] = defaultdict(list)
    for span in spans:
        if span.parent_span_id is not None:
            children[span.parent_span_id].append(span.span_id)
    result: set[str] = set()
    pending = list(children.get(root_id, ()))
    while pending:
        span_id = pending.pop()
        if span_id in result:
            continue
        result.add(span_id)
        pending.extend(children.get(span_id, ()))
    return result


def _execution(root: CompletedSpan, trace_spans: Sequence[CompletedSpan]) -> TurnExecution:
    ordered = sorted(trace_spans, key=lambda span: (span.start_time, span.span_id))
    direct = [span for span in ordered if span.parent_span_id == root.span_id]

    def direct_stage(component: str) -> StageSummary | None:
        return next((_stage(span) for span in direct if span.component == component), None)

    core = next((span for span in direct if span.component == "CORE"), None)
    core_descendants = _descendants(core.span_id, ordered) if core is not None else set()
    clinic = tuple(
        _stage(span)
        for span in ordered
        if span.component == "CLINIC" and span.span_id in core_descendants
    )
    replayed = root.attributes.get("replayed")
    if not isinstance(replayed, bool):
        replayed = next(
            (
                True
                for event in root.events
                if event.name == "session.replayed" and event.attributes.get("replayed") is True
            ),
            None,
        )
    error_codes = tuple(
        sorted({code for span in ordered if (code := _error_code(span)) is not None})
    )
    return TurnExecution(
        call_key=root.call_key,
        turn=root.turn,
        trace_id=root.trace_id,
        start_time=root.start_time,
        duration_ms=float(root.duration_ms),
        status=root.status,
        replayed=replayed,
        stt=direct_stage("STT"),
        core=direct_stage("CORE"),
        tts=direct_stage("TTS"),
        clinic=clinic,
        error_codes=error_codes,
    )


class MetricsAggregator:
    """Pure aggregation logic with no storage or Langfuse dependency."""

    def overview(
        self,
        spans: Iterable[CompletedSpan],
        *,
        start_time: datetime,
        end_time: datetime,
        slow_turn_threshold_ms: float,
        diagnostics: SourceDiagnostics | None = None,
        scores: Sequence[dict] = (),
    ) -> OverviewResult:
        if slow_turn_threshold_ms < 0:
            raise ValueError("slow_turn_threshold_ms must be non-negative")
        records = list(spans)
        by_component = {
            component: [span for span in records if span.component == component]
            for component in ("TURN", *_COMPONENTS)
        }
        turns = by_component["TURN"]
        turn_error_count = sum(span.status == "ERROR" for span in turns)
        slow_count = sum(span.duration_ms >= slow_turn_threshold_ms for span in turns)

        component_metrics = tuple(
            self._component_metrics(component, by_component[component]) for component in _COMPONENTS
        )
        provider_metrics = self._provider_metrics(records)
        from callbot.observability.extended import extended_metrics

        return OverviewResult(
            start_time=_iso_utc(start_time),
            end_time=_iso_utc(end_time),
            slow_turn_threshold_ms=float(slow_turn_threshold_ms),
            turn_count=len(turns),
            turn_latency=latency_stats(span.duration_ms for span in turns),
            stt_latency=latency_stats(span.duration_ms for span in by_component["STT"]),
            core_latency=latency_stats(span.duration_ms for span in by_component["CORE"]),
            tts_latency=latency_stats(span.duration_ms for span in by_component["TTS"]),
            clinic_latency=latency_stats(span.duration_ms for span in by_component["CLINIC"]),
            turn_errors=rate_metric(turn_error_count, len(turns)),
            slow_turns=rate_metric(slow_count, len(turns)),
            stt_empty=self._stt_empty(by_component["STT"]),
            component_metrics=component_metrics,
            provider_model_metrics=provider_metrics,
            hourly=self._hourly(records, slow_turn_threshold_ms),
            diagnostics=diagnostics or SourceDiagnostics(),
            extended=extended_metrics(records, scores=scores),
        )

    def top_errors(
        self, spans: Iterable[CompletedSpan], *, limit: int = 10
    ) -> tuple[ErrorBreakdown, ...]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        counts: dict[tuple[str, str, str, str | None], int] = defaultdict(int)
        for span in spans:
            if span.status != "ERROR":
                continue
            key = (
                span.component,
                _label(span, "provider"),
                _label(span, "model"),
                _error_code(span),
            )
            counts[key] += 1
        rows = [ErrorBreakdown(*key, count) for key, count in counts.items()]
        return tuple(
            sorted(
                rows,
                key=lambda row: (
                    -row.count,
                    row.component,
                    row.provider,
                    row.model,
                    row.error_code or "",
                ),
            )[:limit]
        )

    def quality(
        self,
        spans: Iterable[CompletedSpan],
        *,
        component: str,
        aggregation: str,
        candidate_limit: int = 100,
    ) -> QualityResult:
        """Aggregate supported quality signals without inferring absent telemetry."""
        normalized_component = component.upper()
        if normalized_component not in _QUALITY_DEFINITIONS:
            raise ValueError("component must be STT or TTS")
        if aggregation not in {"call", "turn"}:
            raise ValueError("aggregation must be call or turn")
        if candidate_limit <= 0:
            raise ValueError("candidate_limit must be positive")

        records = list(spans)
        by_trace: dict[str, list[CompletedSpan]] = defaultdict(list)
        for span in records:
            by_trace[span.trace_id].append(span)

        units: list[tuple[CompletedSpan, CompletedSpan, frozenset[str]]] = []
        supported_codes = {item[0] for item in _QUALITY_DEFINITIONS[normalized_component]}
        for trace_spans in by_trace.values():
            ordered = sorted(trace_spans, key=lambda span: (span.start_time, span.span_id))
            roots = [
                span for span in ordered if span.component == "TURN" and span.parent_span_id is None
            ]
            for root in roots:
                stage = next(
                    (
                        span
                        for span in ordered
                        if span.parent_span_id == root.span_id
                        and span.component == normalized_component
                    ),
                    None,
                )
                if stage is None:
                    continue
                issues: set[str] = set()
                error_code = _error_code(stage)
                if error_code in supported_codes:
                    issues.add(error_code)
                if (
                    normalized_component == "STT"
                    and stage.attributes.get("transcript_empty") is True
                ):
                    issues.add("STT_EMPTY_TRANSCRIPT")
                units.append((root, stage, frozenset(issues)))

        units.sort(key=lambda item: (item[0].start_time, item[0].trace_id))
        labels = {
            code: label for code, label, _severity in _QUALITY_DEFINITIONS[normalized_component]
        }
        severities = {
            code: severity for code, _label, severity in _QUALITY_DEFINITIONS[normalized_component]
        }

        if aggregation == "turn":
            grouped = [((root.trace_id,), [(root, stage, issues)]) for root, stage, issues in units]
        else:
            calls: dict[str, list[tuple[CompletedSpan, CompletedSpan, frozenset[str]]]] = (
                defaultdict(list)
            )
            for unit in units:
                calls[unit[0].call_key].append(unit)
            grouped = sorted(calls.items())

        issue_counts = {code: 0 for code in supported_codes}
        issue_eligible_counts = {code: len(grouped) for code in supported_codes}
        if normalized_component == "STT":
            issue_eligible_counts["STT_EMPTY_TRANSCRIPT"] = sum(
                any(
                    isinstance(stage.attributes.get("transcript_empty"), bool)
                    for _root, stage, _issues in group
                )
                for _key, group in grouped
            )
        candidates: list[QualityCandidate] = []
        affected_count = 0
        for _key, group in grouped:
            group_issues = set().union(*(issues for _root, _stage, issues in group))
            if group_issues:
                affected_count += 1
            for code in sorted(group_issues):
                issue_counts[code] += 1
                representative = next(item for item in group if code in item[2])
                root, stage, _issues = representative
                candidates.append(
                    QualityCandidate(
                        call_key=root.call_key,
                        turn=root.turn,
                        trace_id=root.trace_id,
                        issue_code=code,
                        issue_label=labels[code],
                        safe_value=(
                            "transcript_empty=true" if code == "STT_EMPTY_TRANSCRIPT" else code
                        ),
                        status=stage.status,
                    )
                )

        eligible_count = len(grouped)
        issues = tuple(
            QualityIssue(
                code=code,
                label=label,
                severity=severities[code],
                affected_count=issue_counts[code],
                eligible_count=issue_eligible_counts[code],
                rate=(
                    None
                    if issue_eligible_counts[code] == 0
                    else issue_counts[code] / issue_eligible_counts[code]
                ),
            )
            for code, label, _severity in _QUALITY_DEFINITIONS[normalized_component]
        )
        coverage_fields = {
            "Confidence below threshold": "confidence",
            "STT first partial": "first_partial_ms",
            "VAD end reason": "vad_end_reason",
            "429 breakdown": "provider_http_status",
            "Retry": "retry_count",
            "Barge-in": "barge_in",
            "TTS TTFA": "ttfa_ms",
        }
        stages = [stage for _root, stage, _issues in units]
        coverage = tuple(
            QualityCoverage(
                metric=metric,
                instrumentation_status=(
                    "INSTRUMENTED"
                    if (field := coverage_fields.get(metric)) is not None
                    and any(field in stage.attributes for stage in stages)
                    else "NOT_INSTRUMENTED"
                ),
                detail=(
                    "Available in current trace window."
                    if field is not None and any(field in stage.attributes for stage in stages)
                    else detail
                ),
            )
            for metric, detail in _QUALITY_COVERAGE[normalized_component]
        )
        return QualityResult(
            component=normalized_component,
            aggregation=aggregation,
            eligible_count=eligible_count,
            affected_count=affected_count,
            clean_count=eligible_count - affected_count,
            affected_rate=None if eligible_count == 0 else affected_count / eligible_count,
            issues=issues,
            coverage=coverage,
            candidates=tuple(candidates[:candidate_limit]),
        )

    def executions(self, spans: Iterable[CompletedSpan]) -> tuple[TurnExecution, ...]:
        by_trace: dict[str, list[CompletedSpan]] = defaultdict(list)
        for span in spans:
            by_trace[span.trace_id].append(span)
        executions: list[TurnExecution] = []
        for trace_spans in by_trace.values():
            roots = [
                span
                for span in trace_spans
                if span.component == "TURN" and span.parent_span_id is None
            ]
            for root in sorted(roots, key=lambda span: (span.start_time, span.span_id)):
                executions.append(_execution(root, trace_spans))
        return tuple(
            sorted(
                executions,
                key=lambda item: (item.turn, item.start_time, item.trace_id),
            )
        )

    def call_detail(self, spans: Iterable[CompletedSpan], call_key: str) -> CallDetail:
        records = [span for span in spans if span.call_key == call_key]
        executions = self.executions(records)
        return CallDetail(
            call_key=call_key,
            turns=executions,
            total_executions=len(executions),
        )

    def _component_metrics(
        self, component: str, spans: Sequence[CompletedSpan]
    ) -> ComponentMetrics:
        errors = sum(span.status == "ERROR" for span in spans)
        return ComponentMetrics(
            component=component,
            count=len(spans),
            error_count=errors,
            error_rate=rate_metric(errors, len(spans)),
            latency=latency_stats(span.duration_ms for span in spans),
        )

    def _provider_metrics(self, spans: Iterable[CompletedSpan]) -> tuple[ProviderModelMetrics, ...]:
        groups: dict[tuple[str, str, str], list[CompletedSpan]] = defaultdict(list)
        for span in spans:
            if span.component in _PROVIDER_COMPONENTS:
                groups[(span.component, _label(span, "provider"), _label(span, "model"))].append(
                    span
                )
        rows: list[ProviderModelMetrics] = []
        for (component, provider, model), records in sorted(groups.items()):
            errors = sum(span.status == "ERROR" for span in records)
            rows.append(
                ProviderModelMetrics(
                    component=component,
                    provider=provider,
                    model=model,
                    count=len(records),
                    error_count=errors,
                    error_rate=rate_metric(errors, len(records)),
                    latency=latency_stats(span.duration_ms for span in records),
                )
            )
        return tuple(rows)

    def _stt_empty(self, spans: Iterable[CompletedSpan]) -> RateMetric:
        values = [
            value
            for span in spans
            if isinstance((value := span.attributes.get("transcript_empty")), bool)
        ]
        return rate_metric(sum(values), len(values))

    def _hourly(
        self, spans: Iterable[CompletedSpan], slow_turn_threshold_ms: float
    ) -> tuple[HourlyBucket, ...]:
        groups: dict[datetime, list[CompletedSpan]] = defaultdict(list)
        for span in spans:
            started = parse_timestamp(span.start_time)
            hour = started.replace(minute=0, second=0, microsecond=0)
            groups[hour].append(span)
        buckets: list[HourlyBucket] = []
        for hour, records in sorted(groups.items()):
            turns = [span for span in records if span.component == "TURN"]
            stt = [span for span in records if span.component == "STT"]
            core = [span for span in records if span.component == "CORE"]
            tts = [span for span in records if span.component == "TTS"]
            buckets.append(
                HourlyBucket(
                    start_time=_iso_utc(hour),
                    turn_count=len(turns),
                    turn_error_count=sum(span.status == "ERROR" for span in turns),
                    slow_turn_count=sum(
                        span.duration_ms >= slow_turn_threshold_ms for span in turns
                    ),
                    turn_p95_ms=percentile([span.duration_ms for span in turns], 0.95),
                    stt_count=len(stt),
                    stt_p95_ms=percentile([span.duration_ms for span in stt], 0.95),
                    core_count=len(core),
                    core_p95_ms=percentile([span.duration_ms for span in core], 0.95),
                    tts_count=len(tts),
                    tts_p95_ms=percentile([span.duration_ms for span in tts], 0.95),
                    stt_empty=self._stt_empty(stt),
                )
            )
        return tuple(buckets)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
