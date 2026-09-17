"""Independent Product Contract rev 1.1 schema verification.

The expected fields and enums below are copied from Product Contract section
4.1.2 (Listings 1 and 2).  Deliberately do not import the application's
Pydantic request/response models here: those models are the subject under test,
not the oracle for these assertions.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from callbot.engine.tools.clinic_mock_client import ClinicMockClient
from callbot.transports.http.main import app
from callbot.transports.http.schemas import TurnRequest

CALL_STATES = {
    "AWAITING_IDENTITY",
    "AWAITING_INTENT",
    "AWAITING_CONFIRMATION",
    "OFFERING_SLOTS",
    "CLOSING",
    "ENDED",
}

END_OUTCOMES = {
    "CONFIRMED",
    "CANCELLED",
    "RESCHEDULED",
    "TRANSFERRED",
    "UNREACHABLE",
    "BOOKED",
    "SCHEDULED",
}

# None means that the official immutable Rev 1.1 value is not present in this
# repository.  It must be replaced only with the value published by the
# programme; an environment variable or a locally computed digest is not an
# acceptable contract oracle.
EXPECTED_CLINIC_MOCK_DIGEST: str | None = None
CLINIC_MOCK_IMAGE = "clinic-mock:latest"

START_REQUEST_CONTRACT = {
    "call_id": ({"string"}, None),
    "direction": ({"string"}, {"inbound", "outbound"}),
    "appointment_id": ({"string", "null"}, None),
    "caller_number": ({"string", "null"}, None),
    "locale": ({"string"}, None),
    "mode": ({"string"}, {"text", "audio"}),
    "max_turns": ({"integer"}, None),
}

START_RESPONSE_CONTRACT = {
    "call_id": ({"string"}, None),
    "utterance": ({"string"}, None),
    "audio_url": ({"string", "null"}, None),
    "state": ({"string"}, CALL_STATES),
    "turn": ({"integer"}, None),
}

TURN_REQUEST_CONTRACT = {
    "turn": ({"integer"}, None),
    "audio_url": ({"string", "null"}, None),
    "text": ({"string", "null"}, None),
    "silence_ms": ({"integer"}, None),
}

TURN_RESPONSE_CONTRACT = {
    "utterance": ({"string"}, None),
    "audio_url": ({"string", "null"}, None),
    "state": ({"string"}, CALL_STATES),
    "ended": ({"boolean"}, None),
    "outcome": ({"string", "null"}, END_OUTCOMES),
}


def _operation(path: str, method: str) -> dict[str, Any]:
    return app.openapi()["paths"][path][method.lower()]


def _resolve_ref(schema: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if ref is None:
        return schema
    prefix = "#/components/schemas/"
    assert ref.startswith(prefix), f"Unsupported OpenAPI reference: {ref}"
    return app.openapi()["components"]["schemas"][ref.removeprefix(prefix)]


def _request_schema(path: str) -> dict[str, Any]:
    schema = _operation(path, "post")["requestBody"]["content"]["application/json"]["schema"]
    return _resolve_ref(schema)


def _response_schema(path: str) -> dict[str, Any]:
    schema = _operation(path, "post")["responses"]["200"]["content"]["application/json"]["schema"]
    return _resolve_ref(schema)


def _types_and_enum(schema: dict[str, Any]) -> tuple[set[str], set[str] | None]:
    alternatives = schema.get("anyOf", [schema])
    types = {part["type"] for part in alternatives if "type" in part}
    enum_values: set[str] = set()
    enum_declared = False
    for part in alternatives:
        if "enum" in part:
            enum_declared = True
            enum_values.update(part["enum"])
    return types, enum_values if enum_declared else None


def _assert_object_schema(
    actual: dict[str, Any],
    expected: dict[str, tuple[set[str], set[str] | None]],
) -> None:
    assert actual.get("type") == "object"
    assert set(actual.get("properties", {})) == set(expected)
    for field_name, expected_shape in expected.items():
        assert _types_and_enum(actual["properties"][field_name]) == expected_shape


def _assert_all_listing_fields_required(
    actual: dict[str, Any],
    expected: dict[str, tuple[set[str], set[str] | None]],
) -> None:
    """Team interpretation: Listing fields are present even when nullable.

    Listings 1 and 2 show every field, but the supplied contract excerpt does
    not explicitly say that nullable fields MUST be present.  Failures from
    this helper are therefore LISTING_CONFORMANCE, not CONTRACT failures.
    """
    assert set(actual.get("required", [])) == set(expected)


def _assert_start_response(body: dict[str, Any], call_id: str) -> None:
    assert set(body) == set(START_RESPONSE_CONTRACT)
    assert body["call_id"] == call_id
    assert isinstance(body["utterance"], str)
    assert isinstance(body["audio_url"], str) or body["audio_url"] is None
    assert body["state"] in CALL_STATES
    assert type(body["turn"]) is int
    assert body["turn"] == 0


def _assert_turn_response(body: dict[str, Any]) -> None:
    assert set(body) == set(TURN_RESPONSE_CONTRACT)
    assert isinstance(body["utterance"], str)
    assert isinstance(body["audio_url"], str) or body["audio_url"] is None
    assert body["state"] in CALL_STATES
    assert type(body["ended"]) is bool
    if body["ended"]:
        assert body["outcome"] in END_OUTCOMES
    else:
        assert body["outcome"] is None


def _registered_routes(router: Any) -> list[Any]:
    """Flatten FastAPI's route tree across old and new router internals."""
    flattened: list[Any] = []
    for route in router.routes:
        if hasattr(route, "path"):
            flattened.append(route)
        included_router = getattr(route, "original_router", None)
        if included_router is not None:
            flattened.extend(_registered_routes(included_router))
    return flattened


def test_contract_start_call_request_openapi_shape_matches_listing_1() -> None:
    _assert_object_schema(_request_schema("/v1/calls"), START_REQUEST_CONTRACT)


def test_contract_start_call_response_openapi_shape_matches_listing_1() -> None:
    _assert_object_schema(_response_schema("/v1/calls"), START_RESPONSE_CONTRACT)


def test_contract_turn_request_openapi_shape_matches_listing_2() -> None:
    _assert_object_schema(_request_schema("/v1/calls/{call_id}/turn"), TURN_REQUEST_CONTRACT)


def test_contract_turn_response_openapi_shape_matches_listing_2() -> None:
    _assert_object_schema(_response_schema("/v1/calls/{call_id}/turn"), TURN_RESPONSE_CONTRACT)


def test_listing_conformance_start_call_request_fields_are_required() -> None:
    _assert_all_listing_fields_required(_request_schema("/v1/calls"), START_REQUEST_CONTRACT)


def test_listing_conformance_start_call_response_fields_are_required() -> None:
    _assert_all_listing_fields_required(_response_schema("/v1/calls"), START_RESPONSE_CONTRACT)


def test_listing_conformance_turn_request_fields_are_required() -> None:
    _assert_all_listing_fields_required(
        _request_schema("/v1/calls/{call_id}/turn"), TURN_REQUEST_CONTRACT
    )


def test_listing_conformance_turn_response_fields_are_required() -> None:
    _assert_all_listing_fields_required(
        _response_schema("/v1/calls/{call_id}/turn"), TURN_RESPONSE_CONTRACT
    )


@pytest.mark.parametrize(
    ("call_id", "direction", "appointment_id", "caller_number"),
    [
        ("c_contract_outbound", "outbound", "apt_00417", None),
        ("c_contract_inbound", "inbound", None, "+84912345678"),
    ],
)
def test_contract_start_call_accepts_direction_shapes(
    client: TestClient,
    call_id: str,
    direction: str,
    appointment_id: str | None,
    caller_number: str | None,
) -> None:
    response = client.post(
        "/v1/calls",
        json={
            "call_id": call_id,
            "direction": direction,
            "appointment_id": appointment_id,
            "caller_number": caller_number,
            "locale": "vi-VN",
            "mode": "text",
            "max_turns": 20,
        },
    )
    assert response.status_code == 200
    _assert_start_response(response.json(), call_id)
    assert response.json()["audio_url"] is None


def test_team_scope_start_call_audio_mode_is_not_implemented(client: TestClient) -> None:
    """F-02 is text-only; the contract still requires audio, so this is a known gap."""
    response = client.post(
        "/v1/calls",
        json={
            "call_id": "c_contract_audio",
            "direction": "outbound",
            "appointment_id": "apt_00417",
            "caller_number": None,
            "locale": "vi-VN",
            "mode": "audio",
            "max_turns": 20,
        },
    )
    assert response.status_code == 501
    assert response.json()["detail"]["code"] == "AUDIO_NOT_IMPLEMENTED"


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("direction", "sideways"),
        ("mode", "video"),
    ],
)
def test_contract_start_call_rejects_values_outside_enums(
    client: TestClient, field_name: str, bad_value: object
) -> None:
    payload: dict[str, object] = {
        "call_id": "c_contract_invalid_start",
        "direction": "outbound",
        "appointment_id": "apt_00417",
        "caller_number": None,
        "locale": "vi-VN",
        "mode": "text",
        "max_turns": 20,
    }
    payload[field_name] = bad_value
    assert client.post("/v1/calls", json=payload).status_code == 422


def test_team_hardening_start_call_rejects_coercible_string_integer(client: TestClient) -> None:
    """Strictness policy; the contract excerpt does not require rejection."""
    payload: dict[str, object] = {
        "call_id": "c_hardening_invalid_start",
        "direction": "outbound",
        "appointment_id": "apt_00417",
        "caller_number": None,
        "locale": "vi-VN",
        "mode": "text",
        "max_turns": "20",
    }
    assert client.post("/v1/calls", json=payload).status_code == 422


@pytest.mark.parametrize(
    ("call_id", "text", "silence_ms"),
    [
        ("c_turn_text", "Tôi đồng ý", 0),
        ("c_turn_silence", None, 1500),
    ],
)
def test_contract_turn_accepts_text_and_silence_shapes(
    client: TestClient,
    call_id: str,
    text: str | None,
    silence_ms: int,
) -> None:
    start_response = client.post(
        "/v1/calls",
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
    assert start_response.status_code == 200

    response = client.post(
        f"/v1/calls/{call_id}/turn",
        json={
            "turn": 1,
            "audio_url": None,
            "text": text,
            "silence_ms": silence_ms,
        },
    )
    assert response.status_code == 200
    _assert_turn_response(response.json())


def test_contract_turn_request_model_accepts_audio_shape() -> None:
    """Audio is not served over HTTP yet (501), but the request model keeps the Listing 2 shape."""
    request = TurnRequest.model_validate(
        {
            "turn": 1,
            "audio_url": "https://harness/clips/c_turn_audio/1.wav",
            "text": None,
            "silence_ms": 0,
        }
    )
    assert request.audio_url == "https://harness/clips/c_turn_audio/1.wav"


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [("turn", "1"), ("silence_ms", "0")],
)
def test_team_hardening_turn_rejects_coercible_string_integers(
    client: TestClient, field_name: str, bad_value: object
) -> None:
    """Strictness policy; the contract excerpt does not require rejection."""
    payload: dict[str, object] = {
        "turn": 1,
        "audio_url": None,
        "text": "Xin chào",
        "silence_ms": 0,
    }
    payload[field_name] = bad_value
    response = client.post("/v1/calls/c_contract_invalid_turn/turn", json=payload)
    assert response.status_code == 422


def test_contract_route_table_has_business_routes_and_no_harness_routes() -> None:
    route_table = {
        (method, route.path)
        for route in _registered_routes(app)
        for method in getattr(route, "methods", set())
    }
    business_routes = {item for item in route_table if item[1].startswith("/v1/")}
    assert business_routes == {
        ("POST", "/v1/calls"),
        ("POST", "/v1/calls/{call_id}/turn"),
    }
    assert not any(path.startswith("/_harness/") for _, path in route_table)


def test_contract_clinic_client_never_requests_harness_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_paths: list[str] = []

    def capture_send(
        _client: httpx.Client, request: httpx.Request, **_kwargs: Any
    ) -> httpx.Response:
        requested_paths.append(request.url.path)
        return httpx.Response(200, json={}, request=request)

    monkeypatch.setattr(httpx.Client, "send", capture_send)
    clinic = ClinicMockClient("https://clinic-mock.example/v1")

    calls: list[Callable[[], object]] = [
        lambda: clinic.find_patient_by_phone("0912345678"),
        lambda: clinic.get_slots("clinic_1", "2026-10-01", "2026-10-08"),
        lambda: clinic.get_appointment("apt_00417"),
        lambda: clinic.create_appointment("patient_1", "slot_1", "key-create"),
        lambda: clinic.confirm_appointment("apt_00417", 1, "key-confirm"),
        lambda: clinic.cancel_appointment("apt_00417", "NO_LONGER_NEEDED", 1, "key-cancel"),
        lambda: clinic.transfer_appointment("apt_00417", "PATIENT_REQUEST", 1, "key-transfer"),
        lambda: clinic.reschedule_appointment("apt_00417", "slot_2", 1, "key-reschedule"),
    ]
    for make_request in calls:
        make_request()

    assert requested_paths
    assert not any(path.startswith("/_harness/") for path in requested_paths)


def test_external_blocked_clinic_mock_image_matches_official_digest() -> None:
    if EXPECTED_CLINIC_MOCK_DIGEST is None:
        pytest.skip(
            "BLOCKED: the official Contract Rev 1.1 clinic-mock SHA256 digest "
            "is not present in the repository"
        )

    docker = shutil.which("docker")
    assert docker is not None, "Docker is required to inspect the clinic-mock image"
    inspected = subprocess.run(
        [
            docker,
            "image",
            "inspect",
            "--format",
            "{{json .RepoDigests}}",
            CLINIC_MOCK_IMAGE,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    repo_digests = json.loads(inspected.stdout)
    actual_digests = {value.rsplit("@", 1)[-1] for value in repo_digests or []}
    assert EXPECTED_CLINIC_MOCK_DIGEST in actual_digests
