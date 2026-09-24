from __future__ import annotations

import json
import logging
import threading
from dataclasses import replace
from time import monotonic

import httpx
import pytest
from pydantic import SecretStr

from callbot.tracing.jsonl_sink import JsonlTraceSink
from callbot.tracing.langfuse_sink import (
    LangfuseOtlpSettings,
    LangfuseOtlpTraceSink,
    create_langfuse_sink,
)
from callbot.tracing.models import CompletedSpan, TraceEvent
from callbot.tracing.sink import CompositeTraceSink, NullTraceSink


def _span(**changes: object) -> CompletedSpan:
    base = CompletedSpan(
        trace_id="0123456789abcdef0123456789abcdef",
        span_id="0123456789abcdef",
        parent_span_id=None,
        call_key="ck_v1_synthetic",
        turn=1,
        component="TURN",
        operation="http.call_turn",
        start_time="2026-01-01T00:00:00.123456Z",
        end_time="2026-01-01T00:00:02.654321Z",
        duration_ms=2530.865,
        status="OK",
        attributes={"outcome": "CONFIRMED", "provider": "synthetic-provider"},
        events=(
            TraceEvent(
                "policy.decision",
                "2026-01-01T00:00:01Z",
                {"stage": "intent", "decision": "PROCEED"},
            ),
        ),
    )
    return replace(base, **changes)


def _recording_client(requests: list[httpx.Request], status_code: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status_code, request=request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _sink(client: httpx.Client, **changes: object) -> LangfuseOtlpTraceSink:
    options: dict[str, object] = {
        "endpoint": "https://example.langfuse.test/api/public/otel",
        "public_key": "pk-test",
        "secret_key": "sk-test",
        "environment": "test",
        "timeout_seconds": 0.1,
        "queue_size": 16,
        "batch_size": 16,
        "flush_interval_seconds": 10.0,
        "client": client,
    }
    options.update(changes)
    return LangfuseOtlpTraceSink(**options)  # type: ignore[arg-type]


def _exported_spans(request: httpx.Request) -> list[dict[str, object]]:
    body = json.loads(request.content)
    return body["resourceSpans"][0]["scopeSpans"][0]["spans"]


def _attributes(span: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for item in span["attributes"]:  # type: ignore[union-attr]
        value = item["value"]
        result[item["key"]] = next(iter(value.values()))
    return result


def test_otlp_mapping_preserves_ids_hierarchy_times_metadata_events_and_session() -> None:
    requests: list[httpx.Request] = []
    sink = _sink(_recording_client(requests))
    child = _span(
        span_id="fedcba9876543210",
        parent_span_id="0123456789abcdef",
        component="CORE",
        operation="core.handle_turn",
        status="ERROR",
        attributes={"error_type": "INTERNAL", "error_code": "INTERNAL_ERROR"},
    )
    next_turn = _span(
        trace_id="abcdef0123456789abcdef0123456789",
        span_id="1111111111111111",
        turn=2,
        status="CANCELLED",
        events=(),
    )

    for span in (_span(), child, next_turn):
        sink.emit(span)
    assert sink.flush(1.0)
    assert sink.close(1.0)

    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://example.langfuse.test/api/public/otel/v1/traces"
    assert request.headers["authorization"] == "Basic cGstdGVzdDpzay10ZXN0"
    assert request.headers["x-langfuse-ingestion-version"] == "4"
    assert request.headers["content-type"] == "application/json"
    exported = _exported_spans(request)
    root, exported_child, second = exported

    assert root["traceId"] == _span().trace_id
    assert root["spanId"] == _span().span_id
    assert "parentSpanId" not in root
    assert exported_child["parentSpanId"] == child.parent_span_id
    assert root["startTimeUnixNano"] == "1767225600123456000"
    assert root["endTimeUnixNano"] == "1767225602654321000"
    assert root["name"] == "http.call_turn"
    assert root["status"] == {"code": 1}
    assert exported_child["status"] == {"code": 2}
    assert second["status"] == {"code": 0}
    assert root["events"] == [
        {
            "timeUnixNano": "1767225601000000000",
            "name": "policy.decision",
            "attributes": [
                {"key": "stage", "value": {"stringValue": "intent"}},
                {"key": "decision", "value": {"stringValue": "PROCEED"}},
            ],
        }
    ]

    root_attributes = _attributes(root)
    child_attributes = _attributes(exported_child)
    second_attributes = _attributes(second)
    assert root_attributes["langfuse.session.id"] == "ck_v1_synthetic"
    assert child_attributes["langfuse.session.id"] == "ck_v1_synthetic"
    assert second_attributes["langfuse.session.id"] == "ck_v1_synthetic"
    assert root_attributes["langfuse.trace.name"] == "callbot.turn"
    assert root_attributes["langfuse.environment"] == "test"
    assert root_attributes["langfuse.observation.type"] == "span"
    assert root_attributes["langfuse.observation.metadata.turn"] == "1"
    assert second_attributes["langfuse.observation.metadata.turn"] == "2"
    assert root_attributes["langfuse.observation.metadata.component"] == "TURN"
    assert child_attributes["langfuse.observation.metadata.component"] == "CORE"
    assert root_attributes["langfuse.observation.metadata.operation"] == "http.call_turn"
    assert root_attributes["langfuse.observation.metadata.duration_ms"] == 2530.865
    assert child_attributes["langfuse.observation.metadata.error_code"] == "INTERNAL_ERROR"


def test_payload_has_no_input_output_user_or_raw_sensitive_data() -> None:
    requests: list[httpx.Request] = []
    sink = _sink(_recording_client(requests))
    sink.emit(_span())
    assert sink.close(1.0)

    payload = requests[0].content.decode()
    lowered = payload.lower()
    for forbidden in (
        "raw-call",
        "transcript",
        "full_name",
        "dob",
        "phone",
        "appointment_id",
        "patient_id",
        "utterance",
        "audio_url",
        "exception",
        "endpoint_template_raw",
        "langfuse.observation.input",
        "langfuse.observation.output",
        "langfuse.user.id",
        "user.id",
    ):
        assert forbidden not in lowered


@pytest.mark.parametrize(
    "forged",
    [
        _span(
            attributes={
                "full_name": "Patient Name",
                "dob": "1990-01-01",
                "phone": "0900000000",
                "patient_id": "patient-secret",
                "appointment_id": "appointment-secret",
                "transcript": "raw speech",
                "bot_utterance": "raw reply",
                "audio_url": "https://private.test/audio.wav",
                "raw_exception": "private stack",
                "raw_endpoint": "/appointments/private",
            }
        ),
        _span(
            events=(
                TraceEvent(
                    "policy.decision",
                    "2026-01-01T00:00:01Z",
                    {"transcript": "event-private"},
                ),
            )
        ),
    ],
)
def test_forged_unsafe_span_or_event_is_dropped_before_network(
    forged: CompletedSpan, caplog: pytest.LogCaptureFixture
) -> None:
    requests: list[httpx.Request] = []
    sink = _sink(_recording_client(requests))

    with caplog.at_level(logging.WARNING):
        sink.emit(forged)
        assert sink.flush(0.2)
    assert sink.close(1.0)

    assert requests == []
    assert sink.dropped_count == 1
    assert "LANGFUSE_TRACE_DROPPED_UNSAFE" in caplog.text
    for secret in ("Patient Name", "0900000000", "event-private", "private stack"):
        assert secret not in caplog.text


@pytest.mark.parametrize("status_code", [401, 403, 429, 500, 503])
def test_http_failures_are_fail_open(status_code: int, caplog: pytest.LogCaptureFixture) -> None:
    requests: list[httpx.Request] = []
    sink = _sink(_recording_client(requests, status_code))
    with caplog.at_level(logging.WARNING):
        sink.emit(_span())
        assert sink.flush(1.0)
    assert sink.close(1.0)

    assert len(requests) == 1
    assert sink.exported_count == 0
    assert "LANGFUSE_EXPORT_HTTP_FAILED" in caplog.text


@pytest.mark.parametrize("failure", ["timeout", "connect", "dns", "tls"])
def test_network_failures_are_fail_open_and_secret_safe(
    failure: str, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "sk-private-network-secret"

    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "timeout":
            raise httpx.ReadTimeout(secret, request=request)
        if failure in {"connect", "dns"}:
            raise httpx.ConnectError(secret, request=request)
        raise httpx.TransportError(secret)

    sink = _sink(httpx.Client(transport=httpx.MockTransport(handler)))
    with caplog.at_level(logging.WARNING):
        sink.emit(_span())
        assert sink.flush(1.0)
    assert sink.close(1.0)

    assert sink.exported_count == 0
    assert "LANGFUSE_EXPORT_NETWORK_FAILED" in caplog.text
    assert secret not in caplog.text


def test_queue_is_bounded_drop_newest_and_emit_does_not_wait_for_network() -> None:
    entered = threading.Event()
    release = threading.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        entered.set()
        release.wait(2.0)
        return httpx.Response(200, request=request)

    sink = _sink(
        httpx.Client(transport=httpx.MockTransport(handler)),
        queue_size=2,
        batch_size=1,
        flush_interval_seconds=0.01,
    )
    sink.emit(_span())
    assert entered.wait(1.0)
    sink.emit(replace(_span(), span_id="1111111111111111"))
    sink.emit(replace(_span(), span_id="2222222222222222"))

    started = monotonic()
    sink.emit(replace(_span(), span_id="3333333333333333"))
    elapsed = monotonic() - started

    assert elapsed < 0.1
    assert sink.queued_count == 2
    assert sink.dropped_count == 1
    release.set()
    assert sink.close(2.0)
    assert sink.exported_count == 3


def test_queue_uses_validated_snapshot_not_caller_mutable_dict() -> None:
    entered = threading.Event()
    release = threading.Event()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        entered.set()
        release.wait(2.0)
        return httpx.Response(200, request=request)

    sink = _sink(
        httpx.Client(transport=httpx.MockTransport(handler)),
        batch_size=1,
        flush_interval_seconds=0.01,
    )
    sink.emit(_span())
    assert entered.wait(1.0)
    mutable_attributes = {"provider": "safe-provider"}
    span = _span(span_id="2222222222222222", attributes=mutable_attributes)
    sink.emit(span)
    mutable_attributes["transcript"] = "private-after-enqueue"
    release.set()
    assert sink.close(1.0)

    assert len(requests) == 2
    assert "private-after-enqueue" not in requests[1].content.decode()


def test_flush_and_close_are_bounded_when_transport_is_stuck() -> None:
    entered = threading.Event()
    release = threading.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        entered.set()
        release.wait(2.0)
        return httpx.Response(200, request=request)

    sink = _sink(
        httpx.Client(transport=httpx.MockTransport(handler)),
        batch_size=1,
        flush_interval_seconds=0.01,
    )
    sink.emit(_span())
    assert entered.wait(1.0)

    started = monotonic()
    assert not sink.flush(0.01)
    assert monotonic() - started < 0.2
    started = monotonic()
    assert not sink.close(0.01)
    assert monotonic() - started < 0.2

    release.set()
    assert sink.close(1.0)


def test_composite_keeps_jsonl_when_langfuse_fails(tmp_path) -> None:
    requests: list[httpx.Request] = []
    remote = _sink(_recording_client(requests, 500))
    composite = CompositeTraceSink(JsonlTraceSink(tmp_path), remote)

    composite.emit(_span())
    assert composite.close(1.0)

    records = [
        json.loads(line)
        for path in tmp_path.glob("*.jsonl")
        for line in path.read_text().splitlines()
    ]
    assert len(records) == 1
    assert records[0]["trace_id"] == _span().trace_id
    assert len(requests) == 1


def test_composite_keeps_langfuse_when_jsonl_fails(tmp_path) -> None:
    blocked_directory = tmp_path / "not-a-directory"
    blocked_directory.write_text("blocked")
    requests: list[httpx.Request] = []
    remote = _sink(_recording_client(requests))
    composite = CompositeTraceSink(JsonlTraceSink(blocked_directory), remote)

    composite.emit(_span())
    assert composite.close(1.0)

    assert len(requests) == 1
    assert remote.exported_count == 1


def test_disabled_and_invalid_config_are_fail_open_and_secret_safe(
    caplog: pytest.LogCaptureFixture,
) -> None:
    disabled = create_langfuse_sink(LangfuseOtlpSettings(enabled=False))
    assert isinstance(disabled, NullTraceSink)

    secret = "sk-private-config-secret"
    invalid = LangfuseOtlpSettings(
        enabled=True,
        endpoint="https://example.test/api/public/ingestion",
        public_key=SecretStr("pk-test"),
        secret_key=SecretStr(secret),
    )
    with caplog.at_level(logging.WARNING):
        sink = create_langfuse_sink(invalid)

    assert isinstance(sink, NullTraceSink)
    assert "LANGFUSE_CONFIG_INVALID" in caplog.text
    assert secret not in caplog.text


def test_future_stt_tts_schema_is_accepted_without_content() -> None:
    requests: list[httpx.Request] = []
    sink = _sink(_recording_client(requests))
    stt = _span(
        component="STT",
        operation="speech.stt.transcribe",
        attributes={
            "provider": "google",
            "model": "stt-v1",
            "config_version": "v2",
            "audio_duration_ms": 1200.5,
            "first_partial_ms": 140.0,
            "final_ms": 800.0,
            "latency_ms": 805.0,
            "partial_count": 3,
            "streaming": True,
            "silence_detected": False,
            "transcript_empty": False,
            "confidence_bucket": "HIGH",
            "vad_end_reason": "SILENCE",
            "decode_error": False,
        },
        events=(),
    )
    tts = _span(
        span_id="2222222222222222",
        component="TTS",
        operation="speech.tts.synthesize",
        status="ERROR",
        attributes={
            "provider": "google",
            "model": "tts-v1",
            "voice": "vi-VN-Neural2-A",
            "complete_ms": 450.0,
            "latency_ms": 455.0,
            "audio_duration_ms": 2200.0,
            "bytes": 4096,
            "chunks": 4,
            "was_split": True,
            "split_count": 2,
            "text_length_bucket": "MEDIUM",
            "barge_in": False,
            "cancelled": False,
            "provider_http_status": 429,
            "retry_count": 0,
            "timeout": False,
            "provider_status": "RATE_LIMITED",
            "error_type": "PROVIDER",
            "error_code": "PROVIDER_RATE_LIMITED",
        },
        events=(),
    )

    sink.emit(stt)
    sink.emit(tts)
    assert sink.close(1.0)

    exported = _exported_spans(requests[0])
    stt_attributes = _attributes(exported[0])
    tts_attributes = _attributes(exported[1])
    assert stt_attributes["langfuse.observation.metadata.transcript_empty"] is False
    assert stt_attributes["langfuse.observation.metadata.confidence_bucket"] == "HIGH"
    assert tts_attributes["langfuse.observation.metadata.complete_ms"] == 450.0
    assert tts_attributes["langfuse.observation.metadata.was_split"] is True
