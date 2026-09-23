from uuid import uuid4

import fakeredis
import pytest
from fastapi.testclient import TestClient
from tests.transports.http.fakes import make_speech_bundle

from callbot.engine import EngineSettings
from callbot.transports.http.call_mode import CallModeStore
from callbot.transports.http.main import create_app
from callbot.transports.livekit.settings import LiveKitSettings
from clinic_mock_sim import FakeClinicAPI


def _app(clinic, redis_store_factory, redis_server, tmp_path, livekit_settings: LiveKitSettings):
    call_mode_client = fakeredis.FakeRedis(server=redis_server, decode_responses=True)
    return create_app(
        clinic_factory=lambda: clinic,
        engine_settings=EngineSettings(llm_provider="none"),
        session_store_factory=redis_store_factory,
        speech_factory=lambda: make_speech_bundle(tmp_path),
        call_mode_factory=lambda: CallModeStore(call_mode_client, key_prefix=f"test:{uuid4().hex}"),
        livekit_settings_factory=lambda: livekit_settings,
    )


def test_token_returns_503_when_not_configured(
    clinic: FakeClinicAPI, redis_store_factory, redis_server, tmp_path
) -> None:
    app = _app(clinic, redis_store_factory, redis_server, tmp_path, LiveKitSettings(_env_file=None))
    with TestClient(app) as client:
        response = client.post("/livekit/token", json={})

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "LIVEKIT_NOT_CONFIGURED"


def test_token_issues_jwt_with_room_join_grant(
    clinic: FakeClinicAPI, redis_store_factory, redis_server, tmp_path
) -> None:
    pytest.importorskip("livekit", reason="cần extra [livekit] cài livekit-api")
    settings = LiveKitSettings(
        _env_file=None,
        livekit_url="wss://example.livekit.cloud",
        livekit_api_key="test-key",
        livekit_api_secret="test-secret-at-least-32-bytes-long",
    )
    app = _app(clinic, redis_store_factory, redis_server, tmp_path, settings)
    with TestClient(app) as client:
        response = client.post("/livekit/token", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["url"] == "wss://example.livekit.cloud"
    assert body["room_name"].startswith("web-")
    assert body["identity"].startswith("web-")
    assert isinstance(body["token"], str) and body["token"].count(".") == 2  # JWT có 3 phần


def test_token_reuses_provided_room_name(
    clinic: FakeClinicAPI, redis_store_factory, redis_server, tmp_path
) -> None:
    pytest.importorskip("livekit", reason="cần extra [livekit] cài livekit-api")
    settings = LiveKitSettings(
        _env_file=None,
        livekit_url="wss://example.livekit.cloud",
        livekit_api_key="test-key",
        livekit_api_secret="test-secret-at-least-32-bytes-long",
    )
    app = _app(clinic, redis_store_factory, redis_server, tmp_path, settings)
    with TestClient(app) as client:
        response = client.post("/livekit/token", json={"room_name": "my-fixed-room"})

    assert response.json()["room_name"] == "my-fixed-room"


def test_token_attaches_caller_number_as_participant_attribute(
    clinic: FakeClinicAPI, redis_store_factory, redis_server, tmp_path
) -> None:
    """caller_number phải nằm trong token để worker.py đọc lại qua participant.attributes
    (xem call_bridge.py: đây là cách demo web giả lập caller ID vì không phải PSTN)."""
    pytest.importorskip("livekit", reason="cần extra [livekit] cài livekit-api")
    jwt = pytest.importorskip("jwt", reason="cần PyJWT để decode token trong test")
    secret = "test-secret-at-least-32-bytes-long"
    settings = LiveKitSettings(
        _env_file=None,
        livekit_url="wss://example.livekit.cloud",
        livekit_api_key="test-key",
        livekit_api_secret=secret,
    )
    app = _app(clinic, redis_store_factory, redis_server, tmp_path, settings)
    with TestClient(app) as client:
        response = client.post("/livekit/token", json={"caller_number": "0912345600"})

    assert response.status_code == 200
    decoded = jwt.decode(response.json()["token"], secret, algorithms=["HS256"])
    assert decoded["attributes"] == {"direction": "inbound", "caller_number": "0912345600"}


def test_token_rejects_invalid_caller_number(
    clinic: FakeClinicAPI, redis_store_factory, redis_server, tmp_path
) -> None:
    settings = LiveKitSettings(
        _env_file=None,
        livekit_url="wss://example.livekit.cloud",
        livekit_api_key="test-key",
        livekit_api_secret="test-secret-at-least-32-bytes-long",
    )
    app = _app(clinic, redis_store_factory, redis_server, tmp_path, settings)
    with TestClient(app) as client:
        response = client.post(
            "/livekit/token", json={"caller_number": "<script>alert(1)</script>"}
        )

    assert response.status_code == 422


def test_token_omits_caller_number_attribute_when_blank(
    clinic: FakeClinicAPI, redis_store_factory, redis_server, tmp_path
) -> None:
    """direction luôn có mặt trong attributes (worker.py cần nó để chọn nhánh
    inbound/outbound), nhưng caller_number rỗng thì không được đưa vào attributes."""
    pytest.importorskip("livekit", reason="cần extra [livekit] cài livekit-api")
    jwt = pytest.importorskip("jwt", reason="cần PyJWT để decode token trong test")
    secret = "test-secret-at-least-32-bytes-long"
    settings = LiveKitSettings(
        _env_file=None,
        livekit_url="wss://example.livekit.cloud",
        livekit_api_key="test-key",
        livekit_api_secret=secret,
    )
    app = _app(clinic, redis_store_factory, redis_server, tmp_path, settings)
    with TestClient(app) as client:
        response = client.post("/livekit/token", json={"caller_number": "   "})

    decoded = jwt.decode(response.json()["token"], secret, algorithms=["HS256"])
    assert decoded["attributes"] == {"direction": "inbound"}


def test_token_outbound_requires_appointment_id(
    clinic: FakeClinicAPI, redis_store_factory, redis_server, tmp_path
) -> None:
    settings = LiveKitSettings(
        _env_file=None,
        livekit_url="wss://example.livekit.cloud",
        livekit_api_key="test-key",
        livekit_api_secret="test-secret-at-least-32-bytes-long",
    )
    app = _app(clinic, redis_store_factory, redis_server, tmp_path, settings)
    with TestClient(app) as client:
        response = client.post("/livekit/token", json={"direction": "outbound"})

    assert response.status_code == 422


def test_token_outbound_rejects_caller_number(
    clinic: FakeClinicAPI, redis_store_factory, redis_server, tmp_path
) -> None:
    settings = LiveKitSettings(
        _env_file=None,
        livekit_url="wss://example.livekit.cloud",
        livekit_api_key="test-key",
        livekit_api_secret="test-secret-at-least-32-bytes-long",
    )
    app = _app(clinic, redis_store_factory, redis_server, tmp_path, settings)
    with TestClient(app) as client:
        response = client.post(
            "/livekit/token",
            json={
                "direction": "outbound",
                "appointment_id": "apt_00417",
                "caller_number": "0912345600",
            },
        )

    assert response.status_code == 422


def test_token_inbound_rejects_appointment_id(
    clinic: FakeClinicAPI, redis_store_factory, redis_server, tmp_path
) -> None:
    settings = LiveKitSettings(
        _env_file=None,
        livekit_url="wss://example.livekit.cloud",
        livekit_api_key="test-key",
        livekit_api_secret="test-secret-at-least-32-bytes-long",
    )
    app = _app(clinic, redis_store_factory, redis_server, tmp_path, settings)
    with TestClient(app) as client:
        response = client.post("/livekit/token", json={"appointment_id": "apt_00417"})

    assert response.status_code == 422


def test_token_outbound_attaches_appointment_id_attribute(
    clinic: FakeClinicAPI, redis_store_factory, redis_server, tmp_path
) -> None:
    pytest.importorskip("livekit", reason="cần extra [livekit] cài livekit-api")
    jwt = pytest.importorskip("jwt", reason="cần PyJWT để decode token trong test")
    secret = "test-secret-at-least-32-bytes-long"
    settings = LiveKitSettings(
        _env_file=None,
        livekit_url="wss://example.livekit.cloud",
        livekit_api_key="test-key",
        livekit_api_secret=secret,
    )
    app = _app(clinic, redis_store_factory, redis_server, tmp_path, settings)
    with TestClient(app) as client:
        response = client.post(
            "/livekit/token", json={"direction": "outbound", "appointment_id": "apt_00417"}
        )

    assert response.status_code == 200
    decoded = jwt.decode(response.json()["token"], secret, algorithms=["HS256"])
    assert decoded["attributes"] == {"direction": "outbound", "appointment_id": "apt_00417"}


if __name__ == "__main__":
    pytest.main([__file__])
