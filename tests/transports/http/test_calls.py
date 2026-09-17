from typing import Any, Optional

import httpx
import pytest
from fastapi.testclient import TestClient
from tests.engine.fake_clinic import FakeClinicAPI

from callbot.engine import EngineSettings, SessionNotFound
from callbot.engine.dialogue import templates as t
from callbot.engine.dialogue.templates import AI_DISCLOSURE, greeting
from callbot.transports.http.calls import get_orchestrator
from callbot.transports.http.main import create_app


def _start(
    client: TestClient,
    call_id: str,
    direction: str = "outbound",
    appointment_id: Optional[str] = "apt_00417",
    caller_number: Optional[str] = None,
    mode: str = "text",
    max_turns: int = 20,
):
    return client.post(
        "/v1/calls",
        json={
            "call_id": call_id,
            "direction": direction,
            "appointment_id": appointment_id,
            "caller_number": caller_number,
            "locale": "vi-VN",
            "mode": mode,
            "max_turns": max_turns,
        },
    )


def _turn(
    client: TestClient,
    call_id: str,
    turn: int,
    text: Optional[str],
    silence_ms: int = 0,
    audio_url: Optional[str] = None,
):
    return client.post(
        f"/v1/calls/{call_id}/turn",
        json={"turn": turn, "audio_url": audio_url, "text": text, "silence_ms": silence_ms},
    )


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_start_call_returns_engine_opening(client: TestClient) -> None:
    response = _start(client, "c_test_1")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "call_id": "c_test_1",
        "utterance": greeting("outbound"),
        "audio_url": None,
        "state": "AWAITING_IDENTITY",
        "turn": 0,
    }
    # [R-26] endpoint dùng đúng câu chào công bố AI của engine, không hard-code lại
    assert AI_DISCLOSURE in body["utterance"]


def test_name_turn_asks_dob_instead_of_transferring(client: TestClient) -> None:
    _start(client, "c_test_2")
    response = _turn(client, "c_test_2", 1, "Nguyễn Văn A.")
    assert response.status_code == 200
    assert response.json() == {
        "utterance": t.ASK_DOB,
        "audio_url": None,
        "state": "AWAITING_IDENTITY",
        "ended": False,
        "outcome": None,
    }


def test_dob_turn_continues_same_session(client: TestClient, clinic: FakeClinicAPI) -> None:
    _start(client, "c_test_3")
    _turn(client, "c_test_3", 1, "Nguyễn Văn A.")
    response = _turn(client, "c_test_3", 2, "Ngày 14 tháng 3 năm 1978.")
    assert response.status_code == 200
    body = response.json()
    # Tên ở lượt 1 còn trong session nên xác minh thành công và chuyển sang hỏi nhu cầu
    assert body["state"] == "AWAITING_INTENT"
    assert body["ended"] is False
    assert body["outcome"] is None
    assert "14 tháng 10" in body["utterance"]
    assert clinic.writes == []


def test_calls_do_not_share_state(client: TestClient) -> None:
    _start(client, "c_iso_a")
    _start(client, "c_iso_b")
    _turn(client, "c_iso_a", 1, "Nguyễn Văn A.")

    # c_iso_b vẫn đang ở bước hỏi tên: câu ngày sinh không dùng được -> hỏi lại tên
    response = _turn(client, "c_iso_b", 1, "Ngày 14 tháng 3 năm 1978.")
    assert response.json()["utterance"] == t.ASK_NAME_AGAIN
    assert _turn(client, "c_iso_a", 2, "Ngày 14 tháng 3 năm 1978.").json()["state"] == (
        "AWAITING_INTENT"
    )


def test_unknown_call_returns_404(client: TestClient) -> None:
    response = _turn(client, "c_missing", 1, "xin chào")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "CALL_NOT_FOUND"


def test_silence_and_empty_transcript_map_differently(client: TestClient) -> None:
    _start(client, "c_silence")
    silence = _turn(client, "c_silence", 1, None, silence_ms=1500)
    assert silence.status_code == 200
    assert silence.json()["utterance"] == t.SILENCE

    _start(client, "c_empty")
    empty = _turn(client, "c_empty", 1, "", silence_ms=0)
    assert empty.status_code == 200
    assert empty.json()["utterance"] == t.ASK_NAME_AGAIN


def test_audio_mode_is_not_implemented(client: TestClient) -> None:
    response = _start(client, "c_audio", mode="audio")
    assert response.status_code == 501
    assert response.json()["detail"]["code"] == "AUDIO_NOT_IMPLEMENTED"
    # Không mở session cho cuộc gọi audio
    assert _turn(client, "c_audio", 1, "xin chào").status_code == 404


def test_text_call_rejects_audio_url(client: TestClient) -> None:
    _start(client, "c_text_audio")
    response = _turn(client, "c_text_audio", 1, None, audio_url="https://harness/clip.wav")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "AUDIO_URL_NOT_ALLOWED"


@pytest.mark.parametrize(
    "overrides",
    [
        {"direction": "outbound", "appointment_id": None},
        {"direction": "inbound", "appointment_id": None, "caller_number": None},
        {"direction": "inbound", "appointment_id": "apt_00417", "caller_number": "0912345600"},
        {"max_turns": 0},
    ],
)
def test_start_call_rejects_invalid_input(client: TestClient, overrides: dict[str, Any]) -> None:
    assert _start(client, "c_invalid", **overrides).status_code == 422


@pytest.mark.parametrize(
    ("turn", "text", "silence_ms"),
    [(0, "xin chào", 0), (1, None, 0), (1, "xin chào", -1)],
)
def test_turn_rejects_invalid_input(
    client: TestClient, turn: int, text: Optional[str], silence_ms: int
) -> None:
    _start(client, "c_invalid_turn")
    assert _turn(client, "c_invalid_turn", turn, text, silence_ms=silence_ms).status_code == 422


def test_orchestrator_created_once_and_clinic_closed_on_shutdown() -> None:
    created: list[FakeClinicAPI] = []
    closed: list[FakeClinicAPI] = []

    class ClosableClinic(FakeClinicAPI):
        def close(self) -> None:
            closed.append(self)

    def factory() -> FakeClinicAPI:
        clinic = ClosableClinic()
        created.append(clinic)
        return clinic

    app = create_app(clinic_factory=factory, engine_settings=EngineSettings(llm_provider="none"))
    with TestClient(app) as client:
        orchestrator = app.state.orchestrator
        _start(client, "c_lifecycle")
        _turn(client, "c_lifecycle", 1, "Nguyễn Văn A.")
        assert app.state.orchestrator is orchestrator
        assert len(created) == 1
        assert closed == []
    assert closed == created


class _RaisingOrchestrator:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def start_call(self, call):
        raise self._exc

    def handle_turn(self, call_id, caller):
        raise self._exc


_REQUEST = httpx.Request("GET", "https://clinic-mock.example/v1/appointments/apt_00417")


@pytest.mark.parametrize(
    ("exc", "status_code", "code"),
    [
        (SessionNotFound("c_x"), 404, "CALL_NOT_FOUND"),
        (httpx.ConnectError("refused", request=_REQUEST), 502, "UPSTREAM_ERROR"),
        (
            httpx.HTTPStatusError(
                "boom", request=_REQUEST, response=httpx.Response(500, request=_REQUEST)
            ),
            502,
            "UPSTREAM_ERROR",
        ),
        (httpx.ReadTimeout("slow", request=_REQUEST), 504, "UPSTREAM_TIMEOUT"),
        (RuntimeError("sk_secret_key leaked"), 500, "INTERNAL_ERROR"),
    ],
)
def test_engine_errors_map_to_http_status(
    client: TestClient, exc: Exception, status_code: int, code: str
) -> None:
    client.app.dependency_overrides[get_orchestrator] = lambda: _RaisingOrchestrator(exc)
    for response in (_start(client, "c_err"), _turn(client, "c_err", 1, "xin chào")):
        assert response.status_code == status_code
        assert response.json()["detail"]["code"] == code
        assert "sk_secret" not in response.text
        assert "Traceback" not in response.text
