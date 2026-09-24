from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

import fakeredis
from fastapi.testclient import TestClient

from callbot.engine import EngineSettings
from callbot.transports.http.call_mode import CallModeStore
from callbot.transports.http.main import create_app
from tests.transports.http.fakes import make_speech_bundle

STATIC_DIR = (
    Path(__file__).parents[2] / "src" / "callbot" / "transports" / "http" / "observability_static"
)


def _app(clinic, redis_store_factory, redis_server, tmp_path):
    call_mode_client = fakeredis.FakeRedis(server=redis_server, decode_responses=True)
    return create_app(
        clinic_factory=lambda: clinic,
        engine_settings=EngineSettings(),
        session_store_factory=redis_store_factory,
        speech_factory=lambda: make_speech_bundle(tmp_path / "audio"),
        call_mode_factory=lambda: CallModeStore(call_mode_client, key_prefix=f"test:{uuid4().hex}"),
    )


def test_dashboard_and_assets_are_served_without_enabling_api(
    clinic, redis_store_factory, redis_server, tmp_path
) -> None:
    app = _app(clinic, redis_store_factory, redis_server, tmp_path)
    with TestClient(app) as client:
        page = client.get("/observability/")
        assert page.status_code == 200
        assert "Voice Observability" in page.text
        assert 'src="./app.mjs"' in page.text
        assert client.get("/observability/app.mjs").status_code == 200
        assert client.get("/observability/styles.css").status_code == 200
        assert client.get("/internal/observability/overview").status_code == 404


def test_dashboard_mount_keeps_demo_and_business_routes_isolated(
    clinic, redis_store_factory, redis_server, tmp_path
) -> None:
    app = _app(clinic, redis_store_factory, redis_server, tmp_path)
    with TestClient(app) as client:
        assert client.get("/demo/").status_code == 200
        assert client.get("/health").status_code == 200
        paths = app.openapi()["paths"]
        assert "post" in paths["/v1/calls"]
        assert "post" in paths["/v1/calls/{call_id}/turn"]


def test_only_central_api_client_contains_observability_request_paths() -> None:
    modules = list(STATIC_DIR.glob("*.mjs"))
    containing = [
        module.name
        for module in modules
        if "internal/observability/" in module.read_text(encoding="utf-8")
    ]
    assert containing == ["api.mjs"]


def test_dashboard_sources_do_not_request_private_fields_or_external_trace_services() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in STATIC_DIR.iterdir()
        if path.suffix in {".html", ".mjs", ".js"}
    ).lower()
    prohibited_literals = (
        "patient_id",
        "appointment_id",
        "utterance",
        "audio_url",
        "langfuse",
        "jsonl",
    )
    for field in prohibited_literals:
        assert field not in source
    for private_field in ("name", "dob", "phone", "transcript"):
        access_pattern = rf"(?:\.|\[['\"]|\[['\"]){private_field}(?:\b|['\"]\])"
        assert re.search(access_pattern, source) is None


def test_dashboard_uses_backend_percentile_fields_without_percentile_library() -> None:
    source = (STATIC_DIR / "components.mjs").read_text(encoding="utf-8")
    assert "p50_ms" in source
    assert "p95_ms" in source
    assert "p99_ms" in source
    assert "percentile(" not in source.lower()
    assert "quantile(" not in source.lower()
