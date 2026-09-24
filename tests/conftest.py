from collections.abc import Iterator
from uuid import uuid4

import fakeredis
import pytest
from fastapi.testclient import TestClient

import callbot.engine as engine_module
from callbot.engine import EngineSettings, RedisSessionStore
from callbot.transports.http.call_mode import CallModeStore
from callbot.transports.http.main import create_app
from clinic_mock_sim import FakeClinicAPI
from tests.transports.http.fakes import make_speech_bundle

# Fixture `clinic`, `clinic_scenario` và chặn gọi clinic mock thật — xem src/clinic_mock_sim/README.md
pytest_plugins = ["clinic_mock_sim.pytest_plugin"]


@pytest.fixture(autouse=True)
def offline_name_fallback(monkeypatch: pytest.MonkeyPatch, redis_store_factory) -> None:
    """A developer's .env must never turn unit tests into paid name slot-filling or semantic requests."""
    monkeypatch.setenv("NAME_FALLBACK_PROVIDER", "none")
    monkeypatch.setenv("NAME_FALLBACK_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("NAME_FALLBACK_TIMEOUT_S", "3.0")
    monkeypatch.setenv("NAME_FALLBACK_MAX_TOKENS", "")
    # T-05 §8: tests that need the layer inject a fake extractor; nothing here calls OpenAI.
    monkeypatch.setenv("SEMANTIC_FALLBACK_ENABLED", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setattr(engine_module, "_default_session_store", redis_store_factory)


@pytest.fixture
def redis_server():
    return fakeredis.FakeServer()


@pytest.fixture
def redis_store_factory(redis_server):
    prefix = f"test:{uuid4().hex}"

    def factory(**kwargs) -> RedisSessionStore:
        client = fakeredis.FakeRedis(server=redis_server, decode_responses=True)
        return RedisSessionStore(client, key_prefix=prefix, **kwargs)

    return factory


@pytest.fixture
def client(
    clinic: FakeClinicAPI, redis_store_factory, redis_server, tmp_path
) -> Iterator[TestClient]:
    """App HTTP với Orchestrator thật trên clinic giả; `with` để chạy lifespan, mỗi test một session store.

    speech_factory/call_mode_factory dùng fake + fakeredis — không được để một `.env`
    dev thật (Gemini/OpenAI key) biến test thường thành gọi API thật lúc warm-up (§ cùng
    lý do offline_name_fallback ở trên tồn tại).
    """
    call_mode_client = fakeredis.FakeRedis(server=redis_server, decode_responses=True)
    app = create_app(
        clinic_factory=lambda: clinic,
        engine_settings=EngineSettings(),
        session_store_factory=redis_store_factory,
        speech_factory=lambda: make_speech_bundle(tmp_path),
        call_mode_factory=lambda: CallModeStore(call_mode_client, key_prefix=f"test:{uuid4().hex}"),
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def store(redis_store_factory) -> RedisSessionStore:
    return redis_store_factory()
