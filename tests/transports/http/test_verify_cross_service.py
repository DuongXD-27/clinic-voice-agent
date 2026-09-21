"""Verify Identity qua Callbot HTTP -> Clinic Mock thật chạy ở repository riêng."""

from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi import FastAPI

from callbot.engine import EngineSettings
from callbot.engine.tools.clinic_mock_client import ClinicMockClient
from callbot.transports.http.main import create_app

APPOINTMENT_ID = "apt_00417"
CLINIC_API_KEY = "sk_cross_service_verify"
RUN_ENV = "RUN_VERIFY_CROSS_SERVICE"


@dataclass(frozen=True)
class ClinicService:
    root_url: str

    @property
    def api_url(self) -> str:
        return f"{self.root_url}/v1"

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {CLINIC_API_KEY}"}


@dataclass
class CallbotHarness:
    client: httpx.Client
    app: FastAPI
    clinic_operations: list[str]
    base_url: str


class RecordingClinicMockClient(ClinicMockClient):
    """Ghi tên operation nhưng vẫn gửi mọi Clinic request qua HTTP thật."""

    def __init__(self, base_url: str, api_key: str, operations: list[str]) -> None:
        super().__init__(base_url, api_key)
        self._operations = operations

    def get_appointment(self, appointment_id: str) -> dict[str, Any]:
        self._operations.append("get_appointment")
        return super().get_appointment(appointment_id)

    def confirm_appointment(
        self, appointment_id: str, version: int, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        self._operations.append("confirm_appointment")
        return super().confirm_appointment(appointment_id, version, idempotency_key)

    def transfer_appointment(
        self,
        appointment_id: str,
        transfer_reason: str,
        version: int,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self._operations.append("transfer_appointment")
        return super().transfer_appointment(
            appointment_id, transfer_reason, version, idempotency_key
        )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _clinic_repo() -> Path:
    configured = os.environ.get("CLINIC_MOCK_REPO")
    if configured:
        return Path(configured).resolve()
    return Path(__file__).resolve().parents[3].parent / "clinic-mock"


def _clinic_python(repo: Path) -> Path:
    relative = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    return repo / ".venv" / relative


def _wait_for_health(base_url: str, process: subprocess.Popen[bytes] | None = None) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            pytest.fail(f"Service dừng khi khởi động, exit={process.returncode}")
        try:
            if httpx.get(f"{base_url}/health", timeout=0.5).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    pytest.fail(f"Service {base_url} không ready trong 15 giây")


@pytest.fixture(scope="session")
def clinic_service() -> Iterator[ClinicService]:
    if os.environ.get(RUN_ENV) != "1":
        pytest.skip(f"Đặt {RUN_ENV}=1 để chạy Clinic Mock repo thật qua HTTP")

    repo = _clinic_repo()
    python = _clinic_python(repo)
    if not (repo / "src/clinic_mock/app.py").is_file() or not python.is_file():
        pytest.fail(f"Thiếu Clinic Mock repo hoặc virtualenv tại {repo}")

    port = _free_port()
    service = ClinicService(f"http://127.0.0.1:{port}")
    env = os.environ.copy()
    env.update(
        {
            "APP_HOST": "127.0.0.1",
            "APP_PORT": str(port),
            "LANGFUSE_TRACES_ENABLED": "false",
            "LOG_LEVEL": "WARNING",
            "MOCK_API_KEYS": CLINIC_API_KEY,
            "PYTHONIOENCODING": "utf-8",
        }
    )
    process = subprocess.Popen(
        [
            str(python),
            "-m",
            "uvicorn",
            "clinic_mock.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=repo,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        _wait_for_health(service.root_url, process)
        yield service
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.fixture
def clinic_http(clinic_service: ClinicService) -> Iterator[httpx.Client]:
    with httpx.Client(
        base_url=clinic_service.root_url,
        headers=clinic_service.headers,
        timeout=5,
    ) as client:
        reset = client.post("/_harness/reset")
        assert reset.status_code == 200 and reset.json() == {"reset": True}
        try:
            yield client
        finally:
            client.post("/_harness/reset")


@pytest.fixture
def callbot_harness(
    clinic_service: ClinicService,
    clinic_http: httpx.Client,
    redis_store_factory,
) -> Iterator[CallbotHarness]:
    del clinic_http  # dependency bảo đảm reset trước khi Callbot bắt đầu
    operations: list[str] = []
    app = create_app(
        clinic_factory=lambda: RecordingClinicMockClient(
            clinic_service.api_url, CLINIC_API_KEY, operations
        ),
        engine_settings=EngineSettings(llm_provider="none"),
        session_store_factory=redis_store_factory,
    )
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        _wait_for_health(base_url)
        with httpx.Client(base_url=base_url, timeout=5) as client:
            yield CallbotHarness(client, app, operations, base_url)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        assert not thread.is_alive(), "Callbot uvicorn không dừng trong 5 giây"


def _start(client: httpx.Client, call_id: str) -> dict[str, Any]:
    response = client.post(
        "/v1/calls",
        json={
            "call_id": call_id,
            "direction": "outbound",
            "appointment_id": APPOINTMENT_ID,
            "caller_number": None,
            "locale": "vi-VN",
            "mode": "text",
            "max_turns": 20,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _turn(client: httpx.Client, call_id: str, turn: int, text: str) -> dict[str, Any]:
    response = client.post(
        f"/v1/calls/{call_id}/turn",
        json={"turn": turn, "audio_url": None, "text": text, "silence_ms": 0},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _appointment(client: httpx.Client) -> dict[str, Any]:
    response = client.get(f"/v1/appointments/{APPOINTMENT_ID}")
    assert response.status_code == 200, response.text
    return response.json()


def _session_context(harness: CallbotHarness, call_id: str) -> dict[str, Any]:
    session = harness.app.state.session_store.get_session(call_id)
    assert session is not None
    return session.context


def _assert_no_appointment_disclosure(utterances: list[str]) -> None:
    protected = (
        APPOINTMENT_ID,
        "pt_3391",
        "Nguyễn Văn A",
        "1978-03-14",
        "14/03/1978",
        "Nội tổng quát",
        "3 giờ 30 chiều",
        "ngày 14 tháng 10",
    )
    for utterance in utterances:
        assert not [value for value in protected if value.casefold() in utterance.casefold()]


def test_verify_success_uses_real_clinic_http_without_mutating_appointment(
    callbot_harness: CallbotHarness, clinic_http: httpx.Client
) -> None:
    call_id = "cross_verify_success"
    before = _appointment(clinic_http)

    opening = _start(callbot_harness.client, call_id)
    after_name = _turn(callbot_harness.client, call_id, 1, "Nguyễn Văn A")
    after_dob = _turn(callbot_harness.client, call_id, 2, "14/03/1978")

    assert opening["state"] == "AWAITING_IDENTITY"
    assert after_name["state"] == "AWAITING_IDENTITY"
    _assert_no_appointment_disclosure([opening["utterance"], after_name["utterance"]])
    assert after_dob["state"] == "AWAITING_INTENT" and after_dob["ended"] is False
    assert after_dob["outcome"] is None
    assert "Nội tổng quát" in after_dob["utterance"]
    assert "3 giờ 30 chiều" in after_dob["utterance"]
    assert "ngày 14 tháng 10" in after_dob["utterance"]

    context = _session_context(callbot_harness, call_id)
    assert context["identity_step"] == "VERIFIED"
    assert context["patient_id"] == "pt_3391"
    assert callbot_harness.clinic_operations == ["get_appointment", "get_appointment"]
    assert _appointment(clinic_http) == before


def test_verify_failure_does_not_disclose_confirm_or_mutate_real_clinic(
    callbot_harness: CallbotHarness, clinic_http: httpx.Client
) -> None:
    call_id = "cross_verify_failure"
    before = _appointment(clinic_http)

    opening = _start(callbot_harness.client, call_id)
    after_name = _turn(callbot_harness.client, call_id, 1, "Trần Văn B")
    failed = _turn(callbot_harness.client, call_id, 2, "14/03/1978")

    _assert_no_appointment_disclosure(
        [opening["utterance"], after_name["utterance"], failed["utterance"]]
    )
    assert failed["ended"] is True and failed["outcome"] == "TRANSFERRED"
    context = _session_context(callbot_harness, call_id)
    assert context["identity_step"] != "VERIFIED"
    assert context["state"] == "ENDED" and context["outcome"] == "TRANSFERRED"
    assert "confirm_appointment" not in callbot_harness.clinic_operations

    after = _appointment(clinic_http)
    assert after.get("confirmed_at") is None and after.get("confirmed_via") is None
    actual_state = (after["status"], after["version"], after.get("transfer_reason"))
    expected_state = (
        "TRANSFERRED",
        before["version"] + 1,
        "IDENTITY_FAILED",
    )
    assert actual_state == expected_state, (
        f"identity failure produced an unexpected authoritative state: "
        f"expected={expected_state}, actual={actual_state}, "
        f"clinic_operations={callbot_harness.clinic_operations}"
    )


def test_confirm_attendance_updates_real_clinic_only_after_explicit_agreement(
    callbot_harness: CallbotHarness, clinic_http: httpx.Client
) -> None:
    call_id = "cross_confirm_success"
    before = _appointment(clinic_http)

    opening = _start(callbot_harness.client, call_id)
    after_name = _turn(callbot_harness.client, call_id, 1, "Nguyễn Văn A")
    readback = _turn(callbot_harness.client, call_id, 2, "14/03/1978")

    _assert_no_appointment_disclosure([opening["utterance"], after_name["utterance"]])
    assert _session_context(callbot_harness, call_id)["identity_step"] == "VERIFIED"
    assert readback["state"] == "AWAITING_INTENT" and readback["outcome"] is None
    assert "Nội tổng quát" in readback["utterance"]
    assert "3 giờ 30 chiều" in readback["utterance"]
    assert "ngày 14 tháng 10" in readback["utterance"]
    assert "confirm_appointment" not in callbot_harness.clinic_operations
    assert _appointment(clinic_http) == before

    confirmed = _turn(callbot_harness.client, call_id, 3, "Có, tôi đến được.")
    after = _appointment(clinic_http)

    assert (confirmed["state"], confirmed["ended"], confirmed["outcome"]) == (
        "ENDED",
        True,
        "CONFIRMED",
    )
    assert callbot_harness.clinic_operations == [
        "get_appointment",
        "get_appointment",
        "get_appointment",
        "confirm_appointment",
    ]
    assert after["status"] == "CONFIRMED"
    assert after["confirmed_at"] is not None
    assert after["confirmed_via"] == "callbot"
    assert after["version"] == before["version"] + 1
    changed = {
        field for field in before.keys() | after.keys() if before.get(field) != after.get(field)
    }
    assert changed == {"status", "confirmed_at", "confirmed_via", "version"}


def test_ambiguous_attendance_does_not_confirm_real_clinic(
    callbot_harness: CallbotHarness, clinic_http: httpx.Client
) -> None:
    call_id = "cross_confirm_ambiguous"
    before = _appointment(clinic_http)

    opening = _start(callbot_harness.client, call_id)
    after_name = _turn(callbot_harness.client, call_id, 1, "Nguyễn Văn A")
    readback = _turn(callbot_harness.client, call_id, 2, "14/03/1978")
    ambiguous = _turn(callbot_harness.client, call_id, 3, "Để xem đã")

    _assert_no_appointment_disclosure([opening["utterance"], after_name["utterance"]])
    assert _session_context(callbot_harness, call_id)["identity_step"] == "VERIFIED"
    assert "Nội tổng quát" in readback["utterance"]
    assert ambiguous["ended"] is False and ambiguous["outcome"] != "CONFIRMED"
    assert "confirm_appointment" not in callbot_harness.clinic_operations
    assert callbot_harness.clinic_operations == ["get_appointment", "get_appointment"]
    assert _appointment(clinic_http) == before
