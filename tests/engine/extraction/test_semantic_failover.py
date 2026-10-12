"""Provider chính, lỗi dịch vụ thì provider dự phòng (cấu hình ở engine.yaml) — không gọi mạng."""

import threading
from types import SimpleNamespace
from typing import Any, Optional

import pytest
import yaml

from appconfig import CONFIG_DIR
from callbot.engine import _semantic_extractor
from callbot.engine.extraction.model_budget import (
    hand_over_model,
    invoke_model,
    model_turn,
    report_model_status,
)
from callbot.engine.extraction.schema import Intent, QuestionId
from callbot.engine.extraction.semantic import (
    LLMSemanticExtractor,
    ReplyKind,
    SemanticContext,
    SemanticOutcome,
)
from callbot.engine.extraction.semantic_failover import FailoverSemanticExtractor
from callbot.engine.extraction.semantic_jev import JevSemanticExtractor
from callbot.engine.settings import EngineSettings

CONTEXT = SemanticContext(
    transcript="thôi hủy giúp tôi",
    question_id=QuestionId.CANCEL_RECONFIRM,
    direction="outbound",
    allowed_intents=(Intent.CONFIRM, Intent.CANCEL, Intent.RESCHEDULE, Intent.OUT_OF_SCOPE),
    route_reason="CANCEL_LEFTOVER",
    pending_action="CANCEL",
)
PRIMARY_OUTCOME = SemanticOutcome(ReplyKind.AMBIGUOUS)
SECONDARY_OUTCOME = SemanticOutcome(ReplyKind.CONFIRM_ACTION, reply_span="hủy giúp tôi")


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _Gateway:
    def __init__(self, name: str) -> None:
        self.model = f"{name}-model"
        self.provider_name = name


class FakeAdapter:
    """Giả adapter: đặt `last_status`, báo trạng thái cho ngân sách lượt như adapter thật."""

    def __init__(
        self,
        name: str,
        status: str,
        outcome: Optional[SemanticOutcome] = None,
        *,
        cost_s: float = 0.0,
        clock: Optional[Clock] = None,
    ) -> None:
        self.status, self.outcome, self.cost_s, self.clock = status, outcome, cost_s, clock
        self.calls = 0
        self.last_status: Optional[str] = None
        self.last_probabilities = {"reply_kind": {"AMBIGUOUS": 0.9}}
        self.prompt_version = f"{name}_prompt"
        self._gateway = _Gateway(name)

    def analyze(self, context: SemanticContext) -> Optional[SemanticOutcome]:
        self.calls += 1
        if self.clock is not None:
            self.clock.now += self.cost_s
        self.last_status = self.status
        report_model_status(self.status)
        if self.status == "raise":
            raise RuntimeError("boom")
        return self.outcome


def _pair(status: str, outcome=None, *, cost_s: float = 0.0, min_s: float = 1.5):
    clock = Clock()
    primary = FakeAdapter("typesafe", status, outcome, cost_s=cost_s, clock=clock)
    secondary = FakeAdapter("openai", "accepted", SECONDARY_OUTCOME)
    extractor = FailoverSemanticExtractor(primary, secondary, min_secondary_s=min_s, clock=clock)
    return extractor, primary, secondary


@pytest.mark.parametrize(
    ("status", "outcome"),
    [("accepted", PRIMARY_OUTCOME), ("rejected", None), ("empty", None), ("refusal", None)],
)
def test_an_answer_from_the_primary_is_the_answer_of_the_turn(status: str, outcome) -> None:
    """Provider chính đã trả lời (kể cả span bị loại): không hỏi thêm provider khác cho tới khi vừa ý."""
    extractor, _, secondary = _pair(status, outcome)
    assert extractor.analyze(CONTEXT) is outcome
    assert secondary.calls == 0 and extractor.last_provider == "primary"


@pytest.mark.parametrize(
    "status",
    ["timeout", "network_error", "http_error", "invalid_response", "incomplete", "error", "raise"],
)
def test_a_primary_service_failure_falls_back(status: str) -> None:
    extractor, _, secondary = _pair(status, cost_s=1.0)
    assert extractor.analyze(CONTEXT) is SECONDARY_OUTCOME
    assert secondary.calls == 1 and extractor.last_provider == "secondary"


def test_no_fallback_when_the_turn_has_too_little_time_left() -> None:
    """Lỗi ở giây 2,5 của trần 3 s: dự phòng không kịp, gọi chỉ tốn tiền."""
    extractor, _, secondary = _pair("network_error", cost_s=2.5)
    assert extractor.analyze(CONTEXT) is None
    assert secondary.calls == 0 and extractor.last_provider is None


def test_the_turn_budget_uses_the_fallback_answer() -> None:
    """Provider chính đã báo lỗi cho ngân sách lượt (TIMEOUT / ERROR không bị ghi đè): bộ chuyển phải
    trao lại lượt, nếu không kết quả dự phòng bị bỏ dù đã có."""
    extractor, _, _ = _pair("network_error")
    with model_turn() as budget:
        result = invoke_model(extractor, lambda: extractor.analyze(CONTEXT))
    assert result is SECONDARY_OUTCOME
    assert (budget.status, budget.model) == ("OK", "openai-model")
    # Trang demo báo đúng provider dự phòng đã trả lời và provider chính đã lỗi
    assert (budget.provider, budget.backup_for) == ("openai", "typesafe")


def test_the_turn_budget_names_the_primary_when_it_answers() -> None:
    extractor, _, _ = _pair("accepted", PRIMARY_OUTCOME)
    with model_turn() as budget:
        invoke_model(extractor, lambda: extractor.analyze(CONTEXT))
    assert (budget.status, budget.model) == ("OK", "typesafe-model")
    assert (budget.provider, budget.backup_for) == ("typesafe", None)


def test_the_turn_budget_keeps_the_failure_when_no_fallback_runs() -> None:
    extractor, _, _ = _pair("timeout", cost_s=2.9)
    with model_turn() as budget:
        result = invoke_model(extractor, lambda: extractor.analyze(CONTEXT))
    assert result is None and budget.status == "TIMEOUT"


def test_a_late_fallback_does_not_rewrite_a_timed_out_turn() -> None:
    """Bộ chuyển chạy trong thread của model: lượt đã hết giờ thì việc trao lại muộn không được xoá
    TIMEOUT hay ghi tên provider dự phòng chưa kịp trả lời."""
    release, handed_over = threading.Event(), threading.Event()
    config = SimpleNamespace(timeout_s=0.05)
    gateway = SimpleNamespace(
        model="typesafe-model", provider_name="typesafe", _provider=SimpleNamespace(_config=config)
    )

    def late_failover() -> None:
        release.wait(2)
        hand_over_model("openai-model", "openai")
        handed_over.set()

    with model_turn() as budget:
        assert invoke_model(SimpleNamespace(_gateway=gateway), late_failover) is None
        release.set()
        assert handed_over.wait(2)
    assert (budget.status, budget.model, budget.provider, budget.backup_for) == (
        "TIMEOUT",
        "typesafe-model",
        "typesafe",
        None,
    )


def test_eval_hooks_point_at_the_primary() -> None:
    """Script eval bọc `_gateway` và đọc xác suất: phải chạm đúng adapter chính."""
    extractor, primary, _ = _pair("accepted", PRIMARY_OUTCOME)
    wrapper = _Gateway("wrapped")
    extractor._gateway = wrapper
    assert primary._gateway is wrapper and extractor._gateway is wrapper
    assert extractor.last_probabilities == primary.last_probabilities
    assert extractor.prompt_version == "typesafe_prompt"


def test_min_secondary_must_fit_the_budget() -> None:
    with pytest.raises(ValueError):
        FailoverSemanticExtractor(
            FakeAdapter("a", "accepted"), FakeAdapter("b", "accepted"), min_secondary_s=4.0
        )


# --- Cấu hình và factory ---------------------------------------------------------------------


def test_config_defaults_to_jev_with_openai_fallback() -> None:
    """Quyết định owner 10-10-2026: Jev chính, OpenAI dự phòng — đọc thẳng config/engine.yaml."""
    config = yaml.safe_load((CONFIG_DIR / "engine.yaml").read_text(encoding="utf-8"))
    assert config["semantic_provider"] == "jev"
    assert config["semantic_backup_provider"] == "openai"
    assert 0 < config["semantic_backup_min_remaining_s"] <= 3.0


def _settings(**changes: Any) -> EngineSettings:
    base: dict[str, Any] = dict(
        semantic_fallback_enabled=True,
        semantic_provider="jev",
        semantic_backup_provider="openai",
    )
    return EngineSettings(**{**base, **changes})


@pytest.fixture
def _keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


def test_factory_builds_primary_with_fallback(_keys: None) -> None:
    extractor = _semantic_extractor(_settings())
    assert isinstance(extractor, FailoverSemanticExtractor)
    assert isinstance(extractor.primary, JevSemanticExtractor)
    assert isinstance(extractor.secondary, LLMSemanticExtractor)


def test_providers_can_be_swapped_in_config(_keys: None) -> None:
    extractor = _semantic_extractor(
        _settings(semantic_provider="openai", semantic_backup_provider="jev")
    )
    assert isinstance(extractor, FailoverSemanticExtractor)
    assert isinstance(extractor.primary, LLMSemanticExtractor)
    assert isinstance(extractor.secondary, JevSemanticExtractor)


@pytest.mark.parametrize(("primary", "secondary"), [("jev", "none"), ("jev", "jev")])
def test_no_fallback_runs_the_primary_alone(_keys: None, primary: str, secondary: str) -> None:
    extractor = _semantic_extractor(
        _settings(semantic_provider=primary, semantic_backup_provider=secondary)
    )
    assert isinstance(extractor, JevSemanticExtractor)


def test_missing_primary_key_runs_the_fallback_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert isinstance(_semantic_extractor(_settings()), LLMSemanticExtractor)


def test_missing_fallback_key_runs_the_primary_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test")
    assert isinstance(_semantic_extractor(_settings()), JevSemanticExtractor)


def test_no_key_at_all_runs_rules_only() -> None:
    assert _semantic_extractor(_settings()) is None
