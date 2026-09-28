"""Tiện ích clinic của trang demo: nút reset và dropdown dữ liệu, route transport gọi /_harness/*."""

import httpx
import pytest
from fastapi.testclient import TestClient

from callbot.transports.http import demo
from callbot.transports.http.config import settings

BASE = "https://clinic-mock.example/v1"
APPOINTMENT_ROW = {
    "appointment_id": "apt_00417",
    "status": "TRANSFERRED",
    "patient": {"patient_id": "pt_3391", "display_name": "N. V. A."},
}
PATIENT_ROWS = [
    {"patient_id": "p_2", "display_name": "Mai N.", "phone": "0912345678"},
    {"patient_id": "pt_3391", "display_name": "N. V. A.", "phone": "0912345600"},
    {"patient_id": "p_3", "display_name": "Lan T.", "phone": "0912345678"},
]


@pytest.fixture
def mock_clinic(monkeypatch: pytest.MonkeyPatch):
    """Clinic mock giả qua MockTransport; trả danh sách request đã nhận để kiểm tra."""
    seen: list[httpx.Request] = []
    state = {"reset_status": 200}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/_harness/reset":
            if state["reset_status"] != 200:
                return httpx.Response(state["reset_status"], json={"error": {"code": "BAD_KEY"}})
            return httpx.Response(200, json={"reset": True})
        if request.url.path == "/_harness/appointments":
            return httpx.Response(200, json=[APPOINTMENT_ROW])
        if request.url.path == "/_harness/patients":
            return httpx.Response(200, json=PATIENT_ROWS)
        if request.url.path == "/v1/appointments/apt_00417":
            return httpx.Response(
                200, json={"appointment_id": "apt_00417", "status": "SCHEDULED", "version": 3}
            )
        return httpx.Response(404, json={"error": {"code": "NOT_FOUND"}})

    monkeypatch.setattr(demo, "_clinic_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(settings, "clinic_backend", "mock")
    monkeypatch.setattr(settings, "clinic_mock_base_url", BASE + "/")
    monkeypatch.setattr(settings, "clinic_mock_api_key", "sk_test")
    monkeypatch.setattr(settings, "demo_clinic_admin_enabled", True)
    return seen, state


def test_reset_calls_harness_at_domain_root_then_reads_appointment(
    client: TestClient, mock_clinic
) -> None:
    seen, _ = mock_clinic
    response = client.post("/demo-api/clinic-reset", json={"appointment_id": "apt_00417"})

    assert response.status_code == 200
    assert response.json() == {
        "reset": True,
        "appointment": {"appointment_id": "apt_00417", "status": "SCHEDULED", "version": 3},
    }
    # /_harness nằm ở gốc domain, không dưới /v1; key server-side đi kèm
    assert [(r.method, r.url.path) for r in seen] == [
        ("POST", "/_harness/reset"),
        ("GET", "/v1/appointments/apt_00417"),
    ]
    assert seen[0].headers["Authorization"] == "Bearer sk_test"


def test_reset_without_body_defaults_to_sample_appointment(client: TestClient, mock_clinic) -> None:
    response = client.post("/demo-api/clinic-reset")

    assert response.status_code == 200
    assert response.json()["appointment"]["appointment_id"] == "apt_00417"


def test_reset_still_succeeds_when_readback_fails(client: TestClient, mock_clinic) -> None:
    response = client.post("/demo-api/clinic-reset", json={"appointment_id": "apt_missing"})

    assert response.status_code == 200
    assert response.json() == {"reset": True, "appointment": None}


def test_reset_rejected_by_mock_is_reported(client: TestClient, mock_clinic) -> None:
    seen, state = mock_clinic
    state["reset_status"] = 401

    response = client.post("/demo-api/clinic-reset")

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "RESET_FAILED"
    assert "BAD_KEY" in response.json()["detail"]["message"]
    assert len(seen) == 1  # không đọc lại khi reset thất bại


def test_reset_disabled_by_flag_never_reaches_mock(
    client: TestClient, mock_clinic, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen, _ = mock_clinic
    monkeypatch.setattr(settings, "demo_clinic_admin_enabled", False)

    response = client.post("/demo-api/clinic-reset")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "CLINIC_ADMIN_DISABLED"
    assert seen == []


def test_reset_unavailable_on_sim_backend(
    client: TestClient, mock_clinic, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen, _ = mock_clinic
    monkeypatch.setattr(settings, "clinic_backend", "sim")

    response = client.post("/demo-api/clinic-reset")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "RESET_UNAVAILABLE"
    assert seen == []


def test_reset_rejects_unsafe_appointment_id(client: TestClient, mock_clinic) -> None:
    seen, _ = mock_clinic
    response = client.post("/demo-api/clinic-reset", json={"appointment_id": "../_harness/x"})

    assert response.status_code == 422
    assert seen == []


def test_fixtures_from_mock_list_appointments_with_status_and_unique_phones(
    client: TestClient, mock_clinic
) -> None:
    seen, _ = mock_clinic
    response = client.get("/demo-api/clinic-fixtures")

    assert response.status_code == 200
    assert response.json() == {
        "source": "mock",
        "appointments": [
            {"appointment_id": "apt_00417", "status": "TRANSFERRED", "display_name": "N. V. A."}
        ],
        "phones": [
            {"phone": "0912345600", "display_name": "N. V. A."},
            {"phone": "0912345678", "display_name": "Mai N., Lan T."},
        ],
    }
    assert [r.url.path for r in seen] == ["/_harness/appointments", "/_harness/patients"]
    assert seen[0].headers["Authorization"] == "Bearer sk_test"


def test_fixtures_from_sim_include_locally_seeded_data(
    client: TestClient, mock_clinic, clinic, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen, _ = mock_clinic
    monkeypatch.setattr(settings, "clinic_backend", "sim")
    clinic.seed_patient(
        {"patient_id": "pt_local", "display_name": "Bình L.", "phone": "0900000001"}
    )
    clinic.seed_appointment(
        {"appointment_id": "apt_local", "status": "BOOKED", "patient": {"patient_id": "pt_local"}}
    )

    body = client.get("/demo-api/clinic-fixtures").json()

    assert body["source"] == "sim"
    assert {"appointment_id": "apt_local", "status": "BOOKED", "display_name": None} in body[
        "appointments"
    ]
    assert {"phone": "0900000001", "display_name": "Bình L."} in body["phones"]
    assert seen == []  # sim không gọi mạng


def test_fixtures_disabled_by_flag(
    client: TestClient, mock_clinic, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen, _ = mock_clinic
    monkeypatch.setattr(settings, "demo_clinic_admin_enabled", False)

    response = client.get("/demo-api/clinic-fixtures")

    assert response.status_code == 404
    assert seen == []
