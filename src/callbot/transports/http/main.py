import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from redis import Redis

from callbot.engine import (
    ClinicAPI,
    EngineSettings,
    RedisSessionStore,
    SessionStore,
    SessionStoreUnavailable,
    create_orchestrator,
)
from callbot.engine.session.retention import RetentionPolicy
from callbot.engine.session.settings import SessionSettings
from callbot.engine.tools.clinic_mock_client import ClinicMockClient
from callbot.speech.settings import SpeechSettings
from callbot.transports.http.calls import router as calls_router
from callbot.transports.http.config import settings
from callbot.transports.http.speech import CallModeStore, SpeechBundle, build_speech_bundle, warm_up

logger = logging.getLogger(__name__)


def _default_clinic() -> ClinicAPI:
    return ClinicMockClient(settings.clinic_mock_base_url, settings.clinic_mock_api_key)


def _default_session_store() -> SessionStore:
    config = SessionSettings()
    store = RedisSessionStore.from_url(
        config.redis_url,
        retention=RetentionPolicy(config.session_idle_ttl_s, config.session_max_age_s),
        key_prefix=config.redis_key_prefix,
        tombstone_ttl_s=config.session_tombstone_ttl_s,
        max_session_bytes=config.session_max_bytes,
        lock_lease_s=config.session_lock_lease_s,
    )
    store.validate_server_config()
    return store


def _default_speech() -> SpeechBundle:
    return build_speech_bundle(SpeechSettings())


def _default_call_mode() -> CallModeStore:
    config = SessionSettings()
    client = Redis.from_url(
        config.redis_url, decode_responses=True, socket_connect_timeout=3, socket_timeout=3
    )
    return CallModeStore(client, key_prefix=config.redis_key_prefix, ttl_s=config.session_max_age_s)


def create_app(
    clinic_factory: Callable[[], ClinicAPI] = _default_clinic,
    engine_settings: Optional[EngineSettings] = None,
    session_store_factory: Callable[[], SessionStore] = _default_session_store,
    speech_factory: Callable[[], SpeechBundle] = _default_speech,
    call_mode_factory: Callable[[], CallModeStore] = _default_call_mode,
    cleanup_interval_s: float = 30.0,
) -> FastAPI:
    if cleanup_interval_s <= 0:
        raise ValueError("cleanup_interval_s must be positive")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        store = session_store_factory()
        clinic = None
        cleaner = None
        call_mode = None
        stop = asyncio.Event()
        app.state.cleanup_healthy = True

        async def cleanup() -> None:
            while not stop.is_set():
                try:
                    await asyncio.to_thread(store.purge_expired)
                    app.state.cleanup_healthy = True
                except Exception:
                    # Không ghi exception chứa transcript hoặc nội dung API vào log.
                    logger.error("Không dọn được session hết hạn")
                    app.state.cleanup_healthy = False
                try:
                    await asyncio.wait_for(stop.wait(), timeout=cleanup_interval_s)
                except TimeoutError:
                    pass

        try:
            clinic = clinic_factory()
            app.state.session_store = store
            app.state.orchestrator = create_orchestrator(
                clinic, engine_settings or EngineSettings(), store=store
            )
            speech = speech_factory()
            await asyncio.to_thread(warm_up, speech)
            app.state.speech = speech
            audio_dir = Path(speech.audio_store.directory)
            audio_dir.mkdir(parents=True, exist_ok=True)
            # Thư mục thật chỉ biết được sau khi speech_factory() chạy ở đây — mount
            # StaticFiles ngay trong lifespan, trước yield (chưa có traffic thật nào).
            app.mount("/audio", StaticFiles(directory=str(audio_dir)), name="audio")
            call_mode = call_mode_factory()
            app.state.call_mode = call_mode
            cleaner = asyncio.create_task(cleanup())
            yield
        finally:
            stop.set()
            if cleaner is not None:
                await cleaner
            if call_mode is not None:
                call_mode.close()
            try:
                close = getattr(clinic, "close", None)
                if close is not None:
                    close()
            finally:
                store.close()

    app = FastAPI(title="Vinmec Callbot", lifespan=lifespan)
    app.include_router(calls_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        # Liveness: chỉ báo process còn sống.
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> JSONResponse:
        try:
            app.state.session_store.check_ready()
            if not app.state.cleanup_healthy:
                raise SessionStoreUnavailable("Session cleanup unavailable")
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
