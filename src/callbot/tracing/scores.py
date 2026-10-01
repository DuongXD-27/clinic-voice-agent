"""Optional score bridge for already-evaluated, explicitly correlated results."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from pydantic import Field

from appconfig import YamlSettings, yaml_config
from callbot.tracing.langfuse_sink import LangfuseOtlpSettings

logger = logging.getLogger(__name__)
_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
_SESSION_ID = re.compile(r"^ck_[A-Za-z0-9_-]+_[A-Za-z0-9_-]{22}$")
_SCORE_NAMES = frozenset(
    {"task_success", "contract_pass", "severe_failure", "latency_pass", "privacy_pass"}
)


class ScoreSettings(YamlSettings):
    model_config = yaml_config("tracing.yaml", "scores", populate_by_name=True)
    enabled: bool = Field(default=False, validation_alias="LANGFUSE_SCORE_PUBLISH_ENABLED")
    jsonl_dir: Path | None = Field(default=None, validation_alias="LANGFUSE_SCORE_JSONL_DIR")


@dataclass(frozen=True)
class EvaluatedScore:
    """Construct only after an evaluator has produced the verdict and known correlation ID."""

    name: str
    value: bool | float
    trace_id: str | None = None
    session_id: str | None = None

    def __post_init__(self) -> None:
        if self.name not in _SCORE_NAMES:
            raise ValueError("score name is not allowlisted")
        if (self.trace_id is None) == (self.session_id is None):
            raise ValueError("score needs exactly one correlation ID")
        if self.trace_id is not None and not _TRACE_ID.fullmatch(self.trace_id):
            raise ValueError("invalid trace ID")
        if self.session_id is not None and not _SESSION_ID.fullmatch(self.session_id):
            raise ValueError("invalid pseudonymous session ID")
        if not isinstance(self.value, (bool, int, float)) or not 0 <= self.value <= 1:
            raise ValueError("score value must be boolean or numeric in [0, 1]")


class LangfuseScorePublisher:
    def __init__(
        self,
        settings: ScoreSettings | None = None,
        langfuse: LangfuseOtlpSettings | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._settings = settings or ScoreSettings()
        self._enabled = self._settings.enabled
        self._langfuse = langfuse
        self._client = client

    def publish(self, score: EvaluatedScore) -> bool:
        if not self._enabled:
            return False
        remote_published = False
        try:
            config = self._langfuse or LangfuseOtlpSettings()
            parsed = urlparse(config.endpoint)
            if parsed.scheme != "https" or not parsed.netloc:
                logger.warning("LANGFUSE_SCORE_CONFIG_INVALID")
            else:
                prefix = parsed.path.split("/api/public/otel", 1)[0]
                endpoint = f"{parsed.scheme}://{parsed.netloc}{prefix}/api/public/scores"
                body: dict[str, object] = {
                    "name": score.name,
                    "value": int(score.value) if isinstance(score.value, bool) else score.value,
                    "dataType": "BOOLEAN" if isinstance(score.value, bool) else "NUMERIC",
                }
                body["traceId" if score.trace_id is not None else "sessionId"] = (
                    score.trace_id or score.session_id or ""
                )
                client = self._client or httpx.Client(timeout=2.0)
                try:
                    response = client.post(
                        endpoint,
                        auth=(
                            config.public_key.get_secret_value(),
                            config.secret_key.get_secret_value(),
                        ),
                        json=body,
                    )
                    remote_published = 200 <= response.status_code < 300
                    if not remote_published:
                        logger.warning("LANGFUSE_SCORE_HTTP_FAILED status=%d", response.status_code)
                finally:
                    if self._client is None:
                        client.close()
        except Exception:
            logger.warning("LANGFUSE_SCORE_PUBLISH_FAILED")
        finally:
            self._write_local(score, langfuse_published=remote_published)
        return remote_published

    def _write_local(self, score: EvaluatedScore, *, langfuse_published: bool) -> None:
        directory = self._settings.jsonl_dir
        if directory is None:
            return
        try:
            directory.mkdir(parents=True, exist_ok=True)
            now = datetime.now(timezone.utc)
            payload = {
                "schema_version": "score.v1",
                "record_type": "score",
                "timestamp": now.isoformat().replace("+00:00", "Z"),
                "name": score.name,
                "value": score.value,
                "trace_id": score.trace_id,
                "session_id": score.session_id,
                "langfuse_published": langfuse_published,
            }
            with (directory / f"score-{now:%Y%m%d}.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(payload, separators=(",", ":")) + "\n")
        except Exception:
            logger.warning("LANGFUSE_SCORE_LOCAL_WRITE_FAILED")
