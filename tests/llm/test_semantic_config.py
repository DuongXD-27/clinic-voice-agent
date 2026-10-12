"""Cấu hình tầng ngữ nghĩa phải độc lập với slot filling tên — đổi cái này không được đổi cái kia.

`ProviderConfig` đọc `NAME_FALLBACK_*` qua `validation_alias`; factory semantic truyền giá trị
tường minh. Test này khóa thứ tự ưu tiên đó để không phải suy đoán hành vi của pydantic-settings.
"""

import pytest
import yaml

from appconfig import CONFIG_DIR
from callbot.engine import _semantic_extractor, create_orchestrator
from callbot.engine.extraction.semantic import LLMSemanticExtractor
from callbot.engine.settings import EngineSettings
from clinic_mock_sim import FakeClinicAPI
from inference.llm.config import OpenAIConfig


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
        semantic_openai_model="gpt-4o-mini",
        semantic_fallback_timeout_s=2.0,
        semantic_openai_max_tokens=400,
    )
    extractor = _semantic_extractor(settings)
    assert isinstance(extractor, LLMSemanticExtractor)
    assert extractor._gateway.model == "gpt-4o-mini"
    assert extractor._gateway.provider_name == "openai"


def _engine_yaml() -> dict:
    """Đọc thẳng config/engine.yaml — nguồn mặc định duy nhất, không qua env của test."""
    return yaml.safe_load((CONFIG_DIR / "engine.yaml").read_text(encoding="utf-8"))


def test_semantic_is_on_by_default() -> None:
    """Quyết định owner 22-09-2026: bật mặc định."""
    assert _engine_yaml()["semantic_fallback_enabled"] is True


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


def test_changing_the_name_slot_filling_provider_does_not_build_a_semantic_layer(
    monkeypatch: pytest.MonkeyPatch, redis_store_factory
) -> None:
    monkeypatch.setenv("NAME_FALLBACK_PROVIDER", "openai")
    bot = create_orchestrator(
        FakeClinicAPI(),
        settings=EngineSettings(name_fallback_provider="openai", semantic_fallback_enabled=False),
        store=redis_store_factory(),
    )
    assert bot._extractor._fallback is not None  # slot filling họ tên bật
    assert bot._extractor._semantic is None  # semantic vẫn tắt


def test_the_semantic_timeout_is_three_seconds_by_default() -> None:
    assert _engine_yaml()["semantic_fallback_timeout_s"] == 3.0


def test_the_turn_budget_is_four_seconds_and_jev_gets_two(monkeypatch: pytest.MonkeyPatch) -> None:
    """Owner 12/10/2026 (QC qc-cn-08): trần lượt 4 s, Jev 2 s để Jev treo vẫn còn thời gian dự phòng."""
    from callbot.engine import _jev_semantic
    from callbot.engine.extraction.model_budget import MODEL_TIMEOUT_S
    from inference.common.transport import MODEL_CALL_HARD_LIMIT_S

    assert MODEL_TIMEOUT_S == 4.0 and MODEL_CALL_HARD_LIMIT_S == 4.0
    defaults = _engine_yaml()
    assert defaults["semantic_jev_timeout_s"] == 2.0
    assert (
        defaults["semantic_backup_min_remaining_s"]
        <= MODEL_TIMEOUT_S - defaults["semantic_jev_timeout_s"]
    )

    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test-not-a-real-key")
    jev = _jev_semantic(EngineSettings(semantic_jev_timeout_s=2.0, semantic_fallback_timeout_s=3.0))
    assert jev is not None and jev._gateway._config.timeout_s == 2.0
