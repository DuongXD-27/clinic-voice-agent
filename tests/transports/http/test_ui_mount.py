"""/ui phục vụ bản build UI (ui.py): SPA fallback, cache header, không che route khác.

TestClient không dùng `with` nên lifespan không chạy: chỉ kiểm phần định tuyến, không cần
Redis hay clinic.
"""

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from callbot.transports.http.main import create_app

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
    response = client.get("/ui/")

    assert response.status_code == 200
    assert response.text == INDEX
    assert response.headers["cache-control"] == "no-cache"


def test_mount_path_without_slash_redirects_to_index(client: TestClient) -> None:
    response = client.get("/ui", follow_redirects=False)

    assert response.status_code in (301, 307, 308)
    assert response.headers["location"].endswith("/ui/")


@pytest.mark.parametrize("path", ["/ui/call", "/ui/observability/calls/abc"])
def test_client_side_routes_fall_back_to_index(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert response.text == INDEX
    assert response.headers["cache-control"] == "no-cache"


def test_hashed_assets_are_cached_forever(client: TestClient) -> None:
    response = client.get("/ui/assets/index-abc123.js")

    assert response.status_code == 200
    assert response.headers["cache-control"] == IMMUTABLE


def test_unhashed_public_files_revalidate(client: TestClient) -> None:
    response = client.get("/ui/favicon.svg")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("path", ["/ui/assets/missing.js", "/ui/missing.png"])
def test_missing_files_are_real_404_not_index(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 404
    assert response.text != INDEX


def test_mount_does_not_shadow_other_routes(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/openapi.json").status_code == 200


@pytest.mark.parametrize(
    ("path", "target"),
    [
        ("/", "/ui/"),
        ("/demo", "/ui/call"),
        ("/demo/", "/ui/call"),
        ("/demo/livekit-demo.html", "/ui/livekit"),
        ("/observability/", "/ui/observability"),
        ("/observability?metric=stt", "/ui/observability?metric=stt"),
    ],
)
def test_legacy_pages_redirect_to_new_ui(client: TestClient, path: str, target: str) -> None:
    response = client.get(path, follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == target


def test_legacy_redirects_are_not_part_of_the_api_contract(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert not {"/", "/demo", "/demo/", "/observability", "/observability/"} & set(paths)


def test_empty_config_leaves_ui_unmounted() -> None:
    client = TestClient(create_app(ui_dist_dir=""))

    assert client.get("/ui/").status_code == 404
    assert client.get("/health").status_code == 200


def test_unbuilt_directory_logs_and_leaves_ui_unmounted(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="callbot.transports.http.ui"):
        client = TestClient(create_app(ui_dist_dir=str(tmp_path / "not-built")))

    assert client.get("/ui/").status_code == 404
    assert "UI_DIST_MISSING" in caplog.text
