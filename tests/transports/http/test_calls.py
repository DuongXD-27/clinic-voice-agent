from fastapi.testclient import TestClient

from callbot.engine.dialogue.templates import AI_DISCLOSURE, greeting
from callbot.transports.http.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_start_call() -> None:
    response = client.post(
        "/v1/calls",
        json={
            "call_id": "c_test_1",
            "direction": "outbound",
            "appointment_id": "apt_00417",
            "mode": "text",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["call_id"] == "c_test_1"
    assert body["state"] == "AWAITING_IDENTITY"
    # [R-26] endpoint dùng đúng câu chào công bố AI của engine, không hard-code lại
    assert AI_DISCLOSURE in body["utterance"]
    assert body["utterance"] == greeting("outbound")


def test_turn_defaults_to_transfer() -> None:
    client.post(
        "/v1/calls",
        json={"call_id": "c_test_2", "direction": "outbound", "mode": "text"},
    )
    response = client.post(
        "/v1/calls/c_test_2/turn",
        json={"turn": 1, "text": "xin chào"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ended"] is True
    assert body["outcome"] == "TRANSFERRED"
