from collections.abc import Iterator
from uuid import uuid4

import fakeredis
import pytest
from fastapi.testclient import TestClient

import callbot.engine as engine_module
from callbot.engine import EngineSettings, RedisSessionStore
from callbot.engine.dialogue import templates
from callbot.transports.http import calls as http_calls
from callbot.transports.http.call_mode import CallModeStore
from callbot.transports.http.config import settings as http_settings
from callbot.transports.http.main import create_app
from clinic_mock_sim import FakeClinicAPI
from tests.transports.http.fakes import load_silent_audio, make_speech_bundle

# Fixture `clinic`, `clinic_scenario` và chặn gọi clinic mock thật — xem src/clinic_mock_sim/README.md
pytest_plugins = ["clinic_mock_sim.pytest_plugin"]


@pytest.fixture(autouse=True)
def fixed_dialogue_variant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Business tests ưu tiên v0; test_dialogue_variants kiểm tập ba/bốn và selector thật.

    Cố định selector, không bỏ qua render/guard hay thay đổi phản hồi sau khi engine tạo ra.
    """
    monkeypatch.setattr(templates, "choose_variant", lambda ctx, group, **kwargs: "v0")


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
    monkeypatch.setenv("TYPESAFE_API_KEY", "")
    # .env dev bật trace + Langfuse thì mỗi app test gửi trace thật và chờ flush khi tắt (~0.8s/test).
    # Test cần trace tự bật TRACE_ENABLED với JSONL dir riêng; Langfuse luôn tắt.
    monkeypatch.setenv("TRACE_ENABLED", "false")
    monkeypatch.setenv("LANGFUSE_EXPORT_ENABLED", "false")
    monkeypatch.setattr(engine_module, "_default_session_store", redis_store_factory)
    # BOT_API_KEYS trong .env bật auth cho mọi request test; test_auth.py tự bật lại khi cần.
    monkeypatch.setattr(http_settings, "bot_api_keys", "")


@pytest.fixture(autouse=True)
def offline_audio_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    """mode=audio không tải audio_url thật; test cần audio khác tự patch đè."""
    monkeypatch.setattr(http_calls, "load_from_url", load_silent_audio)


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
