"""Environment configuration and composition root for tracing."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
from pydantic import Field, SecretStr

from appconfig import YamlSettings, yaml_config
from callbot.tracing.context import Tracer, null_tracer
from callbot.tracing.jsonl_sink import JsonlTraceSink
from callbot.tracing.langfuse_sink import LangfuseOtlpSettings, create_langfuse_sink
from callbot.tracing.pseudonym import CallKeyFactory
from callbot.tracing.sink import CompositeTraceSink, NullTraceSink, TraceSink

logger = logging.getLogger(__name__)


class TracingSettings(YamlSettings):
    model_config = yaml_config("tracing.yaml", "trace", populate_by_name=True)

    enabled: bool = Field(validation_alias="TRACE_ENABLED")
    jsonl_dir: Path | None = Field(validation_alias="TRACE_JSONL_DIR")
    # HMAC key only comes from env / .env.
    pseudonymization_key: SecretStr = Field(
        default=SecretStr(""), validation_alias="TRACE_PSEUDONYMIZATION_KEY"
    )
    key_version: str = Field(validation_alias="TRACE_KEY_VERSION")
    environment: str = Field(validation_alias="TRACE_ENVIRONMENT")


def create_tracer(
    settings: TracingSettings | None = None,
    langfuse_settings: LangfuseOtlpSettings | None = None,
    *,
    langfuse_client: httpx.Client | None = None,
) -> Tracer:
    try:
        config = settings or TracingSettings()
        if not config.enabled:
            return null_tracer()
        call_keys = CallKeyFactory(
            config.pseudonymization_key.get_secret_value(),
            version=config.key_version,
            environment=config.environment,
        )
        sinks: list[TraceSink] = []
        if config.jsonl_dir is not None:
            sinks.append(JsonlTraceSink(config.jsonl_dir))

        remote = create_langfuse_sink(langfuse_settings, client=langfuse_client)
        if not isinstance(remote, NullTraceSink):
            sinks.append(remote)

        if not sinks:
            logger.warning("TRACE_CONFIG_INVALID")
            return null_tracer()
        sink = sinks[0] if len(sinks) == 1 else CompositeTraceSink(*sinks)
        return Tracer(sink, call_keys)
    except Exception:
        logger.warning("TRACE_CONFIG_INVALID")
        return null_tracer()
