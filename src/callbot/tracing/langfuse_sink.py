"""Privacy-safe, bounded OTLP/HTTP exporter for Langfuse v4 ingestion."""

from __future__ import annotations

import base64
import json
import logging
import re
import threading
from collections import deque
from datetime import datetime, timezone
from time import monotonic
from urllib.parse import urlparse

import httpx
from pydantic import Field, SecretStr

from appconfig import YamlSettings, yaml_config
from callbot.tracing.models import CompletedSpan, TraceEvent
from callbot.tracing.privacy import validate_completed_span
from callbot.tracing.sink import NullTraceSink, TraceSink

logger = logging.getLogger(__name__)

_ENVIRONMENT_PATTERN = r"^[a-z0-9_-]{1,40}$"


class LangfuseOtlpSettings(YamlSettings):
    model_config = yaml_config("tracing.yaml", "langfuse", populate_by_name=True)

    enabled: bool = Field(validation_alias="LANGFUSE_EXPORT_ENABLED")
    endpoint: str = Field(validation_alias="LANGFUSE_OTLP_ENDPOINT")
    # Project credentials only come from env / .env.
    public_key: SecretStr = Field(default=SecretStr(""), validation_alias="LANGFUSE_PUBLIC_KEY")
    secret_key: SecretStr = Field(default=SecretStr(""), validation_alias="LANGFUSE_SECRET_KEY")
    timeout_seconds: float = Field(gt=0, validation_alias="LANGFUSE_TIMEOUT_SECONDS")
    queue_size: int = Field(gt=0, validation_alias="LANGFUSE_QUEUE_SIZE")
    batch_size: int = Field(gt=0, validation_alias="LANGFUSE_BATCH_SIZE")
    flush_interval_seconds: float = Field(gt=0, validation_alias="LANGFUSE_FLUSH_INTERVAL_SECONDS")
    environment: str = Field(
        pattern=_ENVIRONMENT_PATTERN,
        validation_alias="LANGFUSE_ENVIRONMENT",
    )


def _traces_endpoint(endpoint: str) -> str:
    value = endpoint.rstrip("/")
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "/api/public/ingestion" in parsed.path
    ):
        raise ValueError("invalid Langfuse OTLP endpoint")
    if not value.endswith("/v1/traces"):
        value += "/v1/traces"
    return value


def _unix_nano(timestamp: str) -> str:
    parsed = datetime.fromisoformat(timestamp[:-1] + "+00:00")
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = parsed - epoch
    return str(
        delta.days * 86_400_000_000_000 + delta.seconds * 1_000_000_000 + delta.microseconds * 1_000
    )


def _otlp_value(value: str | bool | int | float) -> dict[str, object]:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    return {"stringValue": value}


def _otlp_attributes(values: dict[str, str | bool | int | float]) -> list[dict[str, object]]:
    return [{"key": key, "value": _otlp_value(value)} for key, value in values.items()]


def _span_attributes(span: CompletedSpan, environment: str) -> dict[str, str | bool | int | float]:
    values: dict[str, str | bool | int | float] = {
        "langfuse.session.id": span.call_key,
        "langfuse.trace.name": "callbot.turn",
        "langfuse.environment": environment,
        "langfuse.observation.type": span.observation_type.lower(),
        "langfuse.trace.metadata.turn": str(span.turn),
        "langfuse.observation.metadata.turn": span.turn,
        "langfuse.observation.metadata.component": span.component,
        "langfuse.observation.metadata.operation": span.operation,
        "langfuse.observation.metadata.duration_ms": span.duration_ms,
    }
    for key, value in span.attributes.items():
        if value is not None:
            values[f"langfuse.observation.metadata.{key}"] = value
    if span.observation_type == "GENERATION":
        model = span.attributes.get("actual_model") or span.attributes.get("configured_model")
        if isinstance(model, str):
            values["langfuse.observation.model.name"] = model
        input_tokens = span.attributes.get("input_tokens")
        output_tokens = span.attributes.get("output_tokens")
        cached_tokens = span.attributes.get("cached_input_tokens")
        reasoning_tokens = span.attributes.get("reasoning_tokens")
        usage: dict[str, int] = {}
        if isinstance(input_tokens, int):
            usage["input"] = input_tokens
            if isinstance(cached_tokens, int) and cached_tokens <= input_tokens:
                usage["input"] -= cached_tokens
                if cached_tokens:
                    usage["input_cached_tokens"] = cached_tokens
        if isinstance(output_tokens, int):
            usage["output"] = output_tokens
            if isinstance(reasoning_tokens, int) and reasoning_tokens <= output_tokens:
                usage["output"] -= reasoning_tokens
                if reasoning_tokens:
                    usage["output_reasoning_tokens"] = reasoning_tokens
        if isinstance(span.attributes.get("total_tokens"), int):
            usage["total"] = span.attributes["total_tokens"]
        if usage:
            values["langfuse.observation.usage_details"] = json.dumps(usage, separators=(",", ":"))
        if isinstance(span.attributes.get("cost_usd"), (int, float)):
            values["langfuse.observation.cost_details"] = json.dumps(
                {"total": span.attributes["cost_usd"]}, separators=(",", ":")
            )
    if span.status == "ERROR" and isinstance(span.attributes.get("error_type"), str):
        values["error.type"] = span.attributes["error_type"]
    return values


def _otlp_span(span: CompletedSpan, environment: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "traceId": span.trace_id,
        "spanId": span.span_id,
        "name": span.operation,
        "kind": 1,
        "startTimeUnixNano": _unix_nano(span.start_time),
        "endTimeUnixNano": _unix_nano(span.end_time),
        "attributes": _otlp_attributes(_span_attributes(span, environment)),
        "status": {"code": {"OK": 1, "ERROR": 2, "CANCELLED": 0}[span.status]},
    }
    if span.parent_span_id is not None:
        payload["parentSpanId"] = span.parent_span_id
    if span.events:
        payload["events"] = [
            {
                "timeUnixNano": _unix_nano(event.timestamp),
                "name": event.name,
                "attributes": _otlp_attributes(event.attributes),
            }
            for event in span.events
        ]
    return payload


def _otlp_request(spans: list[CompletedSpan], environment: str) -> dict[str, object]:
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": _otlp_attributes(
                        {"service.name": "clinicalbot", "langfuse.environment": environment}
                    )
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "callbot.tracing", "version": "trace.v1"},
                        "spans": [_otlp_span(span, environment) for span in spans],
                    }
                ],
            }
        ]
    }


def _validated_snapshot(span: CompletedSpan) -> CompletedSpan:
    """Detach queued data from caller-owned mutable dicts after boundary validation."""
    validate_completed_span(span)
    snapshot = CompletedSpan(
        trace_id=span.trace_id,
        span_id=span.span_id,
        parent_span_id=span.parent_span_id,
        call_key=span.call_key,
        turn=span.turn,
        component=span.component,
        operation=span.operation,
        start_time=span.start_time,
        end_time=span.end_time,
        duration_ms=span.duration_ms,
        status=span.status,
        attributes=dict(span.attributes),
        events=tuple(
            TraceEvent(event.name, event.timestamp, dict(event.attributes)) for event in span.events
        ),
        observation_type=span.observation_type,
    )
    validate_completed_span(snapshot)
    return snapshot


class LangfuseOtlpTraceSink:
    """Non-blocking, drop-newest exporter for already-completed spans."""

    def __init__(
        self,
        *,
        endpoint: str,
        public_key: str,
        secret_key: str,
        environment: str = "development",
        timeout_seconds: float = 2.0,
        queue_size: int = 1024,
        batch_size: int = 32,
        flush_interval_seconds: float = 1.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not public_key or not secret_key:
            raise ValueError("Langfuse credentials are required")
        if queue_size <= 0 or batch_size <= 0 or batch_size > queue_size:
            raise ValueError("invalid Langfuse queue or batch size")
        if timeout_seconds <= 0 or flush_interval_seconds <= 0:
            raise ValueError("invalid Langfuse timeout")
        if not re.fullmatch(_ENVIRONMENT_PATTERN, environment) or environment.startswith(
            "langfuse"
        ):
            raise ValueError("invalid Langfuse environment")

        token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode("ascii")
        self._endpoint = _traces_endpoint(endpoint)
        self._headers = {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
            "x-langfuse-ingestion-version": "4",
        }
        self._environment = environment
        self._queue_size = queue_size
        self._batch_size = batch_size
        self._flush_interval_seconds = flush_interval_seconds
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._owns_client = client is None
        self._queue: deque[CompletedSpan] = deque()
        self._condition = threading.Condition()
        self._inflight = 0
        self._force_flush = False
        self._accepting = True
        self._stopping = False
        self._dropped_count = 0
        self._exported_count = 0
        self._worker = threading.Thread(target=self._run, name="langfuse-otlp-export", daemon=True)
        self._worker.start()

    @property
    def queued_count(self) -> int:
        with self._condition:
            return len(self._queue)

    @property
    def dropped_count(self) -> int:
        with self._condition:
            return self._dropped_count

    @property
    def exported_count(self) -> int:
        with self._condition:
            return self._exported_count

    def emit(self, span: CompletedSpan) -> None:
        try:
            snapshot = _validated_snapshot(span)
        except Exception:
            with self._condition:
                self._dropped_count += 1
            logger.warning("LANGFUSE_TRACE_DROPPED_UNSAFE")
            return

        with self._condition:
            if not self._accepting or len(self._queue) >= self._queue_size:
                self._dropped_count += 1
                logger.warning("LANGFUSE_TRACE_DROPPED_QUEUE_FULL")
                return
            self._queue.append(snapshot)
            self._condition.notify_all()

    def flush(self, timeout: float) -> bool:
        deadline = monotonic() + max(0.0, timeout)
        with self._condition:
            self._force_flush = True
            self._condition.notify_all()
            while self._queue or self._inflight:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    def close(self, timeout: float) -> bool:
        deadline = monotonic() + max(0.0, timeout)
        with self._condition:
            self._accepting = False
        flushed = self.flush(max(0.0, deadline - monotonic()))
        with self._condition:
            self._stopping = True
            self._force_flush = True
            self._condition.notify_all()
        self._worker.join(max(0.0, deadline - monotonic()))
        return flushed and not self._worker.is_alive()

    def _run(self) -> None:
        try:
            while True:
                batch = self._next_batch()
                if batch is None:
                    return
                self._send(batch)
                with self._condition:
                    self._inflight -= len(batch)
                    self._condition.notify_all()
        finally:
            if self._owns_client:
                try:
                    self._client.close()
                except Exception:
                    logger.warning("LANGFUSE_CLIENT_CLOSE_FAILED")

    def _next_batch(self) -> list[CompletedSpan] | None:
        with self._condition:
            while not self._queue:
                if self._stopping:
                    return None
                self._condition.wait()

            deadline = monotonic() + self._flush_interval_seconds
            while (
                len(self._queue) < self._batch_size and not self._force_flush and not self._stopping
            ):
                remaining = deadline - monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)

            size = min(len(self._queue), self._batch_size)
            batch = [self._queue.popleft() for _ in range(size)]
            self._inflight += size
            self._force_flush = False
            return batch

    def _send(self, spans: list[CompletedSpan]) -> None:
        try:
            response = self._client.post(
                self._endpoint,
                headers=self._headers,
                json=_otlp_request(spans, self._environment),
            )
            if not 200 <= response.status_code < 300:
                logger.warning("LANGFUSE_EXPORT_HTTP_FAILED")
                return
            with self._condition:
                self._exported_count += len(spans)
        except Exception:
            logger.warning("LANGFUSE_EXPORT_NETWORK_FAILED")


def create_langfuse_sink(
    settings: LangfuseOtlpSettings | None = None,
    *,
    client: httpx.Client | None = None,
) -> TraceSink:
    """Build an optional exporter without making invalid remote config fatal."""
    try:
        config = settings or LangfuseOtlpSettings()
        if not config.enabled:
            return NullTraceSink()
        return LangfuseOtlpTraceSink(
            endpoint=config.endpoint,
            public_key=config.public_key.get_secret_value(),
            secret_key=config.secret_key.get_secret_value(),
            environment=config.environment,
            timeout_seconds=config.timeout_seconds,
            queue_size=config.queue_size,
            batch_size=config.batch_size,
            flush_interval_seconds=config.flush_interval_seconds,
            client=client,
        )
    except Exception:
        logger.warning("LANGFUSE_CONFIG_INVALID")
        return NullTraceSink()
