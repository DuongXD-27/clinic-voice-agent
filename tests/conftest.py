from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from callbot.engine import EngineSettings
from callbot.transports.http.main import create_app
from tests.engine.fake_clinic import FakeClinicAPI


@pytest.fixture
def clinic() -> FakeClinicAPI:
    return FakeClinicAPI()


@pytest.fixture
def client(clinic: FakeClinicAPI) -> Iterator[TestClient]:
    """App HTTP với Orchestrator thật trên clinic giả; `with` để chạy lifespan, mỗi test một session store."""
    app = create_app(
        clinic_factory=lambda: clinic,
        engine_settings=EngineSettings(llm_provider="none"),
    )
    with TestClient(app) as test_client:
        yield test_client
