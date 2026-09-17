import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from callbot.engine import EngineSettings, InMemorySessionStore
from callbot.transports.http.main import create_app
from tests.engine.fake_clinic import FakeClinicAPI

# PostgreSQL thật cho test tích hợp. CI đặt REQUIRE_POSTGRES_TESTS=1 để thiếu DB là lỗi, không skip.
POSTGRES_URL_ENV = "TEST_SESSION_DATABASE_URL"


@pytest.fixture
def clinic() -> FakeClinicAPI:
    return FakeClinicAPI()


@pytest.fixture
def client(clinic: FakeClinicAPI) -> Iterator[TestClient]:
    """App HTTP với Orchestrator thật trên clinic giả; `with` để chạy lifespan, mỗi test một session store."""
    app = create_app(
        clinic_factory=lambda: clinic,
        engine_settings=EngineSettings(llm_provider="none"),
        session_store_factory=InMemorySessionStore,
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def postgres_url() -> str:
    url = os.environ.get(POSTGRES_URL_ENV, "")
    if not url:
        if os.environ.get("REQUIRE_POSTGRES_TESTS") == "1":
            pytest.fail(f"Thiếu {POSTGRES_URL_ENV} trong khi REQUIRE_POSTGRES_TESTS=1")
        pytest.skip(f"Đặt {POSTGRES_URL_ENV} để chạy test PostgreSQL")
    from callbot.engine.session.postgres.migrate import migrate

    migrate(url)
    return url


@pytest.fixture
def postgres_store(postgres_url: str) -> Iterator["object"]:
    import psycopg

    from callbot.engine.session.postgres import PostgresSessionStore

    with psycopg.connect(postgres_url, autocommit=True) as conn:
        conn.execute("TRUNCATE clinic_commands, call_turns, call_sessions")
    store = PostgresSessionStore(postgres_url, min_size=1, max_size=8, timeout_s=5.0)
    store.open()
    try:
        yield store
    finally:
        store.close()


@pytest.fixture(params=["memory", "postgres"])
def store(request: pytest.FixtureRequest) -> "object":
    """Cùng một hợp đồng cho hai repository."""
    if request.param == "memory":
        return InMemorySessionStore()
    return request.getfixturevalue("postgres_store")
