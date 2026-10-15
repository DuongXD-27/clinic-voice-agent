"""UI ở gốc domain (ui.py): SPA fallback, cache header, không che route API.

Phần lớn test dùng TestClient không `with` nên lifespan không chạy: chỉ kiểm định tuyến, không cần
Redis hay clinic. Riêng /audio (mount trong lifespan) có test chạy lifespan với fake.
"""

import logging
from pathlib import Path
from uuid import uuid4

import fakeredis
import pytest
from fastapi.testclient import TestClient
from tests.transports.http.fakes import make_speech_bundle

from callbot.engine import EngineSettings
from callbot.transports.http.call_mode import CallModeStore
from callbot.transports.http.main import create_app
from clinic_mock_sim import FakeClinicAPI

INDEX = "<!doctype html><title>ui-index</title>"
IMMUTABLE = "public, max-age=31536000, immutable"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(INDEX, encoding="utf-8")
    (root / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (root / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    return root


@pytest.fixture
def client(dist: Path) -> TestClient:
    return TestClient(create_app(ui_dist_dir=str(dist)))


def test_root_serves_index_without_long_cache(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.text == INDEX
    assert response.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize(
    "path",
    ["/login", "/call", "/livekit", "/stt", "/observability", "/observability/calls/abc"],
)
def test_client_side_routes_fall_back_to_index(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert response.text == INDEX
    assert response.headers["cache-control"] == "no-cache"


def test_hashed_assets_are_cached_forever(client: TestClient) -> None:
    response = client.get("/assets/index-abc123.js")

    assert response.status_code == 200
    assert response.headers["cache-control"] == IMMUTABLE


def test_unhashed_public_files_revalidate(client: TestClient) -> None:
    response = client.get("/favicon.svg")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("path", ["/assets/missing.js", "/missing.png", "/favicon.ico"])
def test_missing_files_are_real_404_not_index(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 404
    assert response.text != INDEX


@pytest.mark.parametrize(
    "path",
    [
        "/v1/calls/c1",
        "/demo-api/unknown",
        "/internal/unknown",
        "/audio/c1/0",
        "/audio-static/abc",
        "/livekit/unknown",
        "/docs/unknown",
    ],
)
def test_unknown_api_paths_are_real_404_not_index(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 404
    assert response.text != INDEX


def test_mount_does_not_shadow_other_routes(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/openapi.json").status_code == 200
    assert "swagger" in client.get("/docs").text.lower()
    # POST /livekit/token tới route API (không phải 405 của StaticFiles), dù /livekit là trang UI.
    token = client.post("/livekit/token", json={})
    assert token.status_code != 405
    assert token.headers["content-type"].startswith("application/json")


def test_audio_mounted_in_lifespan_is_not_shadowed(
    dist: Path, tmp_path: Path, redis_store_factory, redis_server
) -> None:
    speech = make_speech_bundle(tmp_path / "audio")
    call_modes = fakeredis.FakeRedis(server=redis_server, decode_responses=True)
    app = create_app(
        ui_dist_dir=str(dist),
        clinic_factory=FakeClinicAPI,
        engine_settings=EngineSettings(llm_provider="none"),
        session_store_factory=redis_store_factory,
        speech_factory=lambda: speech,
        call_mode_factory=lambda: CallModeStore(call_modes, key_prefix=f"test:{uuid4().hex}"),
    )
    with TestClient(app) as client:
        clip = Path(speech.audio_store.directory) / "c1" / "0.wav"
        clip.parent.mkdir(parents=True)
        clip.write_bytes(b"RIFF0000WAVE")

        response = client.get("/audio/c1/0.wav")

    assert response.status_code == 200
    assert response.content == b"RIFF0000WAVE"


@pytest.mark.parametrize(
    ("path", "target"),
    [
        ("/demo", "/call"),
        ("/demo/", "/call"),
        ("/demo/livekit-demo.html", "/livekit"),
        ("/ui", "/"),
        ("/ui/", "/"),
        ("/ui/call", "/call"),
        ("/ui/observability/calls/abc", "/observability/calls/abc"),
        ("/ui/observability?metric=stt", "/observability?metric=stt"),
    ],
)
def test_old_links_redirect_to_root_ui(client: TestClient, path: str, target: str) -> None:
    response = client.get(path, follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == target


def test_legacy_redirects_are_not_part_of_the_api_contract(client: TestClient) -> None:
    paths = set(client.get("/openapi.json").json()["paths"])

    assert not {"/", "/demo", "/demo/", "/ui", "/ui/{path}"} & paths


def test_empty_config_leaves_ui_unmounted() -> None:
    client = TestClient(create_app(ui_dist_dir=""))

    assert client.get("/").status_code == 404
    assert client.get("/call").status_code == 404
    assert client.get("/health").status_code == 200


def test_unbuilt_directory_logs_and_leaves_ui_unmounted(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="callbot.transports.http.ui"):
        client = TestClient(create_app(ui_dist_dir=str(tmp_path / "not-built")))

    assert client.get("/").status_code == 404
    assert "UI_DIST_MISSING" in caplog.text
