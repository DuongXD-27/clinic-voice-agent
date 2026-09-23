"""Vendor-neutral trace records."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class TraceEvent:
    name: str
    timestamp: str
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"name": self.name, "timestamp": self.timestamp}
        if self.attributes:
            result["attributes"] = self.attributes
        return result


@dataclass(frozen=True, slots=True)
class CompletedSpan:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    call_key: str
    turn: int
    component: str
    operation: str
    start_time: str
    end_time: str
    duration_ms: float
    status: str
    attributes: dict[str, Any] = field(default_factory=dict)
    events: tuple[TraceEvent, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": "trace.v1",
            "record_type": "span",
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "call_key": self.call_key,
            "turn": self.turn,
            "component": self.component,
            "operation": self.operation,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "status": self.status,
        }
        result.update(self.attributes)
        if self.events:
            result["events"] = [event.to_dict() for event in self.events]
        return result
