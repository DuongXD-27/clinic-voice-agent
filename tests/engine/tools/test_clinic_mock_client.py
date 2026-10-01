"""ClinicMockClient trên httpx.MockTransport: header, tham số phân trang, phân loại lỗi, telemetry."""

import json
from typing import Any, Callable

import httpx
import pytest

from callbot.engine.errors import ClinicAPIError
from callbot.engine.tools.clinic_mock_client import ClinicMockClient
from callbot.engine.tools.telemetry import collect_api_calls

Handler = Callable[[httpx.Request], httpx.Response]


def _client(handler: Handler, api_key: str = "sk_test") -> ClinicMockClient:
    client = ClinicMockClient("https://clinic.test/v1", api_key)
    client._client = httpx.Client(  # noqa: SLF001 — thay transport, giữ header/base_url thật
        base_url="https://clinic.test/v1",
        headers=client._client.headers,
        transport=httpx.MockTransport(handler),
    )
    return client


def _envelope(
    status: int, code: str, message: str = "", request_id: str = "req_1"
) -> httpx.Response:
    return httpx.Response(
        status, json={"error": {"code": code, "message": message, "request_id": request_id}}
    )


def test_api_key_must_have_sk_prefix() -> None:
    with pytest.raises(ValueError):
        ClinicMockClient("https://clinic.test/v1", "sk-dash-style")


def test_read_sends_bearer_and_pagination_params() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": [], "next_cursor": None, "has_more": False})

    client = _client(handler, "sk_abc")
    page = client.get_slots("cl_vinmec", "2026-10-14T00:00:00+07:00", "2026-10-20T00:00:00+07:00")
    client.find_patient_by_phone("0912345600", cursor="eyJvZmZzZXQiOjI1fQ", limit=50)

    assert page == {"data": [], "next_cursor": None, "has_more": False}
    slots, patients = seen
    assert slots.headers["Authorization"] == "Bearer sk_abc"
    assert slots.url.path == "/v1/slots" and slots.url.params["limit"] == "100"
    assert slots.url.params["from"] == "2026-10-14T00:00:00+07:00"
    assert "cursor" not in slots.url.params
    assert patients.url.params["cursor"] == "eyJvZmZzZXQiOjI1fQ"
    assert patients.url.params["limit"] == "50"


def test_write_headers_and_unreachable_body_per_4_2_5() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"status": "UNREACHABLE", "attempt_count": 1, "version": 4})

    client = _client(handler)
    with collect_api_calls() as records:
        client.mark_unreachable("apt_00417", "SILENCE", 3, "c_1:3:unreachable")
        client.cancel_appointment("apt_00417", "COST", 3, "c_1:4:cancel", confirmed=True)

    unreachable, cancel = seen
    assert unreachable.headers["Idempotency-Key"] == "c_1:3:unreachable"
    assert unreachable.headers["If-Match"] == "3"
    assert [record.if_match_used for record in records] == [True, True]
    assert json.loads(unreachable.content) == {
        "unreachable_reason": "SILENCE"
    }  # không attempt_count
    assert json.loads(cancel.content) == {"cancel_reason": "COST", "confirmed": True}


def test_list_without_data_key_is_bad_response() -> None:
    client = _client(lambda _r: httpx.Response(200, json={"patients": []}))
    with pytest.raises(ClinicAPIError) as exc:
        client.find_patient_by_phone("0912345600")
    assert exc.value.code == "BAD_RESPONSE"


@pytest.mark.parametrize(
    "status, code, outcome_known, retryable",
    [
        (400, "INVALID_REQUEST", True, False),
        (401, "BAD_KEY", True, False),
        (404, "NOT_FOUND", True, False),
        (409, "VERSION_CONFLICT", True, False),
        (409, "SLOT_TAKEN", True, False),
        (409, "CONFIRMATION_REQUIRED", True, False),
        (409, "INVALID_STATE_TRANSITION", True, False),
        (422, "IDEMPOTENCY_CONFLICT", True, False),
        (429, "RATE_LIMITED", True, True),
        (503, "UPSTREAM", False, True),
        (500, "INTERNAL_ERROR", False, True),
    ],
)
def test_error_envelope_maps_to_clinic_api_error(status, code, outcome_known, retryable) -> None:
    client = _client(lambda _r: _envelope(status, code, "boom", "req_42"))
    with pytest.raises(ClinicAPIError) as exc:
        client.confirm_appointment("apt_00417", 3, "key")
    error = exc.value
    assert (error.status, error.code, error.message) == (status, code, "boom")
    assert error.request_id == "req_42"
    assert error.outcome_known is outcome_known and error.retryable is retryable


def test_error_without_envelope_falls_back_to_status_code() -> None:
    client = _client(lambda _r: httpx.Response(404, text="<html>not found</html>"))
    with pytest.raises(ClinicAPIError) as exc:
        client.get_appointment("apt_x")
    assert exc.value.code == "NOT_FOUND" and exc.value.status == 404


def test_2xx_without_a_json_body_is_an_unknown_outcome() -> None:
    """Lệnh ghi đã tới mock (2xx) nhưng không đọc được body: chưa rõ đã áp dụng gì (T-12)."""
    client = _client(lambda _r: httpx.Response(200, text="<html>ok</html>"))
    with pytest.raises(ClinicAPIError) as exc:
        client.confirm_appointment("apt_00417", 3, "key")
    assert (exc.value.status, exc.value.code) == (200, "BAD_RESPONSE")
    assert exc.value.outcome_known is False


def test_connect_error_is_known_rejection_but_timeout_is_unknown() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ClinicAPIError) as refused:
        _client(refuse).confirm_appointment("apt_00417", 3, "key")
    assert refused.value.code == "CONNECT_ERROR" and refused.value.outcome_known is True

    with pytest.raises(ClinicAPIError) as timed_out:
        _client(slow).confirm_appointment("apt_00417", 3, "key")
    assert timed_out.value.code == "TIMEOUT" and timed_out.value.outcome_known is False
    assert timed_out.value.retryable is True


def test_every_request_emits_api_call_record_without_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/confirm"):
            return _envelope(409, "VERSION_CONFLICT", request_id="req_v")
        return httpx.Response(200, json={"appointment_id": "apt_00417", "version": 3})

    client = _client(handler)
    with collect_api_calls() as calls:
        client.get_appointment("apt_00417")
        with pytest.raises(ClinicAPIError):
            client.confirm_appointment("apt_00417", 2, "key")

    ok, rejected = calls
    assert (ok.operation, ok.method, ok.path, ok.status, ok.outcome) == (
        "get_appointment",
        "GET",
        "/appointments/apt_00417",
        200,
        "ok",
    )
    assert (rejected.code, rejected.request_id, rejected.outcome) == (
        "VERSION_CONFLICT",
        "req_v",
        "rejected",
    )
    assert "verify" not in json.dumps([c.to_dict() for c in calls])


def test_client_never_calls_harness_endpoints() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json={"data": [], "next_cursor": None, "has_more": False})

    client = _client(handler)
    calls: list[Callable[[], Any]] = [
        lambda: client.find_patient_by_phone("0912345600"),
        lambda: client.get_slots("cl", "2026-10-14T00:00:00+07:00", "2026-10-15T00:00:00+07:00"),
        lambda: client.get_appointment("apt_00417"),
        lambda: client.create_appointment("pt", "slot", "k"),
        lambda: client.confirm_appointment("apt_00417", 1, "k"),
        lambda: client.cancel_appointment("apt_00417", "COST", 1, "k", confirmed=True),
        lambda: client.transfer_appointment("apt_00417", "PATIENT_REQUEST", 1, "k"),
        lambda: client.reschedule_appointment("apt_00417", "slot", 1, "k"),
        lambda: client.mark_unreachable("apt_00417", "SILENCE", 1, "k"),
    ]
    for call in calls:
        call()
    assert len(paths) == 9 and all(p.startswith("/v1/") for p in paths)
    assert not any("/_harness" in p for p in paths)


def test_2xx_without_a_json_body_is_traced_as_unknown() -> None:
    client = _client(lambda _r: httpx.Response(200, text="<html>ok</html>"))
    with collect_api_calls() as calls, pytest.raises(ClinicAPIError):
        client.confirm_appointment("apt_00417", 3, "key")
    assert [(c.status, c.code, c.outcome) for c in calls] == [(200, "BAD_RESPONSE", "unknown")]
