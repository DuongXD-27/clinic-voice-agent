"""Cấu hình tầng ngữ nghĩa phải độc lập với NER tên — đổi cái này không được đổi cái kia.

`ProviderConfig` đọc `NAME_FALLBACK_*` qua `validation_alias`; factory semantic truyền giá trị
tường minh. Test này khóa thứ tự ưu tiên đó để không phải suy đoán hành vi của pydantic-settings.
"""

import pytest

from callbot.engine import _semantic_extractor, create_orchestrator
from callbot.engine.extraction.semantic import LLMSemanticExtractor
from callbot.engine.settings import EngineSettings
from inference.llm.config import OpenAIConfig
from tests.engine.fake_clinic import FakeClinicAPI


@pytest.fixture(autouse=True)
def _openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")


def test_explicit_values_win_over_the_name_fallback_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NAME_FALLBACK_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("NAME_FALLBACK_TIMEOUT_S", "9.5")
    monkeypatch.setenv("NAME_FALLBACK_MAX_TOKENS", "111")

    config = OpenAIConfig(model="gpt-4o-mini", timeout_s=2.0, max_completion_tokens=400)
    assert (config.model, config.timeout_s, config.max_completion_tokens) == (
        "gpt-4o-mini",
        2.0,
        400,
    )


def test_semantic_factory_uses_its_own_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NAME_FALLBACK_MODEL", "gemini-2.5-flash")
    settings = EngineSettings(
        semantic_fallback_enabled=True,
        semantic_fallback_model="gpt-4o-mini",
        semantic_fallback_timeout_s=2.0,
        semantic_fallback_max_tokens=400,
    )
    extractor = _semantic_extractor(settings)
    assert isinstance(extractor, LLMSemanticExtractor)
    assert extractor._gateway.model == "gpt-4o-mini"
    assert extractor._gateway.provider_name == "openai"


def test_semantic_is_on_by_default_in_code() -> None:
    """Quyết định owner 22-09-2026: bật mặc định. Đọc default của field, không qua env của test."""
    assert EngineSettings.model_fields["semantic_fallback_enabled"].default is True


def test_the_test_suite_itself_keeps_semantic_off(redis_store_factory) -> None:
    """`tests/conftest.py` đặt SEMANTIC_FALLBACK_ENABLED=false: không test nào gọi OpenAI thật."""
    assert EngineSettings().semantic_fallback_enabled is False
    bot = create_orchestrator(FakeClinicAPI(), store=redis_store_factory())
    assert bot._extractor._semantic is None


def test_enabled_without_an_api_key_falls_back_to_rules_instead_of_failing(
    monkeypatch: pytest.MonkeyPatch, redis_store_factory
) -> None:
    """Bật mặc định trên máy không có khóa: server vẫn khởi động, chạy chỉ-luật."""
    monkeypatch.setenv("OPENAI_API_KEY", "")
    settings = EngineSettings(semantic_fallback_enabled=True)
    assert _semantic_extractor(settings) is None
    bot = create_orchestrator(FakeClinicAPI(), settings=settings, store=redis_store_factory())
    assert bot._extractor._semantic is None


def test_changing_the_ner_provider_does_not_build_a_semantic_layer(
    monkeypatch: pytest.MonkeyPatch, redis_store_factory
) -> None:
    monkeypatch.setenv("NAME_FALLBACK_PROVIDER", "openai")
    bot = create_orchestrator(
        FakeClinicAPI(),
        settings=EngineSettings(name_fallback_provider="openai", semantic_fallback_enabled=False),
        store=redis_store_factory(),
    )
    assert bot._extractor._fallback is not None  # NER bật
    assert bot._extractor._semantic is None  # semantic vẫn tắt


def test_the_semantic_timeout_is_three_seconds_everywhere() -> None:
    """Mặc định trong code và `.env.example` là cùng một giá trị."""
    from pathlib import Path

    assert EngineSettings.model_fields["semantic_fallback_timeout_s"].default == 3.0
    example = Path(__file__).resolve().parents[2] / ".env.example"
    assert "SEMANTIC_FALLBACK_TIMEOUT_S=3.0" in example.read_text(encoding="utf-8").splitlines()
