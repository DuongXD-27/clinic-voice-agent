import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from time import monotonic
from typing import Optional

from fastapi import Depends, FastAPI
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
from callbot.observability import JsonlSpanSource, MetricsQueryService
from callbot.tracing import Tracer, create_tracer
from callbot.transports.http.auth import require_api_key
from callbot.transports.http.call_mode import CallModeStore
from callbot.transports.http.calls import router as calls_router
from callbot.transports.http.clinic_backend import build_clinic
from callbot.transports.http.config import ObservabilityApiSettings, settings
from callbot.transports.http.demo import router as demo_router
from callbot.transports.http.livekit_token import router as livekit_router
from callbot.transports.http.observability import router as observability_router
from callbot.transports.http.stt_eval import router as stt_eval_router
from callbot.transports.http.ui import add_legacy_redirects, mount_ui
from callbot.transports.livekit.settings import LiveKitSettings
from speech.asr.offline import VadFactory
from speech.asr.vad import FrameClassifier
from speech.bundle import SpeechBundle, build_speech_bundle, warm_up
from speech.settings import SpeechSettings

logger = logging.getLogger(__name__)
_TRACE_SHUTDOWN_TIMEOUT_SECONDS = 5.0


def _default_clinic() -> ClinicAPI:
    return build_clinic(settings)


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


def _default_livekit_settings() -> LiveKitSettings:
    return LiveKitSettings()


def _default_stt_vad_factory() -> VadFactory:
    model_path = SpeechSettings().silero_vad_model_path

    def build(sample_rate: int) -> FrameClassifier:
        # Silero stateful: mỗi request một instance
        from speech.asr.vad.silero import SileroVadClassifier

        return SileroVadClassifier(model_path, sample_rate=sample_rate)

    return build


def _configure_observability(app: FastAPI, supplied: ObservabilityApiSettings | None) -> None:
    """Register the opt-in internal router without risking core app startup."""
    try:
        config = supplied or ObservabilityApiSettings()
        if not config.enabled:
            return
        configured = config.trace_dir.strip() or config.fallback_trace_dir.strip()
        if not configured:
            logger.warning("OBSERVABILITY_CONFIG_INVALID")
            return
        trace_dir = Path(configured)
        app.state.observability_trace_dir = trace_dir
        app.state.observability_service = MetricsQueryService(JsonlSpanSource(trace_dir))
        app.include_router(observability_router)
    except Exception:
        logger.warning("OBSERVABILITY_CONFIG_INVALID")


def create_app(
    clinic_factory: Callable[[], ClinicAPI] = _default_clinic,
    engine_settings: Optional[EngineSettings] = None,
    session_store_factory: Callable[[], SessionStore] = _default_session_store,
    speech_factory: Callable[[], SpeechBundle] = _default_speech,
    call_mode_factory: Callable[[], CallModeStore] = _default_call_mode,
    livekit_settings_factory: Callable[[], LiveKitSettings] = _default_livekit_settings,
    tracer_factory: Callable[[], Tracer] = create_tracer,
    observability_settings: ObservabilityApiSettings | None = None,
    stt_eval_enabled: Optional[bool] = None,
    stt_vad_factory: Optional[VadFactory] = None,
    ui_dist_dir: Optional[str] = None,
    cleanup_interval_s: float = 30.0,
    audio_retention_s: Optional[float] = None,
    trace_shutdown_timeout_s: float = _TRACE_SHUTDOWN_TIMEOUT_SECONDS,
) -> FastAPI:
    if cleanup_interval_s <= 0:
        raise ValueError("cleanup_interval_s must be positive")
    if audio_retention_s is not None and audio_retention_s <= 0:
        raise ValueError("audio_retention_s must be positive")
    if trace_shutdown_timeout_s <= 0:
        raise ValueError("trace_shutdown_timeout_s must be positive")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        tracer = tracer_factory()
        app.state.tracer = tracer
        store = None
        clinic = None
        cleaner = None
        call_mode = None
        speech = None
        stop = asyncio.Event()
        app.state.cleanup_healthy = True
        # Wav giữ đủ lâu để harness tải `audio_url` trong suốt cuộc gọi dài nhất có thể.
        retention_s = audio_retention_s or SessionSettings().session_max_age_s

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
                    await asyncio.to_thread(
                        app.state.speech.audio_store.purge_older_than, retention_s
                    )
                except Exception:
                    # Lỗi dọn file không ảnh hưởng xử lý cuộc gọi — không đánh dấu /ready fail.
                    logger.exception("Không dọn được audio cũ")
                try:
                    await asyncio.wait_for(stop.wait(), timeout=cleanup_interval_s)
                except TimeoutError:
                    pass

        try:
            store = session_store_factory()
            clinic = clinic_factory()
            # Trang demo đọc dữ liệu sim để dựng dropdown (demo.list_clinic_fixtures)
            app.state.clinic = clinic
            app.state.session_store = store
            app.state.orchestrator = create_orchestrator(
                clinic, engine_settings or EngineSettings(), tracer=tracer, store=store
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
            try:
                if speech is not None:
                    for resource in (speech, speech.asr, speech.tts, speech.audio_store):
                        close = getattr(resource, "close", None)
                        if close is not None:
                            try:
                                await asyncio.to_thread(close)
                            except Exception:
                                logger.warning("SPEECH_RESOURCE_CLOSE_FAILED")
                if call_mode is not None:
                    try:
                        await asyncio.to_thread(call_mode.close)
                    except Exception:
                        logger.warning("CALL_MODE_CLOSE_FAILED")
                close = getattr(clinic, "close", None)
                if close is not None:
                    try:
                        await asyncio.to_thread(close)
                    except Exception:
                        logger.warning("CLINIC_CLOSE_FAILED")
                if store is not None:
                    try:
                        await asyncio.to_thread(store.close)
                    except Exception:
                        logger.warning("SESSION_STORE_CLOSE_FAILED")
            finally:
                deadline = monotonic() + trace_shutdown_timeout_s
                try:
                    remaining = max(0.0, deadline - monotonic())
                    flushed = await asyncio.wait_for(
                        asyncio.to_thread(tracer.flush, remaining), timeout=remaining
                    )
                    if not flushed:
                        logger.warning("TRACE_FLUSH_INCOMPLETE")
                except Exception:
                    logger.warning("TRACE_FLUSH_FAILED")
                try:
                    remaining = max(0.0, deadline - monotonic())
                    closed = await asyncio.wait_for(
                        asyncio.to_thread(tracer.close, remaining), timeout=remaining
                    )
                    if not closed:
                        logger.warning("TRACE_CLOSE_INCOMPLETE")
                except Exception:
                    logger.warning("TRACE_CLOSE_FAILED")

    app = FastAPI(title="Vinmec Callbot", lifespan=lifespan)
    app.state.livekit_settings = livekit_settings_factory()
    app.include_router(calls_router, dependencies=[Depends(require_api_key)])
    app.include_router(demo_router, dependencies=[Depends(require_api_key)])
    app.include_router(livekit_router)
    if settings.stt_eval_enabled if stt_eval_enabled is None else stt_eval_enabled:
        app.state.stt_vad_factory = stt_vad_factory or _default_stt_vad_factory()
        app.include_router(stt_eval_router, dependencies=[Depends(require_api_key)])
    _configure_observability(app, observability_settings)
    add_legacy_redirects(app)
    mount_ui(app, settings.ui_dist_dir if ui_dist_dir is None else ui_dist_dir)

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
