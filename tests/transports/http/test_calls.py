from typing import Any, Optional

import httpx
import pytest
from fastapi.testclient import TestClient
from tests.engine.fake_clinic import FakeClinicAPI

from callbot.engine import (
    CallBusy,
    CallConflict,
    CallEnded,
    EngineSettings,
    InMemorySessionStore,
    ReconciliationRequired,
    SessionNotFound,
    SessionStoreUnavailable,
    TurnConflict,
    TurnOutOfOrder,
)
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

    # c_iso_b chưa có tên: giữ ngày sinh (T-02) nhưng vẫn phải hỏi tên — không dùng tên của c_iso_a
    response = _turn(client, "c_iso_b", 1, "Ngày 14 tháng 3 năm 1978.")
    assert response.json()["utterance"] == t.ASK_NAME_AFTER_DOB
    assert response.json()["state"] == "AWAITING_IDENTITY"
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

    app = create_app(
        clinic_factory=factory,
        engine_settings=EngineSettings(llm_provider="none"),
        session_store_factory=InMemorySessionStore,
    )
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
        (CallConflict("c_x"), 409, "CALL_CONFLICT"),
        (TurnConflict("c_x"), 409, "TURN_CONFLICT"),
        (TurnOutOfOrder("c_x", 3, 2), 409, "TURN_OUT_OF_ORDER"),
        (CallEnded("c_x"), 409, "CALL_ENDED"),
        (CallBusy("c_x"), 409, "CALL_BUSY"),
        (ReconciliationRequired("c_x", 2, "sk_secret"), 409, "CALL_RECONCILIATION_REQUIRED"),
        (SessionStoreUnavailable("postgresql://sk_secret@db"), 503, "SESSION_STORE_UNAVAILABLE"),
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


# --- F-03: thứ tự lượt và replay qua HTTP ------------------------------------------------


def test_turn_order_errors_over_http(client: TestClient) -> None:
    _start(client, "c_http_order")
    first = _turn(client, "c_http_order", 1, "Nguyễn Văn A.")

    skipped = _turn(client, "c_http_order", 3, "14/03/1978")
    assert skipped.status_code == 409
    assert skipped.json()["detail"]["code"] == "TURN_OUT_OF_ORDER"
    assert skipped.json()["detail"]["expected_turn"] == 2

    conflict = _turn(client, "c_http_order", 1, "Trần Văn B")
    assert (conflict.status_code, conflict.json()["detail"]["code"]) == (409, "TURN_CONFLICT")

    replay = _turn(client, "c_http_order", 1, "Nguyễn Văn A.")
    assert replay.status_code == 200 and replay.json() == first.json()


def test_start_call_is_idempotent_over_http(client: TestClient) -> None:
    first = _start(client, "c_http_open")
    _turn(client, "c_http_open", 1, "Nguyễn Văn A.")
    again = _start(client, "c_http_open")
    assert again.status_code == 200 and again.json() == first.json()
    # Context không bị reset: lượt 2 vẫn là ngày sinh
    assert _turn(client, "c_http_open", 2, "14/03/1978").json()["state"] == "AWAITING_INTENT"

    other = _start(client, "c_http_open", max_turns=5)
    assert (other.status_code, other.json()["detail"]["code"]) == (409, "CALL_CONFLICT")


def test_new_turn_after_end_returns_call_ended(client: TestClient) -> None:
    _start(client, "c_http_end")
    last = _turn(client, "c_http_end", 1, "cho tôi gặp nhân viên")
    assert last.json()["ended"] is True
    after = _turn(client, "c_http_end", 2, "alo")
    assert (after.status_code, after.json()["detail"]["code"]) == (409, "CALL_ENDED")
    assert _turn(client, "c_http_end", 1, "cho tôi gặp nhân viên").json() == last.json()


def test_ready_reports_session_store(client: TestClient) -> None:
    assert client.get("/ready").json() == {"status": "ready"}

    class Down(InMemorySessionStore):
        def check_ready(self) -> None:
            raise SessionStoreUnavailable("db down")

    app = create_app(
        clinic_factory=FakeClinicAPI,
        engine_settings=EngineSettings(llm_provider="none"),
        session_store_factory=Down,
    )
    with TestClient(app) as down:
        response = down.get("/ready")
        assert response.status_code == 503
        assert response.json()["code"] == "SESSION_STORE_UNAVAILABLE"
        assert down.get("/health").status_code == 200  # liveness không phụ thuộc DB


# --- F-04: Information Extraction mới trên đường HTTP -------------------------------------


def _conversation(client: TestClient, call_id: str, lines: list[Optional[str]], **start):
    assert _start(client, call_id, **start).status_code == 200
    bodies = []
    for turn, line in enumerate(lines, start=1):
        response = (
            _turn(client, call_id, turn, None, silence_ms=2000)
            if line is None
            else _turn(client, call_id, turn, line)
        )
        assert response.status_code == 200, response.text
        bodies.append(response.json())
    return bodies


@pytest.mark.parametrize(
    ("call_id", "start", "lines", "outcome", "write"),
    [
        (
            "c_ie_confirm",
            {},
            ["Nguyễn Văn A", "14/03/1978", "Có, tôi đến được."],
            "CONFIRMED",
            ("apt_00417", "CONFIRMED", {}),
        ),
        (
            "c_ie_cancel",
            {},
            ["Nguyễn Văn A", "14/03/1978", "Tôi muốn hủy lịch", "Vâng", "Hủy đi"],
            "CANCELLED",
            ("apt_00417", "CANCELLED", {"cancel_reason": "UNSPECIFIED"}),
        ),
        (
            "c_ie_resched",
            {},
            ["Nguyễn Văn A", "14/03/1978", "Cho tôi đổi lịch", "10 giờ sáng", "Được"],
            "RESCHEDULED",
            ("apt_00417", "RESCHEDULED", {"new_slot_id": "slot_aa01"}),
        ),
        (
            "c_ie_book",
            {"direction": "inbound", "appointment_id": None, "caller_number": "0912345600"},
            ["Nguyễn Văn A", "14/03/1978", "Tôi muốn đặt lịch khám", "khung 1", "Đồng ý"],
            "BOOKED",
            ("apt_new_1", "BOOKED", {"slot_id": "slot_aa01"}),
        ),
        (
            "c_ie_voicemail",
            {},
            ["Quý khách vui lòng để lại lời nhắn sau tiếng bíp"],
            "UNREACHABLE",
            ("apt_00417", "UNREACHABLE", {"unreachable_reason": "VOICEMAIL"}),
        ),
    ],
)
def test_information_extraction_over_http(
    client: TestClient,
    clinic: FakeClinicAPI,
    call_id: str,
    start: dict[str, Any],
    lines: list[str],
    outcome: str,
    write: tuple,
) -> None:
    bodies = _conversation(client, call_id, lines, **start)
    assert bodies[-1]["ended"] is True and bodies[-1]["outcome"] == outcome
    assert clinic.writes == [write]

    store = client.app.state.session_store
    last = store.get_turn(call_id, len(lines))
    assert last.status == "COMPLETED" and last.extraction is not None
    fields_found = [
        (name, item["provenance"], item["span"])
        for name, item in last.extraction.items()
        if isinstance(item, dict) and item.get("provenance") not in (None, "NONE")
    ]
    assert fields_found, last.extraction
    assert all(span for _, _, span in fields_found)
    [command] = store.list_commands(call_id)
    assert command.status == "SUCCEEDED"


def test_http_app_on_postgres_replays_across_app_restart(
    postgres_store: Any, postgres_url: str
) -> None:
    from callbot.engine.session.postgres import PostgresSessionStore

    clinic = FakeClinicAPI()

    def new_app():
        def store_factory():
            store = PostgresSessionStore(postgres_url, max_size=4)
            store.open()
            return store

        return create_app(
            clinic_factory=lambda: clinic,
            engine_settings=EngineSettings(llm_provider="none"),
            session_store_factory=store_factory,
        )

    with TestClient(new_app()) as first:
        assert first.get("/ready").json() == {"status": "ready"}
        _start(first, "c_pg_http")
        asked = _turn(first, "c_pg_http", 1, "Nguyễn Văn A.").json()

    with TestClient(new_app()) as second:
        assert _start(second, "c_pg_http").json()["utterance"] == greeting("outbound")
        assert _turn(second, "c_pg_http", 1, "Nguyễn Văn A.").json() == asked
        assert _turn(second, "c_pg_http", 2, "14/03/1978").json()["state"] == "AWAITING_INTENT"
        done = _turn(second, "c_pg_http", 3, "Có, tôi đến được").json()
        assert done["outcome"] == "CONFIRMED"
    assert clinic.writes == [("apt_00417", "CONFIRMED", {})]
