"""Bearer key BOT_API_KEYS trên /v1/calls và /demo-api (auth.py)."""

from typing import Optional

import pytest
from fastapi.testclient import TestClient

from callbot.transports.http.config import settings

KEY = "sk_mentor_test"
OTHER_KEY = "sk_team_test"


def _start(client: TestClient, call_id: str, key: Optional[str] = None, scheme: str = "Bearer"):
    headers = {"Authorization": f"{scheme} {key}"} if key is not None else {}
    return client.post(
        "/v1/calls",
        headers=headers,
        json={
            "call_id": call_id,
            "direction": "outbound",
            "appointment_id": "apt_00417",
            "caller_number": None,
            "locale": "vi-VN",
            "mode": "text",
            "max_turns": 20,
        },
    )


@pytest.fixture
def auth_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "bot_api_keys", f" {KEY} , {OTHER_KEY} ,")


def test_empty_keys_disable_auth(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "bot_api_keys", "")
    assert _start(client, "c_auth_off").status_code == 200


@pytest.mark.usefixtures("auth_on")
@pytest.mark.parametrize(
    ("key", "scheme", "message"),
    [
        (None, "Bearer", "Missing bearer token."),
        ("", "Bearer", "Missing bearer token."),
        (KEY, "Basic", "Missing bearer token."),
        ("sk_wrong", "Bearer", "Invalid bearer token."),
        (KEY + "x", "Bearer", "Invalid bearer token."),
    ],
)
def test_rejects_missing_or_wrong_key(
    client: TestClient, key: Optional[str], scheme: str, message: str
) -> None:
    response = _start(client, "c_auth_bad", key, scheme)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": {"code": "BAD_KEY", "message": message}}


@pytest.mark.usefixtures("auth_on")
@pytest.mark.parametrize("key", [KEY, OTHER_KEY])
def test_accepts_every_configured_key(client: TestClient, key: str) -> None:
    assert _start(client, f"c_auth_{key}", key).status_code == 200


@pytest.mark.usefixtures("auth_on")
def test_auth_checked_before_body_validation(client: TestClient) -> None:
    # Smoke test CD dựa vào thứ tự này: body rỗng + key đúng -> 422, không mở phiên, không gọi Clinic
    assert client.post("/v1/calls", json={}).status_code == 401
    ok = client.post("/v1/calls", json={}, headers={"Authorization": f"Bearer {KEY}"})
    assert ok.status_code == 422


@pytest.mark.usefixtures("auth_on")
def test_turn_requires_key(client: TestClient) -> None:
    assert _start(client, "c_auth_turn", KEY).status_code == 200
    body = {"turn": 1, "audio_url": None, "text": "Vâng", "silence_ms": 0}
    assert client.post("/v1/calls/c_auth_turn/turn", json=body).status_code == 401
    ok = client.post(
        "/v1/calls/c_auth_turn/turn", json=body, headers={"Authorization": f"Bearer {KEY}"}
    )
    assert ok.status_code == 200


@pytest.mark.usefixtures("auth_on")
def test_demo_api_requires_key(client: TestClient) -> None:
    response = client.post("/demo-api/clinic-reset", json={"appointment_id": "apt_00417"})
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "BAD_KEY"


@pytest.mark.usefixtures("auth_on")
@pytest.mark.parametrize("path", ["/health", "/ready", "/demo/"])
def test_probes_and_demo_page_stay_open(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 200


def test_swagger_declares_bearer_auth(client: TestClient) -> None:
    # Swagger chỉ hiện nút Authorize khi schema khai báo securitySchemes
    spec = client.get("/openapi.json").json()
    assert spec["components"]["securitySchemes"]["BearerAuth"] == {
        "type": "http",
        "scheme": "bearer",
    }
    assert spec["paths"]["/v1/calls"]["post"]["security"] == [{"BearerAuth": []}]
    assert "security" not in spec["paths"]["/health"]["get"]
