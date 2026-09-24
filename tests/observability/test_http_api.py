from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import fakeredis
import pytest
from fastapi.testclient import TestClient

from callbot.engine import EngineSettings
from callbot.observability import JsonlSpanSource, MetricsQueryService
from callbot.tracing.models import CompletedSpan, TraceEvent
from callbot.transports.http.call_mode import CallModeStore
from callbot.transports.http.config import ObservabilityApiSettings
from callbot.transports.http.main import create_app
from tests.transports.http.fakes import make_speech_bundle

UTC = timezone.utc
BASE_TIME = (datetime.now(UTC) - timedelta(hours=4)).replace(minute=0, second=0, microsecond=0)
WINDOW_START = BASE_TIME - timedelta(hours=1)
WINDOW_END = BASE_TIME + timedelta(hours=6)
CALL_KEY = "ck_v1_call_a"
OTHER_CALL_KEY = "ck_v1_call_b"
OPERATIONS = {
    "TURN": "http.call_turn",
    "STT": "speech.stt.transcribe",
    "CORE": "core.handle_turn",
    "TTS": "speech.tts.synthesize",
    "CLINIC": "clinic.get_appointment",
}


def _id(value: int, width: int) -> str:
    return f"{value:0{width}x}"[-width:]


def _span(
    component: str,
    *,
    trace: int,
    span: int,
    parent: int | None = None,
    call_key: str = CALL_KEY,
    turn: int = 0,
    hour: int = 0,
    duration_ms: float = 100.0,
    status: str = "OK",
    attributes: dict[str, object] | None = None,
    events: tuple[TraceEvent, ...] = (),
) -> CompletedSpan:
    started = BASE_TIME + timedelta(hours=hour)
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


def _records() -> list[CompletedSpan]:
    replayed = TraceEvent(
        name="session.replayed",
        timestamp=(BASE_TIME + timedelta(hours=3)).isoformat().replace("+00:00", "Z"),
        attributes={
            "replayed": True,
            "terminal": False,
            "storage_status": "OK",
            "turn_ordering": "OK",
        },
    )
    return [
        _span("TURN", trace=1, span=10, turn=0, duration_ms=1000),
        _span("CORE", trace=1, span=11, parent=10, turn=0, duration_ms=500),
        _span(
            "TURN",
            trace=2,
            span=20,
            turn=1,
            hour=1,
            duration_ms=3000,
            status="ERROR",
            attributes={"error_code": "INTERNAL_ERROR"},
        ),
        _span(
            "STT",
            trace=2,
            span=21,
            parent=20,
            turn=1,
            hour=1,
            duration_ms=400,
            status="ERROR",
            attributes={
                "provider": "fake-asr",
                "model": "asr-v1",
                "transcript_empty": True,
                "error_code": "STT_PROVIDER_ERROR",
            },
        ),
        _span("CORE", trace=2, span=22, parent=20, turn=1, hour=1, duration_ms=1000),
        _span(
            "CLINIC",
            trace=2,
            span=23,
            parent=22,
            turn=1,
            hour=1,
            duration_ms=200,
            status="ERROR",
            attributes={"error_code": "CLINIC_TIMEOUT"},
        ),
        _span(
            "TTS",
            trace=2,
            span=24,
            parent=20,
            turn=1,
            hour=1,
            duration_ms=700,
            attributes={"provider": "fake-tts", "model": "tts-v1"},
        ),
        _span(
            "TURN",
            trace=3,
            span=30,
            turn=2,
            hour=2,
            duration_ms=2100,
            attributes={"replayed": False},
        ),
        _span("CORE", trace=3, span=31, parent=30, turn=2, hour=2, duration_ms=900),
        _span(
            "TURN",
            trace=4,
            span=40,
            turn=2,
            hour=3,
            duration_ms=2200,
            events=(replayed,),
        ),
        _span("CORE", trace=4, span=41, parent=40, turn=2, hour=3, duration_ms=800),
        _span(
            "TURN",
            trace=5,
            span=50,
            call_key=OTHER_CALL_KEY,
            turn=0,
            hour=2,
            duration_ms=500,
        ),
    ]


def _write_records(
    directory: Path, *, malformed: bool = False, privacy_canary: bool = False
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(span.to_dict()) for span in _records()]
    if malformed:
        lines.append("{malformed")
    if privacy_canary:
        raw = _records()[0].to_dict()
        raw.update(
            {
                "raw_call_id": "CANARY_CALL",
                "name": "CANARY_NAME",
                "dob": "CANARY_DOB",
                "phone": "CANARY_PHONE",
                "transcript": "CANARY_TRANSCRIPT",
                "utterance": "CANARY_UTTERANCE",
                "audio_url": "CANARY_AUDIO",
                "exception": "CANARY_EXCEPTION",
            }
        )
        lines.append(json.dumps(raw))
    (directory / "trace-20260921-p101.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _params(start: datetime = WINDOW_START, end: datetime = WINDOW_END) -> dict[str, str]:
    return {"start": start.isoformat(), "end": end.isoformat()}


@pytest.fixture
def app_factory(clinic, redis_store_factory, redis_server, tmp_path):
    def factory(settings: ObservabilityApiSettings):
        call_mode_client = fakeredis.FakeRedis(server=redis_server, decode_responses=True)
        return create_app(
            clinic_factory=lambda: clinic,
            engine_settings=EngineSettings(),
            session_store_factory=redis_store_factory,
            speech_factory=lambda: make_speech_bundle(tmp_path / f"audio-{uuid4().hex}"),
            call_mode_factory=lambda: CallModeStore(
                call_mode_client, key_prefix=f"test:{uuid4().hex}"
            ),
            observability_settings=settings,
        )

    return factory


@pytest.fixture
def api_client(tmp_path, app_factory) -> Iterator[TestClient]:
    trace_dir = tmp_path / "traces"
    _write_records(trace_dir, malformed=True, privacy_canary=True)
    app = app_factory(ObservabilityApiSettings(enabled=True, trace_dir=str(trace_dir)))
    with TestClient(app) as client:
        yield client


def test_overview_matches_query_service_and_reports_diagnostics(api_client, tmp_path) -> None:
    response = api_client.get(
        "/internal/observability/overview",
        params={**_params(), "slow_threshold_ms": 2000},
    )
    assert response.status_code == 200
    payload = response.json()

    expected = MetricsQueryService(JsonlSpanSource(tmp_path / "traces")).get_overview(
        WINDOW_START, WINDOW_END, slow_turn_threshold_ms=2000
    )
    assert payload["turn_count"] == expected.turn_count
    assert payload["turn_latency"] == expected.turn_latency.to_dict()
    assert payload["stt_latency"] == expected.stt_latency.to_dict()
    assert payload["core_latency"] == expected.core_latency.to_dict()
    assert payload["tts_latency"] == expected.tts_latency.to_dict()
    assert payload["slow_turn"] == {"count": 3, "denominator": 5, "rate": 0.6}
    assert payload["turn_error"] == {"count": 1, "denominator": 5, "rate": 0.2}
    assert payload["stt_empty"] == {"empty_count": 1, "eligible_count": 1, "rate": 1.0}
    assert len(payload["hourly"]) == 4
    assert payload["diagnostics"]["records_skipped"] == 2
    assert payload["diagnostics"]["records_processed"] == len(_records())


def test_call_detail_preserves_replay_and_paginates(api_client) -> None:
    response = api_client.get(
        f"/internal/observability/calls/{CALL_KEY}", params={**_params(), "limit": 2, "offset": 2}
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["total_executions"] == 4
    assert [(item["turn"], item["trace_id"]) for item in payload["executions"]] == [
        (2, _id(3, 32)),
        (2, _id(4, 32)),
    ]
    assert payload["executions"][1]["replayed"] is True


def test_call_detail_validates_key_and_returns_safe_not_found(api_client) -> None:
    invalid = api_client.get("/internal/observability/calls/raw-call-id", params=_params())
    missing = api_client.get("/internal/observability/calls/ck_v1_missing", params=_params())

    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "invalid_call_key"
    assert "raw-call-id" not in invalid.text
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "call_not_found"
    assert "ck_v1_missing" not in missing.text


def test_turn_detail_has_stage_and_clinic_summaries(api_client) -> None:
    response = api_client.get(f"/internal/observability/turns/{_id(2, 32)}", params=_params())
    assert response.status_code == 200
    payload = response.json()

    assert payload["trace_id"] == _id(2, 32)
    assert payload["stages"]["stt"]["provider"] == "fake-asr"
    assert payload["stages"]["core"]["duration_ms"] == 1000
    assert payload["stages"]["tts"]["model"] == "tts-v1"
    assert payload["clinic"][0]["error_code"] == "CLINIC_TIMEOUT"
    assert payload["error_codes"] == ["CLINIC_TIMEOUT", "INTERNAL_ERROR", "STT_PROVIDER_ERROR"]


def test_turn_detail_validates_id_and_returns_safe_not_found(api_client) -> None:
    invalid = api_client.get("/internal/observability/turns/NOT-A-TRACE", params=_params())
    missing = api_client.get("/internal/observability/turns/" + "f" * 32, params=_params())

    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "invalid_trace_id"
    assert "NOT-A-TRACE" not in invalid.text
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "turn_not_found"


def test_slow_turns_apply_threshold_and_bounded_offset_pagination(api_client) -> None:
    response = api_client.get(
        "/internal/observability/slow-turns",
        params={**_params(), "threshold_ms": 2000, "limit": 1, "offset": 1},
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["limit"] == 1
    assert payload["offset"] == 1
    assert len(payload["items"]) == 1
    assert payload["items"][0]["duration_ms"] == 2200
    assert payload["items"][0]["core_ms"] == 800
    assert payload["items"][0]["stt_ms"] is None

    too_large = api_client.get(
        "/internal/observability/slow-turns", params={**_params(), "limit": 501}
    )
    assert too_large.status_code == 422


def test_errors_are_sorted_and_never_include_messages(api_client) -> None:
    response = api_client.get("/internal/observability/errors", params={**_params(), "limit": 2})
    assert response.status_code == 200
    payload = response.json()

    assert payload["limit"] == 2
    assert [(item["component"], item["error_code"]) for item in payload["items"]] == [
        ("CLINIC", "CLINIC_TIMEOUT"),
        ("STT", "STT_PROVIDER_ERROR"),
    ]
    assert "message" not in json.dumps(payload)
    assert "exception" not in json.dumps(payload).lower()


def test_quality_endpoint_uses_closed_modes_and_safe_candidates(api_client) -> None:
    response = api_client.get(
        "/internal/observability/quality",
        params={**_params(), "component": "STT", "aggregation": "call"},
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["component"] == "STT"
    assert payload["aggregation"] == "call"
    assert payload["eligible_count"] == 1
    assert payload["affected_count"] == 1
    assert payload["clean_count"] == 0
    counts = {item["code"]: item["affected_count"] for item in payload["issues"]}
    assert counts["STT_EMPTY_TRANSCRIPT"] == 1
    assert counts["STT_PROVIDER_ERROR"] == 1
    assert payload["candidates"][0]["call_key"] == CALL_KEY
    assert all(item["instrumentation_status"] == "NOT_INSTRUMENTED" for item in payload["coverage"])

    invalid = api_client.get(
        "/internal/observability/quality",
        params={**_params(), "component": "CORE", "aggregation": "call"},
    )
    assert invalid.status_code == 422


def test_time_validation_default_empty_and_max_window(api_client) -> None:
    defaulted = api_client.get("/internal/observability/overview")
    assert defaulted.status_code == 200
    assert defaulted.json()["turn_count"] == 5

    empty_start = BASE_TIME + timedelta(hours=10)
    empty = api_client.get(
        "/internal/observability/overview",
        params=_params(empty_start, empty_start + timedelta(hours=1)),
    )
    assert empty.status_code == 200
    assert empty.json()["turn_count"] == 0
    assert empty.json()["turn_latency"]["p95_ms"] is None

    reversed_range = api_client.get(
        "/internal/observability/overview", params=_params(WINDOW_END, WINDOW_START)
    )
    naive = api_client.get(
        "/internal/observability/overview",
        params={"start": "2026-01-01T00:00:00", "end": WINDOW_END.isoformat()},
    )
    oversized = api_client.get(
        "/internal/observability/overview",
        params=_params(WINDOW_START, WINDOW_START + timedelta(days=32)),
    )
    for response in (reversed_range, naive, oversized):
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "invalid_time_range"


def test_default_disabled_and_missing_configuration_do_not_register_router(
    app_factory, monkeypatch
) -> None:
    defaults = ObservabilityApiSettings(_env_file=None)
    assert defaults.enabled is False

    disabled = app_factory(ObservabilityApiSettings(enabled=False, trace_dir="ignored"))
    with TestClient(disabled) as client:
        assert client.get("/internal/observability/overview").status_code == 404
        assert client.get("/health").status_code == 200

    monkeypatch.setenv("TRACE_JSONL_DIR", "")
    missing = app_factory(ObservabilityApiSettings(enabled=True, trace_dir=""))
    with TestClient(missing) as client:
        assert client.get("/internal/observability/overview").status_code == 404
        assert client.get("/health").status_code == 200


def test_missing_directory_is_empty_but_file_path_is_unavailable(tmp_path, app_factory) -> None:
    missing_dir = tmp_path / "not-created"
    empty_app = app_factory(ObservabilityApiSettings(enabled=True, trace_dir=str(missing_dir)))
    with TestClient(empty_app) as client:
        response = client.get("/internal/observability/overview", params=_params())
        assert response.status_code == 200
        assert response.json()["turn_count"] == 0

    file_path = tmp_path / "not-a-directory"
    file_path.write_text("blocked", encoding="utf-8")
    unavailable_app = app_factory(ObservabilityApiSettings(enabled=True, trace_dir=str(file_path)))
    with TestClient(unavailable_app) as client:
        response = client.get("/internal/observability/overview", params=_params())
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "observability_unavailable"
        assert str(file_path) not in response.text
        assert client.get("/health").status_code == 200


def test_all_endpoints_exclude_privacy_canaries(api_client) -> None:
    responses = [
        api_client.get("/internal/observability/overview", params=_params()),
        api_client.get(f"/internal/observability/calls/{CALL_KEY}", params=_params()),
        api_client.get(f"/internal/observability/turns/{_id(2, 32)}", params=_params()),
        api_client.get("/internal/observability/slow-turns", params=_params()),
        api_client.get("/internal/observability/errors", params=_params()),
        api_client.get("/internal/observability/quality", params=_params()),
    ]
    assert all(response.status_code == 200 for response in responses)
    serialized = json.dumps([response.json() for response in responses])
    for canary in (
        "CANARY_CALL",
        "CANARY_NAME",
        "CANARY_DOB",
        "CANARY_PHONE",
        "CANARY_TRANSCRIPT",
        "CANARY_UTTERANCE",
        "CANARY_AUDIO",
        "CANARY_EXCEPTION",
    ):
        assert canary not in serialized


def test_business_routes_remain_registered_when_observability_is_enabled(api_client) -> None:
    paths = api_client.app.openapi()["paths"]
    assert "get" in paths["/health"]
    assert "post" in paths["/v1/calls"]
    assert "post" in paths["/v1/calls/{call_id}/turn"]
