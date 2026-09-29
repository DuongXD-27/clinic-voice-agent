"""CLINIC_BACKEND: sim mặc định local, mock khi deploy."""

from pathlib import Path
from uuid import uuid4

import fakeredis
import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError
from tests.transports.http.fakes import make_speech_bundle

import callbot.transports.http.main as main_module
from callbot.engine import EngineSettings
from callbot.engine.tools.clinic_mock_client import ClinicMockClient
from callbot.transports.http.call_mode import CallModeStore
from callbot.transports.http.clinic_backend import build_clinic
from callbot.transports.http.config import Settings
from clinic_mock_sim import FakeClinicAPI

ROOT = Path(__file__).resolve().parents[3]


def _settings(**values) -> Settings:
    # _env_file=None: .env của máy dev không được đổi kết quả test
    return Settings(_env_file=None, **values)


@pytest.fixture(autouse=True)
def single_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)


def test_mock_backend_uses_client() -> None:
    clinic = build_clinic(
        _settings(clinic_backend="mock", clinic_mock_base_url="https://clinic.test/v1")
    )
    assert isinstance(clinic, ClinicMockClient)
    clinic.close()


def test_mock_requires_explicit_base_url() -> None:
    with pytest.raises(ValueError, match="CLINIC_MOCK_BASE_URL is required"):
        build_clinic(_settings(clinic_backend="mock", clinic_mock_base_url=""))


def test_demo_clinic_admin_requires_bot_api_keys() -> None:
    assert _settings().demo_clinic_admin_enabled is False
    with pytest.raises(ValidationError, match="requires BOT_API_KEYS"):
        _settings(demo_clinic_admin_enabled=True, bot_api_keys="")
    with pytest.raises(ValidationError, match="CLINIC_MOCK_BASE_URL is required"):
        _settings(
            clinic_backend="mock",
            demo_clinic_admin_enabled=True,
            bot_api_keys="sk_test",
            clinic_mock_base_url="",
        )
    assert _settings(
        clinic_backend="mock",
        demo_clinic_admin_enabled=True,
        bot_api_keys="sk_test",
        clinic_mock_base_url="https://clinic.test/v1",
    ).demo_clinic_admin_enabled


def test_sim_uses_listing3_by_default() -> None:
    clinic = build_clinic(_settings(clinic_backend="sim"))
    assert isinstance(clinic, FakeClinicAPI)
    assert clinic.appointments["apt_00417"]["starts_at"] == "2026-10-14T09:00:00+07:00"
    assert clinic.strict_slot_window is False


def test_sim_can_mirror_the_mentor_mock_dataset() -> None:
    clinic = build_clinic(_settings(clinic_backend="sim", clinic_sim_dataset="mentor_mock"))
    assert clinic.appointments["apt_00417"]["starts_at"] == "2026-10-14T15:30:00+07:00"
    assert clinic.strict_slot_window is True


def test_sim_applies_comma_separated_scenarios() -> None:
    clinic = build_clinic(
        _settings(clinic_backend="sim", clinic_sim_scenario=" terminal_status, duplicate_phone ")
    )
    assert clinic.appointments["apt_00417"]["status"] == "CANCELLED"
    assert len(clinic.find_patient_by_phone("0912345600")["data"]) == 2


def test_unknown_scenario_fails_at_startup() -> None:
    with pytest.raises(ValueError, match="slot_race"):
        build_clinic(_settings(clinic_backend="sim", clinic_sim_scenario="slot_rase"))


def test_sim_refuses_more_than_one_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    with pytest.raises(RuntimeError, match="WEB_CONCURRENCY=2"):
        build_clinic(_settings(clinic_backend="sim"))


def test_unknown_backend_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(clinic_backend="fake")


def test_app_runs_a_call_on_the_sim_without_a_clinic_factory(
    monkeypatch: pytest.MonkeyPatch, redis_store_factory, redis_server, tmp_path
) -> None:
    """Đường Docker local: create_app() mặc định + CLINIC_BACKEND=sim, không cần mạng/key."""
    monkeypatch.setattr(main_module, "settings", _settings(clinic_backend="sim"))
    built: list = []
    real_build = main_module.build_clinic
    monkeypatch.setattr(
        main_module,
        "build_clinic",
        lambda settings: built.append(real_build(settings)) or built[-1],
    )
    call_mode_client = fakeredis.FakeRedis(server=redis_server, decode_responses=True)
    app = main_module.create_app(
        engine_settings=EngineSettings(),
        session_store_factory=redis_store_factory,
        speech_factory=lambda: make_speech_bundle(tmp_path),
        call_mode_factory=lambda: CallModeStore(call_mode_client, key_prefix=f"t:{uuid4().hex}"),
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/calls",
            json={
                "call_id": "c_sim_demo",
                "direction": "outbound",
                "appointment_id": "apt_00417",
                "caller_number": None,
                "locale": "vi-VN",
                "mode": "text",
                "max_turns": 20,
            },
        )

    assert response.status_code == 200, response.text
    [clinic] = built
    assert isinstance(clinic, FakeClinicAPI) and clinic.closed is True
    assert [(c.operation, c.outcome) for c in clinic.calls] == [("get_appointment", "ok")]


def _compose_env(name: str, service: str = "bot") -> dict:
    compose = yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))
    return compose["services"][service]["environment"]


def test_local_compose_defaults_to_sim_with_one_worker() -> None:
    env = _compose_env("docker-compose.yml")
    assert env["CLINIC_BACKEND"] == "${CLINIC_BACKEND:-sim}"
    assert env["WEB_CONCURRENCY"] == "${WEB_CONCURRENCY:-1}"


def test_image_forces_one_worker_when_the_sim_is_selected() -> None:
    # .env của thành viên có thể còn WEB_CONCURRENCY=2: image tự ép 1 khi sim, mock giữ nguyên
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert 'if [ \\"$CLINIC_BACKEND\\" = sim ]; then export WEB_CONCURRENCY=1; fi;' in dockerfile


def test_deploy_compose_pins_the_real_mock() -> None:
    # environment: ghi đè env_file .env — server không thể chuyển sang sim
    assert _compose_env("docker-compose.prod.yml")["CLINIC_BACKEND"] == "mock"
    # Worker đọc clinic từ config/http.yaml: deploy cũng ghi cứng mock như bot
    assert _compose_env("docker-compose.prod.yml", "livekit-worker")["CLINIC_BACKEND"] == "mock"
