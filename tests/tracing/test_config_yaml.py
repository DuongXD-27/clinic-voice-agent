"""Trace defaults live in YAML; env keeps deployment values and secrets."""

from callbot.tracing.config import TracingSettings
from callbot.tracing.langfuse_sink import LangfuseOtlpSettings
from callbot.transports.http.config import ObservabilityApiSettings


def test_trace_and_dashboard_defaults_load_from_yaml(monkeypatch) -> None:
    for name in (
        "TRACE_ENABLED",
        "TRACE_JSONL_DIR",
        "TRACE_KEY_VERSION",
        "TRACE_ENVIRONMENT",
        "LANGFUSE_EXPORT_ENABLED",
        "LANGFUSE_TIMEOUT_SECONDS",
        "OBSERVABILITY_API_ENABLED",
        "OBSERVABILITY_TRACE_DIR",
    ):
        monkeypatch.setenv(name, "")

    trace = TracingSettings(_env_file=None)
    langfuse = LangfuseOtlpSettings(_env_file=None)
    dashboard = ObservabilityApiSettings(_env_file=None)

    assert (trace.enabled, trace.jsonl_dir, trace.key_version, trace.environment) == (
        False,
        None,
        "v1",
        "development",
    )
    assert trace.pseudonymization_key.get_secret_value() == ""
    assert (langfuse.enabled, langfuse.timeout_seconds, langfuse.queue_size) == (
        False,
        2.0,
        1024,
    )
    assert langfuse.public_key.get_secret_value() == ""
    assert langfuse.secret_key.get_secret_value() == ""
    assert (dashboard.enabled, dashboard.trace_dir) == (False, "")


def test_trace_and_dashboard_env_override_yaml(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TRACE_ENABLED", "true")
    monkeypatch.setenv("TRACE_JSONL_DIR", str(tmp_path))
    monkeypatch.setenv("TRACE_KEY_VERSION", "v2")
    monkeypatch.setenv("TRACE_ENVIRONMENT", "staging")
    monkeypatch.setenv("LANGFUSE_EXPORT_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_TIMEOUT_SECONDS", "4.5")
    monkeypatch.setenv("OBSERVABILITY_API_ENABLED", "true")
    monkeypatch.setenv("OBSERVABILITY_TRACE_DIR", str(tmp_path))

    trace = TracingSettings(_env_file=None)
    langfuse = LangfuseOtlpSettings(_env_file=None)
    dashboard = ObservabilityApiSettings(_env_file=None)

    assert (trace.enabled, trace.jsonl_dir, trace.key_version, trace.environment) == (
        True,
        tmp_path,
        "v2",
        "staging",
    )
    assert (langfuse.enabled, langfuse.timeout_seconds) == (True, 4.5)
    assert (dashboard.enabled, dashboard.trace_dir) == (True, str(tmp_path))
