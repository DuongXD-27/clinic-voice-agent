"""Vendor-neutral span source contracts and a streaming JSONL implementation."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from callbot.observability.models import SourceDiagnostics
from callbot.tracing.models import CompletedSpan, TraceEvent
from callbot.tracing.privacy import SPAN_FIELDS, validate_completed_span

_BASE_FIELDS = frozenset(
    {
        "schema_version",
        "record_type",
        "trace_id",
        "span_id",
        "parent_span_id",
        "call_key",
        "turn",
        "component",
        "operation",
        "start_time",
        "end_time",
        "duration_ms",
        "status",
        "events",
        "observation_type",
    }
)


def require_utc_range(start_time: datetime, end_time: datetime) -> tuple[datetime, datetime]:
    if start_time.tzinfo is None or start_time.utcoffset() is None:
        raise ValueError("start_time must be timezone-aware")
    if end_time.tzinfo is None or end_time.utcoffset() is None:
        raise ValueError("end_time must be timezone-aware")
    start = start_time.astimezone(timezone.utc)
    end = end_time.astimezone(timezone.utc)
    if end <= start:
        raise ValueError("end_time must be after start_time")
    return start, end


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("trace timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


class SpanSource(Protocol):
    @property
    def diagnostics(self) -> SourceDiagnostics: ...

    def query(self, start_time: datetime, end_time: datetime) -> Iterator[CompletedSpan]: ...


class JsonlSpanSource:
    """Stream every PID/rotation trace file and yield valid records in ``[start, end)``."""

    def __init__(self, directory: str | Path) -> None:
        self._directory = Path(directory)
        self._diagnostics = SourceDiagnostics()

    @property
    def diagnostics(self) -> SourceDiagnostics:
        return self._diagnostics

    def query(self, start_time: datetime, end_time: datetime) -> Iterator[CompletedSpan]:
        start, end = require_utc_range(start_time, end_time)
        counters = {
            "files_read": 0,
            "files_skipped": 0,
            "records_seen": 0,
            "records_yielded": 0,
            "records_skipped": 0,
            "unsupported_records": 0,
        }
        self._diagnostics = SourceDiagnostics()
        try:
            for path in self._paths(counters):
                try:
                    with path.open("r", encoding="utf-8", errors="replace") as stream:
                        counters["files_read"] += 1
                        for line in stream:
                            if not line.strip():
                                continue
                            counters["records_seen"] += 1
                            try:
                                raw = json.loads(line)
                                if not isinstance(raw, dict):
                                    raise ValueError("trace record must be an object")
                                if raw.get("schema_version") not in {"trace.v1", "trace.v2"} or (
                                    raw.get("schema_version") == "trace.v2"
                                    and raw.get("record_type") != "generation"
                                ):
                                    counters["unsupported_records"] += 1
                                    continue
                                span = _parse_span(raw)
                                started = parse_timestamp(span.start_time)
                            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                                counters["records_skipped"] += 1
                                continue
                            if start <= started < end:
                                counters["records_yielded"] += 1
                                yield span
                except OSError:
                    counters["files_skipped"] += 1
        finally:
            self._diagnostics = SourceDiagnostics(**counters)

    def query_scores(self, start_time: datetime, end_time: datetime) -> Iterator[dict[str, Any]]:
        start, end = require_utc_range(start_time, end_time)
        for path in self._directory.glob("score-????????.jsonl"):
            try:
                with path.open("r", encoding="utf-8") as stream:
                    for line in stream:
                        try:
                            item = json.loads(line)
                            if not isinstance(item, dict):
                                continue
                            if set(item) - {
                                "schema_version",
                                "record_type",
                                "timestamp",
                                "name",
                                "value",
                                "trace_id",
                                "session_id",
                                "langfuse_published",
                            }:
                                continue
                            if (
                                item.get("schema_version") != "score.v1"
                                or item.get("record_type") != "score"
                            ):
                                continue
                            if item.get("name") not in {
                                "task_success",
                                "contract_pass",
                                "severe_failure",
                                "latency_pass",
                                "privacy_pass",
                            }:
                                continue
                            trace_id = item.get("trace_id")
                            session_id = item.get("session_id")
                            if (trace_id is None) == (session_id is None):
                                continue
                            identity = trace_id or session_id
                            pattern = (
                                r"[0-9a-f]{32}"
                                if trace_id is not None
                                else r"ck_[A-Za-z0-9_-]+_[A-Za-z0-9_-]{22}"
                            )
                            if (
                                not isinstance(identity, str)
                                or re.fullmatch(pattern, identity) is None
                            ):
                                continue
                            value = item.get("value")
                            if not isinstance(value, (bool, int, float)) or not 0 <= value <= 1:
                                continue
                            if "langfuse_published" in item and not isinstance(
                                item["langfuse_published"], bool
                            ):
                                continue
                            if start <= parse_timestamp(item["timestamp"]) < end:
                                yield item
                        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                            continue
            except OSError:
                continue

    def _paths(self, counters: dict[str, int]) -> Iterator[Path]:
        if not self._directory.is_dir():
            return
        seen_files: set[tuple[int, int] | str] = set()
        for path in sorted(self._directory.glob("trace-????????-p*.jsonl")):
            try:
                stat = path.stat()
                identity: tuple[int, int] | str
                identity = (stat.st_dev, stat.st_ino) if stat.st_ino else str(path.resolve())
            except OSError:
                counters["files_skipped"] += 1
                continue
            if identity in seen_files:
                continue
            seen_files.add(identity)
            yield path


def _parse_span(raw: dict[str, Any]) -> CompletedSpan:
    if raw.get("record_type") not in {"span", "generation"}:
        raise ValueError("unsupported trace record type")
    unknown = set(raw) - _BASE_FIELDS - SPAN_FIELDS
    if unknown:
        raise ValueError("trace record contains unknown fields")

    events_raw = raw.get("events", [])
    if not isinstance(events_raw, list):
        raise ValueError("trace events must be a list")
    events: list[TraceEvent] = []
    for event in events_raw:
        if not isinstance(event, dict) or set(event) - {"name", "timestamp", "attributes"}:
            raise ValueError("trace event is invalid")
        attributes = event.get("attributes", {})
        if not isinstance(attributes, dict):
            raise ValueError("trace event attributes are invalid")
        events.append(
            TraceEvent(
                name=event["name"],
                timestamp=event["timestamp"],
                attributes=dict(attributes),
            )
        )

    attributes = {key: raw[key] for key in SPAN_FIELDS if key in raw and raw[key] is not None}
    span = CompletedSpan(
        trace_id=raw["trace_id"],
        span_id=raw["span_id"],
        parent_span_id=raw["parent_span_id"],
        call_key=raw["call_key"],
        turn=raw["turn"],
        component=raw["component"],
        operation=raw["operation"],
        start_time=raw["start_time"],
        end_time=raw["end_time"],
        duration_ms=raw["duration_ms"],
        status=raw["status"],
        attributes=attributes,
        events=tuple(events),
        observation_type="GENERATION" if raw.get("record_type") == "generation" else "SPAN",
    )
    validate_completed_span(span)
    return span
