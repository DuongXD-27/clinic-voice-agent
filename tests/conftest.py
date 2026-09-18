from collections.abc import Iterator
from uuid import uuid4

import fakeredis
import pytest
from fastapi.testclient import TestClient

import callbot.engine as engine_module
from callbot.engine import EngineSettings, RedisSessionStore
from callbot.transports.http.main import create_app
from tests.engine.fake_clinic import FakeClinicAPI


@pytest.fixture(autouse=True)
def offline_name_fallback(monkeypatch: pytest.MonkeyPatch, redis_store_factory) -> None:
    """A developer's .env must never turn unit tests into paid NER requests."""
    monkeypatch.setenv("NAME_FALLBACK_PROVIDER", "none")
    monkeypatch.setenv("NAME_FALLBACK_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("NAME_FALLBACK_TIMEOUT_S", "3.0")
    monkeypatch.setenv("NAME_FALLBACK_MAX_TOKENS", "")
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
def clinic() -> FakeClinicAPI:
    return FakeClinicAPI()


@pytest.fixture
def client(clinic: FakeClinicAPI, redis_store_factory) -> Iterator[TestClient]:
    """App HTTP với Orchestrator thật trên clinic giả; `with` để chạy lifespan, mỗi test một session store."""
    app = create_app(
        clinic_factory=lambda: clinic,
        engine_settings=EngineSettings(llm_provider="none"),
        session_store_factory=redis_store_factory,
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def store(redis_store_factory) -> RedisSessionStore:
    return redis_store_factory()
