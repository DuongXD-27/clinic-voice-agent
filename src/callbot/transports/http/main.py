from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from callbot.engine import (
    ClinicAPI,
    EngineSettings,
    SessionStore,
    SessionStoreUnavailable,
    create_orchestrator,
)
from callbot.engine.tools.clinic_mock_client import ClinicMockClient
from callbot.transports.http.calls import router as calls_router
from callbot.transports.http.config import settings


def _default_clinic() -> ClinicAPI:
    return ClinicMockClient(settings.clinic_mock_base_url, settings.clinic_mock_api_key)


def _default_session_store() -> SessionStore:
    """PostgreSQL bắt buộc: nhiều worker dùng chung phiên. Không tự chuyển sang bộ nhớ khi DB lỗi."""
    from callbot.engine.session.postgres import PostgresSessionStore, SessionStoreSettings

    store_settings = SessionStoreSettings()
    if not store_settings.session_database_url:
        raise RuntimeError("Thiếu SESSION_DATABASE_URL — ứng dụng HTTP cần PostgreSQL")
    store = PostgresSessionStore(
        store_settings.session_database_url,
        min_size=store_settings.session_pool_min_size,
        max_size=store_settings.session_pool_max_size,
        timeout_s=store_settings.session_pool_timeout_s,
    )
    store.open()
    return store


def create_app(
    clinic_factory: Callable[[], ClinicAPI] = _default_clinic,
    engine_settings: Optional[EngineSettings] = None,
    session_store_factory: Callable[[], SessionStore] = _default_session_store,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Một client + một orchestrator cho mỗi worker; phiên nằm trong session store dùng chung
        store = session_store_factory()
        clinic = clinic_factory()
        app.state.session_store = store
        app.state.orchestrator = create_orchestrator(
            clinic, engine_settings or EngineSettings(), store=store
        )
        try:
            yield
        finally:
            close = getattr(clinic, "close", None)
            if close is not None:
                close()
            store.close()

    app = FastAPI(title="Vinmec Callbot", lifespan=lifespan)
    app.include_router(calls_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        # Liveness: không gọi clinic mock hay DB, chỉ báo process còn sống
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> JSONResponse:
        # Readiness: DB kết nối được và schema đã migrate đúng phiên bản
        try:
            app.state.session_store.check_ready()
        except SessionStoreUnavailable:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "unavailable",
                    "code": "SESSION_STORE_UNAVAILABLE",
                },
            )
        return JSONResponse({"status": "ready"})

    return app


app = create_app()
