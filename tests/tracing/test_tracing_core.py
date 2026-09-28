import base64
import hashlib
import hmac
import json
import logging
from dataclasses import replace

import pytest
from pydantic import SecretStr

from callbot.engine.errors import ClinicAPIError, TurnOutOfOrder
from callbot.tracing import SafeAttributes, Tracer
from callbot.tracing.config import TracingSettings, create_tracer
from callbot.tracing.errors import classify_exception
from callbot.tracing.jsonl_sink import JsonlTraceSink
from callbot.tracing.models import CompletedSpan, TraceEvent
from callbot.tracing.privacy import UnsafeTraceData
from callbot.tracing.pseudonym import CallKeyFactory


class MemorySink:
    def __init__(self) -> None:
        self.spans: list[CompletedSpan] = []

    def emit(self, span: CompletedSpan) -> None:
        self.spans.append(span)


def _factory(environment: str = "test", key: str = "k" * 32) -> CallKeyFactory:
    return CallKeyFactory(key, version="v1", environment=environment)


def test_call_key_is_stable_separated_and_matches_hmac_contract() -> None:
    call_id = "raw-call-123"
    factory = _factory()
    first = factory.create(call_id)
    digest = hmac.new(b"k" * 32, b"test\0raw-call-123", hashlib.sha256).digest()[:16]
    expected = "ck_v1_" + base64.urlsafe_b64encode(digest).decode().rstrip("=")

    assert first.startswith("ck_v1_")
    assert first == factory.create(call_id)
    assert first != factory.create("another-call")
    assert first != _factory(environment="production").create(call_id)
    assert first != _factory(key="z" * 32).create(call_id)
    assert first == expected
    assert call_id not in first


def test_safe_attributes_default_drop_rejects_unknown_and_objects() -> None:
    with pytest.raises(UnsafeTraceData):
        SafeAttributes({"transcript": "secret"})
    with pytest.raises(UnsafeTraceData):
        SafeAttributes.for_span(transcript="secret")
    with pytest.raises(UnsafeTraceData):
        SafeAttributes.for_span(outcome=RuntimeError("private"))
    with pytest.raises(UnsafeTraceData):
        SafeAttributes.for_span(endpoint_template="/appointments/apt_private/confirm")
    with pytest.raises(UnsafeTraceData):
        SafeAttributes.for_event("policy.decision", arbitrary="secret")


def test_export_boundary_rejects_forged_completed_span(caplog: pytest.LogCaptureFixture) -> None:
    sink = MemorySink()
    tracer = Tracer(sink, _factory())
    forged = CompletedSpan(
        trace_id="0" * 32,
        span_id="1" * 16,
        parent_span_id=None,
        call_key="ck_v1_safe",
        turn=1,
        component="TURN",
        operation="http.call_turn",
        start_time="2026-01-01T00:00:00Z",
        end_time="2026-01-01T00:00:01Z",
        duration_ms=1000.0,
        status="OK",
        attributes={"transcript": "private"},
        events=(
            TraceEvent(
                name="policy.decision",
                timestamp="2026-01-01T00:00:00Z",
                attributes={"arbitrary": "private"},
            ),
        ),
    )

    with caplog.at_level(logging.WARNING):
        tracer._emit(forged)

    assert sink.spans == []
    assert "TRACE_SINK_WRITE_FAILED" in caplog.text
    assert "private" not in caplog.text


def test_export_boundary_rejects_forged_time_duration_and_result_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = MemorySink()
    tracer = Tracer(sink, _factory())
    canary = "patient-private-canary"
    base = CompletedSpan(
        trace_id="0" * 32,
        span_id="1" * 16,
        parent_span_id=None,
        call_key="ck_v1_safe",
        turn=1,
        component="TURN",
        operation="http.call_turn",
        start_time="2026-01-01T00:00:00Z",
        end_time="2026-01-01T00:00:01.123456Z",
        duration_ms=1000.0,
        status="OK",
    )
    forged = (
        replace(base, start_time=canary),
        replace(base, end_time=canary),
        replace(base, duration_ms=-1),
        replace(
            base,
            events=(TraceEvent("policy.decision", canary, {"stage": "signals"}),),
        ),
        replace(base, attributes={"result_code": "PATIENT_PRIVATE_123"}),
    )

    with caplog.at_level(logging.WARNING):
        for span in forged:
            tracer._emit(span)

    assert sink.spans == []
    assert "TRACE_SINK_WRITE_FAILED" in caplog.text
    assert canary not in caplog.text


def test_invalid_attributes_error_code_and_event_are_fail_open(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = MemorySink()
    tracer = Tracer(sink, _factory())
    canary = "private-trace-canary"

    with caplog.at_level(logging.WARNING):
        with tracer.start_trace(
            call_id="raw-call", turn=1, component="TURN", operation="http.call_turn"
        ) as span:
            span.enrich(transcript=canary)
            span.set_error_code("INTERNAL", "PRIVATE_ERROR_CODE")
            span.event("policy.decision", arbitrary=canary)

    assert len(sink.spans) == 1
    assert sink.spans[0].status == "ERROR"
    assert canary not in json.dumps(sink.spans[0].to_dict())
    assert "TRACE_ATTRIBUTE_REJECTED" in caplog.text
    assert "TRACE_EVENT_REJECTED" in caplog.text


def test_span_schema_hierarchy_duration_and_no_exception_message() -> None:
    sink = MemorySink()
    tracer = Tracer(sink, _factory())
    secret = "exception-private-message"

    with pytest.raises(RuntimeError):
        with tracer.start_trace(
            call_id="raw-call", turn=4, component="TURN", operation="http.call_turn"
        ):
            with tracer.span(component="CORE", operation="core.handle_turn") as child:
                child.set_safe_attributes(SafeAttributes.for_span(state_before="AWAITING_INTENT"))
                raise RuntimeError(secret)

    child_record, root_record = sink.spans
    assert child_record.trace_id == root_record.trace_id
    assert child_record.call_key == root_record.call_key
    assert child_record.turn == root_record.turn == 4
    assert child_record.parent_span_id == root_record.span_id
    assert root_record.parent_span_id is None
    assert child_record.status == root_record.status == "ERROR"
    assert child_record.duration_ms >= 0 and root_record.duration_ms >= 0
    assert child_record.to_dict()["schema_version"] == "trace.v1"
    assert secret not in json.dumps([span.to_dict() for span in sink.spans])


def test_sink_failure_is_fail_open(caplog: pytest.LogCaptureFixture) -> None:
    class BrokenSink:
        def emit(self, span: CompletedSpan) -> None:
            del span
            raise OSError("disk secret")

    tracer = Tracer(BrokenSink(), _factory(key="secret-key-material-12345678901234"))
    with caplog.at_level(logging.WARNING):
        with tracer.start_trace(
            call_id="private-call", turn=1, component="TURN", operation="http.call_turn"
        ):
            pass
    assert "TRACE_SINK_WRITE_FAILED" in caplog.text
    assert "private-call" not in caplog.text
    assert "secret-key-material" not in caplog.text
    assert "disk secret" not in caplog.text


@pytest.mark.parametrize(
    ("exc", "error_type", "error_code"),
    [
        (TurnOutOfOrder("private", 3, 2), "VALIDATION", "TURN_OUT_OF_ORDER"),
        (ClinicAPIError(None, "TIMEOUT", "private"), "TIMEOUT", "CLINIC_TIMEOUT"),
        (
            ClinicAPIError(None, "CONNECT_ERROR", "private"),
            "UPSTREAM",
            "CLINIC_CONNECT_ERROR",
        ),
        (
            ClinicAPIError(409, "VERSION_CONFLICT", "private"),
            "VERSION_CONFLICT",
            "CLINIC_VERSION_CONFLICT",
        ),
        (ClinicAPIError(422, "INVALID", "private"), "UPSTREAM", "CLINIC_REJECTED"),
    ],
)
def test_domain_errors_map_to_stable_codes(exc, error_type: str, error_code: str) -> None:
    info = classify_exception(exc)
    assert (info.error_type, info.error_code) == (error_type, error_code)


def test_disabled_does_not_require_secret_or_emit(tmp_path) -> None:
    tracer = create_tracer(
        TracingSettings(
            enabled=False,
            jsonl_dir=tmp_path,
            pseudonymization_key=SecretStr(""),
        )
    )
    with tracer.start_trace(
        call_id="private", turn=1, component="TURN", operation="http.call_turn"
    ) as span:
        assert not span.enabled
    assert list(tmp_path.iterdir()) == []


def test_invalid_enabled_config_is_static_and_secret_safe(
    tmp_path, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "too-short-private"
    with caplog.at_level(logging.WARNING):
        tracer = create_tracer(
            TracingSettings(
                enabled=True,
                jsonl_dir=tmp_path,
                pseudonymization_key=SecretStr(secret),
            )
        )
    assert not tracer.enabled
    assert "TRACE_CONFIG_INVALID" in caplog.text
    assert secret not in caplog.text


def test_jsonl_lines_are_independent_rotated_and_pid_scoped(tmp_path) -> None:
    first = JsonlTraceSink(tmp_path, max_file_bytes=1, pid=101)
    second = JsonlTraceSink(tmp_path, pid=202)
    tracer_a = Tracer(first, _factory())
    tracer_b = Tracer(second, _factory())

    for tracer, turn in ((tracer_a, 1), (tracer_a, 2), (tracer_b, 3)):
        with tracer.start_trace(
            call_id="same-call", turn=turn, component="TURN", operation="http.call_turn"
        ):
            pass

    paths = list(tmp_path.glob("*.jsonl"))
    assert any("p101" in path.name for path in paths)
    assert any("p202" in path.name for path in paths)
    records = [json.loads(line) for path in paths for line in path.read_text().splitlines()]
    assert len(records) == 3
    assert all(record["schema_version"] == "trace.v1" for record in records)
    assert all(record["record_type"] == "span" for record in records)


def test_jsonl_cleanup_is_throttled_per_process(tmp_path, monkeypatch) -> None:
    sink = JsonlTraceSink(tmp_path, cleanup_interval_s=3600)
    tracer = Tracer(sink, _factory())
    cleanup_calls = 0

    def count_cleanup() -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1

    monkeypatch.setattr(sink, "_cleanup", count_cleanup)
    for turn in (1, 2):
        with tracer.start_trace(
            call_id="same-call", turn=turn, component="TURN", operation="http.call_turn"
        ):
            pass

    assert cleanup_calls == 1
