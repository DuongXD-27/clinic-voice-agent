from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI

from callbot.engine import ClinicAPI, EngineSettings, create_orchestrator
from callbot.engine.tools.clinic_mock_client import ClinicMockClient
from callbot.transports.http.calls import router as calls_router
from callbot.transports.http.config import settings


def _default_clinic() -> ClinicAPI:
    return ClinicMockClient(settings.clinic_mock_base_url, settings.clinic_mock_api_key)


def create_app(
    clinic_factory: Callable[[], ClinicAPI] = _default_clinic,
    engine_settings: Optional[EngineSettings] = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Một client + một orchestrator cho cả process: session nằm trong bộ nhớ của orchestrator
        clinic = clinic_factory()
        app.state.orchestrator = create_orchestrator(clinic, engine_settings or EngineSettings())
        try:
            yield
        finally:
            close = getattr(clinic, "close", None)
            if close is not None:
                close()

    app = FastAPI(title="Vinmec Callbot", lifespan=lifespan)
    app.include_router(calls_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        # Không gọi clinic mock: /health chỉ báo process còn sống
        return {"status": "ok"}

    return app


app = create_app()
