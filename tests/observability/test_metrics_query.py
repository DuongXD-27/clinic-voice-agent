from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from callbot.observability import (
    JsonlSpanSource,
    MetricsAggregator,
    MetricsQueryService,
    SourceDiagnostics,
    latency_stats,
    percentile,
)
from callbot.tracing.models import CompletedSpan, TraceEvent

UTC = timezone.utc
WINDOW_START = datetime(2026, 1, 1, tzinfo=UTC)
WINDOW_END = WINDOW_START + timedelta(days=1)
OPERATIONS = {
    "TURN": "http.call_turn",
    "STT": "speech.stt.transcribe",
    "CORE": "core.handle_turn",
    "TTS": "speech.tts.synthesize",
    "CLINIC": "clinic.get_appointment",
    "EXTRACTION": "core.extract",
    "DIALOGUE": "core.dialogue",
}


def _id(value: int, width: int) -> str:
    return f"{value:0{width}x}"[-width:]


def _span(
    component: str,
    *,
    trace: int = 1,
    span: int = 1,
    parent: int | None = None,
    call_key: str = "ck_v1_call_a",
    turn: int = 0,
    hour: int = 0,
    minute: int = 0,
    duration_ms: float = 100.0,
    status: str = "OK",
    attributes: dict[str, object] | None = None,
    events: tuple[TraceEvent, ...] = (),
) -> CompletedSpan:
    started = WINDOW_START + timedelta(hours=hour, minutes=minute)
    ended = started + timedelta(milliseconds=duration_ms)
    return CompletedSpan(
        trace_id=_id(trace, 32),
        span_id=_id(span, 16),
        parent_span_id=None if parent is None else _id(parent, 16),
        call_key=call_key,
        turn=turn,
        component=component,
        operation=OPERATIONS[component],
        start_time=started.isoformat().replace("+00:00", "Z"),
        end_time=ended.isoformat().replace("+00:00", "Z"),
        duration_ms=duration_ms,
        status=status,
        attributes=attributes or {},
        events=events,
    )


class MemorySource:
    def __init__(self, spans: list[CompletedSpan]) -> None:
        self._spans = spans
        self._diagnostics = SourceDiagnostics(records_seen=len(spans))

    @property
    def diagnostics(self) -> SourceDiagnostics:
        return self._diagnostics

    def query(self, start_time: datetime, end_time: datetime):
        for span in self._spans:
            started = datetime.fromisoformat(span.start_time.replace("Z", "+00:00"))
            if start_time <= started < end_time:
                yield span


@pytest.mark.parametrize(
    ("values", "quantile", "expected"),
    [
        ([], 0.50, None),
        ([7], 0.50, 7.0),
        ([1, 2], 0.50, 1.0),
        ([1, 2], 0.95, 2.0),
        ([5, 1, 4, 2, 3], 0.50, 3.0),
        ([1, 2, 3, 4], 0.50, 2.0),
        (list(range(1, 101)), 0.95, 95.0),
        (list(range(1, 101)), 0.99, 99.0),
    ],
)
def test_nearest_rank_percentile_is_deterministic(values, quantile, expected) -> None:
    assert percentile(values, quantile) == expected


def test_latency_stats_empty_and_mean() -> None:
    assert latency_stats([]).to_dict() == {
        "count": 0,
        "p50_ms": None,
        "p95_ms": None,
        "p99_ms": None,
        "min_ms": None,
        "max_ms": None,
        "mean_ms": None,
    }
    stats = latency_stats([10, 20, 30, 40])
    assert stats.p50_ms == 20
    assert stats.p95_ms == 40
    assert stats.mean_ms == 25


def test_jsonl_source_streams_multi_process_rotation_and_skips_bad_records(tmp_path) -> None:
    first = _span("TURN", trace=1, span=1, hour=0).to_dict()
    second = _span("TURN", trace=2, span=2, hour=1).to_dict()
    third = _span("TURN", trace=3, span=3, hour=2).to_dict()
    outside = _span("TURN", trace=4, span=4, hour=4).to_dict()
    unsupported = dict(first, schema_version="trace.v2")
    forbidden = dict(first, transcript="private-canary")

    (tmp_path / "trace-20260101-p101.jsonl").write_text(
        "\n".join((json.dumps(first), "{bad json", json.dumps(unsupported))) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "trace-20260101-p101-1.jsonl").write_text(
        "\n".join((json.dumps(second), json.dumps(forbidden))) + "\n", encoding="utf-8"
    )
    (tmp_path / "trace-20260101-p202.jsonl").write_text(
        "\n".join((json.dumps(third), json.dumps(outside))) + "\n", encoding="utf-8"
    )
    (tmp_path / "not-a-trace.jsonl").write_text(json.dumps(first), encoding="utf-8")

    source = JsonlSpanSource(tmp_path)
    records = list(source.query(WINDOW_START, WINDOW_START + timedelta(hours=3)))

    assert sorted(record.trace_id for record in records) == [
        _id(1, 32),
        _id(2, 32),
        _id(3, 32),
    ]
    assert source.diagnostics.files_read == 3
    assert source.diagnostics.records_seen == 7
    assert source.diagnostics.records_yielded == 3
    assert source.diagnostics.records_skipped == 2
    assert source.diagnostics.unsupported_records == 1


def test_jsonl_source_requires_aware_valid_window(tmp_path) -> None:
    source = JsonlSpanSource(tmp_path)
    with pytest.raises(ValueError, match="timezone-aware"):
        list(source.query(datetime(2026, 1, 1), WINDOW_END))
    with pytest.raises(ValueError, match="after"):
        list(source.query(WINDOW_END, WINDOW_START))


def test_overview_rates_provider_groups_and_missing_empty_signal() -> None:
    spans: list[CompletedSpan] = []
    for index in range(10):
        status = "ERROR" if index in {0, 1} else "CANCELLED" if index == 2 else "OK"
        attributes: dict[str, object] = {
            "provider": "asr-a" if index < 5 else "asr-b",
            "model": "model-a" if index < 5 else "model-b",
        }
        if index < 8:
            attributes["transcript_empty"] = index in {0, 3}
        if status == "ERROR":
            attributes["error_code"] = "STT_PROVIDER_ERROR"
        spans.extend(
            [
                _span(
                    "TURN",
                    trace=100 + index,
                    span=1000 + index,
                    turn=index,
                    duration_ms=1000 + index * 250,
                    status="ERROR" if index == 0 else "OK",
                ),
                _span(
                    "STT",
                    trace=100 + index,
                    span=2000 + index,
                    parent=1000 + index,
                    turn=index,
                    duration_ms=10 + index,
                    status=status,
                    attributes=attributes,
                ),
            ]
        )

    overview = MetricsQueryService(MemorySource(spans)).get_overview(
        WINDOW_START, WINDOW_END, slow_turn_threshold_ms=2000
    )

    stt = next(row for row in overview.component_metrics if row.component == "STT")
    assert overview.turn_count == 10
    assert overview.turn_latency.p50_ms == 2000
    assert overview.turn_latency.p95_ms == 3250
    assert overview.slow_turns.to_dict() == {"numerator": 6, "denominator": 10, "rate": 0.6}
    assert overview.turn_errors.to_dict() == {
        "numerator": 1,
        "denominator": 10,
        "rate": 0.1,
    }
    assert stt.count == 10
    assert stt.error_count == 2
    assert stt.error_rate.rate == 0.2
    assert overview.stt_empty.to_dict() == {"numerator": 2, "denominator": 8, "rate": 0.25}
    assert [(row.provider, row.model, row.count) for row in overview.provider_model_metrics] == [
        ("asr-a", "model-a", 5),
        ("asr-b", "model-b", 5),
    ]


def _quality_spans() -> list[CompletedSpan]:
    return [
        _span("TURN", trace=201, span=2010, call_key="ck_v1_call_a", turn=1),
        _span(
            "STT",
            trace=201,
            span=2011,
            parent=2010,
            call_key="ck_v1_call_a",
            turn=1,
            status="ERROR",
            attributes={"transcript_empty": True, "error_code": "STT_PROVIDER_ERROR"},
        ),
        _span("TURN", trace=202, span=2020, call_key="ck_v1_call_a", turn=2),
        _span(
            "STT",
            trace=202,
            span=2021,
            parent=2020,
            call_key="ck_v1_call_a",
            turn=2,
            attributes={"transcript_empty": True},
        ),
        _span("TURN", trace=203, span=2030, call_key="ck_v1_call_b", turn=1),
        _span(
            "STT",
            trace=203,
            span=2031,
            parent=2030,
            call_key="ck_v1_call_b",
            turn=1,
            attributes={"transcript_empty": False},
        ),
        _span(
            "TTS",
            trace=203,
            span=2032,
            parent=2030,
            call_key="ck_v1_call_b",
            turn=1,
            status="ERROR",
            attributes={"error_code": "TTS_STORAGE_ERROR"},
        ),
        _span("TURN", trace=204, span=2040, call_key="ck_v1_without_speech", turn=1),
    ]


def test_quality_by_call_deduplicates_repeated_and_multi_issue_executions() -> None:
    result = MetricsQueryService(MemorySource(_quality_spans())).get_quality(
        WINDOW_START,
        WINDOW_END,
        component="STT",
        aggregation="call",
    )

    issue_counts = {item.code: item.affected_count for item in result.issues}
    assert result.eligible_count == 2
    assert result.affected_count == 1
    assert result.clean_count == 1
    assert result.affected_rate == 0.5
    assert issue_counts["STT_EMPTY_TRANSCRIPT"] == 1
    assert issue_counts["STT_PROVIDER_ERROR"] == 1
    assert len(result.candidates) == 2
    assert {candidate.call_key for candidate in result.candidates} == {"ck_v1_call_a"}


def test_quality_by_turn_counts_each_execution_and_not_each_issue() -> None:
    result = MetricsQueryService(MemorySource(_quality_spans())).get_quality(
        WINDOW_START,
        WINDOW_END,
        component="STT",
        aggregation="turn",
    )

    issue_counts = {item.code: item.affected_count for item in result.issues}
    assert result.eligible_count == 3
    assert result.affected_count == 2
    assert result.clean_count == 1
    assert result.affected_rate == pytest.approx(2 / 3)
    assert issue_counts["STT_EMPTY_TRANSCRIPT"] == 2
    assert issue_counts["STT_PROVIDER_ERROR"] == 1
    assert len(result.candidates) == 3


def test_quality_separates_stt_and_tts_and_exposes_only_safe_candidates() -> None:
    result = MetricsQueryService(MemorySource(_quality_spans())).get_quality(
        WINDOW_START,
        WINDOW_END,
        component="TTS",
        aggregation="call",
    )

    issue_counts = {item.code: item.affected_count for item in result.issues}
    assert result.eligible_count == 1
    assert result.affected_count == 1
    assert issue_counts == {
        "TTS_TIMEOUT": 0,
        "TTS_PROVIDER_ERROR": 0,
        "TTS_STORAGE_ERROR": 1,
    }
    payload = result.to_dict()
    rendered = json.dumps(payload)
    assert "STT_EMPTY_TRANSCRIPT" not in rendered
    for forbidden in ("transcript", "patient_id", "appointment_id", "audio_url"):
        assert f'"{forbidden}"' not in rendered


def test_quality_no_eligible_data_is_distinct_from_clean_data() -> None:
    no_data = MetricsAggregator().quality([], component="STT", aggregation="call")
    clean = MetricsAggregator().quality(_quality_spans()[4:6], component="STT", aggregation="call")

    assert no_data.eligible_count == 0
    assert no_data.affected_rate is None
    assert clean.eligible_count == 1
    assert clean.affected_count == 0
    assert clean.clean_count == 1
    assert clean.affected_rate == 0
    assert all(item.instrumentation_status == "NOT_INSTRUMENTED" for item in clean.coverage)


def test_empty_transcript_keeps_its_instrumented_sample_denominator() -> None:
    spans = [
        _span("TURN", trace=301, span=3010, call_key="ck_v1_error", turn=1),
        _span(
            "STT",
            trace=301,
            span=3011,
            parent=3010,
            call_key="ck_v1_error",
            turn=1,
            status="ERROR",
            attributes={"error_code": "STT_PROVIDER_ERROR"},
        ),
        _span("TURN", trace=302, span=3020, call_key="ck_v1_clean", turn=1),
        _span(
            "STT",
            trace=302,
            span=3021,
            parent=3020,
            call_key="ck_v1_clean",
            turn=1,
            attributes={"transcript_empty": False},
        ),
    ]
    result = MetricsAggregator().quality(spans, component="STT", aggregation="call")
    issues = {item.code: item for item in result.issues}

    assert result.eligible_count == 2
    assert issues["STT_EMPTY_TRANSCRIPT"].eligible_count == 1
    assert issues["STT_EMPTY_TRANSCRIPT"].rate == 0
    assert issues["STT_PROVIDER_ERROR"].eligible_count == 2
    assert issues["STT_PROVIDER_ERROR"].rate == 0.5


def test_quality_replay_is_an_execution_by_turn_and_deduplicated_by_call() -> None:
    spans = [
        _span("TURN", trace=401, span=4010, call_key="ck_v1_replay", turn=1),
        _span(
            "STT",
            trace=401,
            span=4011,
            parent=4010,
            call_key="ck_v1_replay",
            turn=1,
            attributes={"transcript_empty": True},
        ),
        _span(
            "TURN",
            trace=402,
            span=4020,
            call_key="ck_v1_replay",
            turn=1,
            attributes={"replayed": True},
        ),
        _span(
            "STT",
            trace=402,
            span=4021,
            parent=4020,
            call_key="ck_v1_replay",
            turn=1,
            attributes={"transcript_empty": True},
        ),
    ]
    by_call = MetricsAggregator().quality(spans, component="STT", aggregation="call")
    by_turn = MetricsAggregator().quality(spans, component="STT", aggregation="turn")

    assert (by_call.eligible_count, by_call.affected_count) == (1, 1)
    assert (by_turn.eligible_count, by_turn.affected_count) == (2, 2)


def test_missing_provider_model_use_explicit_safe_bucket() -> None:
    overview = MetricsQueryService(MemorySource([_span("TTS")])).get_overview(
        WINDOW_START, WINDOW_END
    )
    row = overview.provider_model_metrics[0]
    assert (row.provider, row.model) == ("UNSPECIFIED", "UNSPECIFIED")


def test_overview_exposes_each_supported_stage_latency_and_provider_error_rate() -> None:
    spans = [
        _span("TURN", trace=90, span=900, duration_ms=100),
        _span(
            "STT",
            trace=90,
            span=901,
            parent=900,
            duration_ms=10,
            status="ERROR",
            attributes={
                "provider": "asr-provider",
                "model": "asr-model",
                "error_code": "STT_PROVIDER_ERROR",
            },
        ),
        _span("CORE", trace=90, span=902, parent=900, duration_ms=20),
        _span(
            "TTS",
            trace=90,
            span=903,
            parent=900,
            duration_ms=30,
            status="ERROR",
            attributes={
                "provider": "tts-provider",
                "model": "tts-model",
                "error_code": "TTS_PROVIDER_ERROR",
            },
        ),
        _span("CLINIC", trace=90, span=904, parent=902, duration_ms=40),
    ]

    overview = MetricsQueryService(MemorySource(spans)).get_overview(WINDOW_START, WINDOW_END)

    assert (
        overview.turn_latency.p50_ms,
        overview.turn_latency.p95_ms,
        overview.turn_latency.p99_ms,
    ) == (100, 100, 100)
    assert overview.stt_latency.p95_ms == 10
    assert overview.core_latency.p95_ms == 20
    assert overview.tts_latency.p95_ms == 30
    assert overview.clinic_latency.p95_ms == 40
    assert [
        (row.component, row.provider, row.model, row.error_count, row.error_rate.rate)
        for row in overview.provider_model_metrics
    ] == [
        ("STT", "asr-provider", "asr-model", 1, 1.0),
        ("TTS", "tts-provider", "tts-model", 1, 1.0),
    ]


def test_hourly_trend_uses_utc_buckets_and_raw_counts() -> None:
    spans: list[CompletedSpan] = []
    for hour, duration, status, empty in (
        (0, 1000, "OK", False),
        (1, 3000, "ERROR", True),
        (2, 2500, "OK", None),
    ):
        attributes = {"provider": "fake", "model": "fake-v1"}
        if empty is not None:
            attributes["transcript_empty"] = empty
        if status == "ERROR":
            attributes["error_code"] = "STT_PROVIDER_ERROR"
        spans.extend(
            [
                _span(
                    "TURN",
                    trace=hour + 1,
                    span=hour + 10,
                    hour=hour,
                    duration_ms=duration,
                    status=status,
                ),
                _span(
                    "STT",
                    trace=hour + 1,
                    span=hour + 20,
                    parent=hour + 10,
                    hour=hour,
                    attributes=attributes,
                ),
            ]
        )

    hourly = (
        MetricsQueryService(MemorySource(spans))
        .get_overview(WINDOW_START, WINDOW_END, slow_turn_threshold_ms=2000)
        .hourly
    )

    assert [bucket.start_time for bucket in hourly] == [
        "2026-01-01T00:00:00Z",
        "2026-01-01T01:00:00Z",
        "2026-01-01T02:00:00Z",
    ]
    assert [bucket.turn_count for bucket in hourly] == [1, 1, 1]
    assert [bucket.turn_error_count for bucket in hourly] == [0, 1, 0]
    assert [bucket.slow_turn_count for bucket in hourly] == [0, 1, 1]
    assert hourly[0].stt_empty.rate == 0
    assert hourly[1].stt_empty.rate == 1
    assert hourly[2].stt_empty.rate is None


def _call_spans() -> list[CompletedSpan]:
    replay_event = TraceEvent(
        "session.replayed",
        "2026-01-01T00:02:00Z",
        {"replayed": True, "terminal": False, "storage_status": "OK", "turn_ordering": "OK"},
    )
    spans = [
        _span("TURN", trace=1, span=10, turn=0, minute=0, duration_ms=100),
        _span("CORE", trace=1, span=11, parent=10, turn=0, minute=0, duration_ms=80),
        _span("TURN", trace=2, span=20, turn=1, minute=1, duration_ms=3000),
        _span(
            "STT",
            trace=2,
            span=21,
            parent=20,
            turn=1,
            minute=1,
            duration_ms=500,
            attributes={
                "provider": "fake-asr",
                "model": "asr-v1",
                "transcript_empty": False,
            },
        ),
        _span("CORE", trace=2, span=22, parent=20, turn=1, minute=1, duration_ms=1500),
        _span("EXTRACTION", trace=2, span=25, parent=22, turn=1, minute=1, duration_ms=100),
        _span("DIALOGUE", trace=2, span=26, parent=22, turn=1, minute=1, duration_ms=200),
        _span(
            "CLINIC",
            trace=2,
            span=23,
            parent=22,
            turn=1,
            minute=1,
            duration_ms=300,
            status="ERROR",
            attributes={"error_code": "CLINIC_TIMEOUT"},
        ),
        _span(
            "TTS",
            trace=2,
            span=24,
            parent=20,
            turn=1,
            minute=1,
            duration_ms=700,
            attributes={"provider": "fake-tts", "model": "tts-v1"},
        ),
        _span("TURN", trace=3, span=30, turn=2, minute=2, duration_ms=2100),
        _span("CORE", trace=3, span=31, parent=30, turn=2, minute=2),
        _span(
            "TURN",
            trace=4,
            span=40,
            turn=2,
            minute=3,
            duration_ms=2200,
            events=(replay_event,),
        ),
        _span("CORE", trace=4, span=41, parent=40, turn=2, minute=3),
    ]
    return list(reversed(spans))


def test_call_and_turn_queries_reconstruct_by_ids_and_preserve_replays() -> None:
    spans = _call_spans()
    spans.append(
        _span(
            "TURN",
            trace=99,
            span=99,
            call_key="ck_v1_call_b",
            turn=0,
            duration_ms=9999,
        )
    )
    service = MetricsQueryService(MemorySource(spans))

    call = service.get_call("ck_v1_call_a", WINDOW_START, WINDOW_END)
    turn = service.get_turn(_id(2, 32), WINDOW_START, WINDOW_END)

    assert [(item.turn, item.trace_id) for item in call.turns] == [
        (0, _id(1, 32)),
        (1, _id(2, 32)),
        (2, _id(3, 32)),
        (2, _id(4, 32)),
    ]
    assert call.turns[-1].replayed is True
    assert turn is not None
    assert turn.stt is not None and turn.stt.provider == "fake-asr"
    assert turn.core is not None
    assert turn.tts is not None and turn.tts.model == "tts-v1"
    assert len(turn.clinic) == 1
    assert turn.clinic[0].operation == "clinic.get_appointment"
    assert turn.clinic[0].error_code == "CLINIC_TIMEOUT"
    assert turn.error_codes == ("CLINIC_TIMEOUT",)


def test_slow_turns_and_top_errors_are_safe_and_deterministic() -> None:
    spans = _call_spans()
    spans.append(
        _span(
            "TTS",
            trace=5,
            span=50,
            status="ERROR",
            attributes={
                "provider": "fake-tts",
                "model": "tts-v1",
                "error_code": "TTS_PROVIDER_ERROR",
            },
        )
    )
    spans.append(
        _span(
            "TTS",
            trace=6,
            span=60,
            status="ERROR",
            attributes={
                "provider": "fake-tts",
                "model": "tts-v1",
                "error_code": "TTS_PROVIDER_ERROR",
            },
        )
    )
    service = MetricsQueryService(MemorySource(spans))

    slow = service.list_slow_turns(WINDOW_START, WINDOW_END, slow_turn_threshold_ms=2000, limit=2)
    errors = service.top_errors(WINDOW_START, WINDOW_END)

    assert [row.duration_ms for row in slow] == [3000, 2200]
    assert [(row.component, row.error_code, row.count) for row in errors] == [
        ("TTS", "TTS_PROVIDER_ERROR", 2),
        ("CLINIC", "CLINIC_TIMEOUT", 1),
    ]


def test_public_dtos_are_closed_and_do_not_leak_raw_fields(tmp_path) -> None:
    safe = _span(
        "TURN",
        attributes={"text_length_bucket": "large", "idempotency_used": True},
    ).to_dict()
    malicious = dict(safe)
    malicious.update(
        {
            "raw_call_id": "raw-call-canary",
            "name": "name-canary",
            "dob": "dob-canary",
            "phone": "phone-canary",
            "patient_id": "patient-canary",
            "appointment_id": "appointment-canary",
            "transcript": "transcript-canary",
            "utterance": "utterance-canary",
            "audio_url": "audio-canary",
            "raw_exception": "exception-canary",
        }
    )
    path = tmp_path / "trace-20260101-p1.jsonl"
    path.write_text("\n".join((json.dumps(safe), json.dumps(malicious))) + "\n", encoding="utf-8")
    source = JsonlSpanSource(tmp_path)

    overview = MetricsQueryService(source).get_overview(WINDOW_START, WINDOW_END)
    serialized = json.dumps(overview.to_dict())

    assert overview.turn_count == 1
    assert source.diagnostics.records_skipped == 1
    for canary in (
        "raw-call-canary",
        "name-canary",
        "dob-canary",
        "phone-canary",
        "patient-canary",
        "appointment-canary",
        "transcript-canary",
        "utterance-canary",
        "audio-canary",
        "exception-canary",
    ):
        assert canary not in serialized


def test_json_ready_models_contain_no_arbitrary_attribute_dictionary() -> None:
    detail = MetricsQueryService(MemorySource(_call_spans())).get_call(
        "ck_v1_call_a", WINDOW_START, WINDOW_END
    )
    payload = detail.to_dict()

    assert isinstance(payload["turns"], list)
    assert "attributes" not in json.dumps(payload)
    assert "events" not in json.dumps(payload)


def test_aggregator_does_not_count_cancelled_as_error() -> None:
    spans = [
        _span("CORE", span=1, status="OK"),
        _span("CORE", span=2, status="ERROR", attributes={"error_code": "INTERNAL_ERROR"}),
        _span("CORE", span=3, status="CANCELLED"),
    ]
    row = (
        MetricsAggregator()
        .overview(
            spans,
            start_time=WINDOW_START,
            end_time=WINDOW_END,
            slow_turn_threshold_ms=2000,
        )
        .component_metrics[1]
    )

    assert row.component == "CORE"
    assert row.count == 3
    assert row.error_count == 1
    assert row.error_rate.rate == 1 / 3
