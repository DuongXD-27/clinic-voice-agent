"""Fail-open tracing facade and ContextVar propagation."""

from __future__ import annotations

import logging
import secrets
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from time import perf_counter_ns
from types import TracebackType

from callbot.tracing.errors import TRACE_STATUSES, classify_exception
from callbot.tracing.models import CompletedSpan, TraceEvent
from callbot.tracing.privacy import (
    SafeAttributes,
    validate_completed_span,
    validate_component_operation,
)
from callbot.tracing.pseudonym import CallKeyFactory
from callbot.tracing.sink import NullTraceSink, TraceSink

logger = logging.getLogger(__name__)

_CURRENT_SPAN: ContextVar[SpanHandle | None] = ContextVar("trace_current_span", default=None)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class SpanHandle:
    """Mutable in-flight span; only safe, prevalidated attributes can be attached."""

    def __init__(
        self,
        tracer: Tracer,
        *,
        trace_id: str,
        span_id: str,
        parent_span_id: str | None,
        call_key: str,
        turn: int,
        component: str,
        operation: str,
        parent: SpanHandle | None = None,
        enabled: bool = True,
    ) -> None:
        self._tracer = tracer
        self.trace_id = trace_id
        self.span_id = span_id
        self.parent_span_id = parent_span_id
        self.call_key = call_key
        self.turn = turn
        self.component = component
        self.operation = operation
        self._parent = parent
        self.enabled = enabled
        self._start_time = _utc_now()
        self._start_ns = perf_counter_ns()
        self._status = "OK"
        self._attributes: dict[str, object] = {}
        self._events: list[TraceEvent] = []
        self._ended = False

    def set_safe_attributes(self, attributes: SafeAttributes) -> None:
        if not self.enabled:
            return
        try:
            self._attributes.update(attributes.values)
        except Exception:
            logger.warning("TRACE_ATTRIBUTE_REJECTED")

    def enrich(self, **attributes: object) -> None:
        """Attach validated span metadata without affecting business control flow."""
        if not self.enabled:
            return
        try:
            self.set_safe_attributes(SafeAttributes.for_span(**attributes))
        except Exception:
            logger.warning("TRACE_ATTRIBUTE_REJECTED")

    def event(self, name: str, attributes: SafeAttributes | None = None, **values: object) -> None:
        if not self.enabled:
            return
        try:
            if attributes is not None and values:
                raise ValueError("trace event attributes were provided twice")
            safe = attributes or SafeAttributes.for_event(name, **values)
            self._events.append(
                TraceEvent(
                    name=name,
                    timestamp=_utc_now(),
                    attributes=dict(safe.values),
                )
            )
        except Exception:
            logger.warning("TRACE_EVENT_REJECTED")

    def set_status(self, status: str) -> None:
        if status not in TRACE_STATUSES:
            logger.warning("TRACE_STATUS_REJECTED")
            return
        if self.enabled:
            self._status = status

    def set_error(self, exc: BaseException) -> None:
        try:
            info = classify_exception(exc)
            self.set_error_code(info.error_type, info.error_code)
        except Exception:
            logger.warning("TRACE_ERROR_REJECTED")
            if self.enabled:
                self._status = "ERROR"

    def set_error_code(self, error_type: str, error_code: str) -> None:
        if not self.enabled:
            return
        self._status = "ERROR"
        self.enrich(error_type=error_type, error_code=error_code)

    def increment_ancestor_counter(self, component: str, field: str) -> None:
        span: SpanHandle | None = self
        while span is not None:
            if span.component == component and span.enabled:
                try:
                    current = span._attributes.get(field, 0)
                    span.enrich(**{field: int(current) + 1})
                except Exception:
                    logger.warning("TRACE_ATTRIBUTE_REJECTED")
                return
            span = span._parent

    def set_ancestor_safe_attributes(self, component: str, attributes: SafeAttributes) -> None:
        span = self._parent
        while span is not None:
            if span.component == component and span.enabled:
                span.set_safe_attributes(attributes)
                return
            span = span._parent

    def enrich_ancestor(self, component: str, **attributes: object) -> None:
        span = self._parent
        while span is not None:
            if span.component == component and span.enabled:
                span.enrich(**attributes)
                return
            span = span._parent

    def finish(self) -> None:
        if not self.enabled or self._ended:
            return
        self._ended = True
        try:
            completed = CompletedSpan(
                trace_id=self.trace_id,
                span_id=self.span_id,
                parent_span_id=self.parent_span_id,
                call_key=self.call_key,
                turn=self.turn,
                component=self.component,
                operation=self.operation,
                start_time=self._start_time,
                end_time=_utc_now(),
                duration_ms=max(0.0, (perf_counter_ns() - self._start_ns) / 1_000_000),
                status=self._status,
                attributes=dict(self._attributes),
                events=tuple(self._events),
            )
            self._tracer._emit(completed)
        except Exception:
            logger.warning("TRACE_SPAN_FINISH_FAILED")


class _SpanScope:
    def __init__(self, span: SpanHandle) -> None:
        self._span = span
        self._token: Token[SpanHandle | None] | None = None

    def __enter__(self) -> SpanHandle:
        self._token = _CURRENT_SPAN.set(self._span)
        return self._span

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exc_type, traceback
        try:
            if exc is not None and self._span._status == "OK":
                if type(exc).__name__ == "CancelledError":
                    self._span.set_status("CANCELLED")
                else:
                    self._span.set_error(exc)
            self._span.finish()
        except Exception:
            logger.warning("TRACE_SCOPE_FAILED")
        finally:
            if self._token is not None:
                _CURRENT_SPAN.reset(self._token)
        return False


class Tracer:
    def __init__(
        self,
        sink: TraceSink | None = None,
        call_keys: CallKeyFactory | None = None,
    ) -> None:
        self._sink: TraceSink = sink or NullTraceSink()
        self._call_keys = call_keys

    @property
    def enabled(self) -> bool:
        return self._call_keys is not None and not isinstance(self._sink, NullTraceSink)

    def current_span(self) -> SpanHandle | None:
        return _CURRENT_SPAN.get()

    def start_trace(self, *, call_id: str, turn: int, component: str, operation: str) -> _SpanScope:
        if not self.enabled:
            return _SpanScope(self._noop(component, operation, turn))
        try:
            validate_component_operation(component, operation)
            assert self._call_keys is not None
            call_key = self._call_keys.create(call_id)
            return _SpanScope(
                SpanHandle(
                    self,
                    trace_id=secrets.token_hex(16),
                    span_id=secrets.token_hex(8),
                    parent_span_id=None,
                    call_key=call_key,
                    turn=turn,
                    component=component,
                    operation=operation,
                )
            )
        except Exception:
            logger.warning("TRACE_START_REJECTED")
            return _SpanScope(self._noop(component, operation, turn))

    def span(self, *, component: str, operation: str) -> _SpanScope:
        parent = _CURRENT_SPAN.get()
        if parent is None or not parent.enabled:
            return _SpanScope(self._noop(component, operation, parent.turn if parent else 0))
        try:
            validate_component_operation(component, operation)
            return _SpanScope(
                SpanHandle(
                    self,
                    trace_id=parent.trace_id,
                    span_id=secrets.token_hex(8),
                    parent_span_id=parent.span_id,
                    call_key=parent.call_key,
                    turn=parent.turn,
                    component=component,
                    operation=operation,
                    parent=parent,
                )
            )
        except Exception:
            logger.warning("TRACE_SPAN_REJECTED")
            return _SpanScope(self._noop(component, operation, parent.turn))

    def event(self, name: str, **attributes: object) -> None:
        span = _CURRENT_SPAN.get()
        if span is not None and span.enabled:
            span.event(name, **attributes)

    def _noop(self, component: str, operation: str, turn: int) -> SpanHandle:
        return SpanHandle(
            self,
            trace_id="",
            span_id="",
            parent_span_id=None,
            call_key="",
            turn=turn,
            component=component,
            operation=operation,
            enabled=False,
        )

    def _emit(self, span: CompletedSpan) -> None:
        try:
            validate_completed_span(span)
            self._sink.emit(span)
        except Exception:
            logger.warning("TRACE_SINK_WRITE_FAILED")

    def flush(self, timeout: float) -> bool:
        flush = getattr(self._sink, "flush", None)
        if flush is None:
            return True
        try:
            return bool(flush(max(0.0, timeout)))
        except Exception:
            logger.warning("TRACE_FLUSH_FAILED")
            return False

    def close(self, timeout: float) -> bool:
        close = getattr(self._sink, "close", None)
        if close is None:
            return True
        try:
            return bool(close(max(0.0, timeout)))
        except Exception:
            logger.warning("TRACE_CLOSE_FAILED")
            return False


def null_tracer() -> Tracer:
    return Tracer()


def trace_event(name: str, **attributes: object) -> None:
    """Record against the active span without coupling domain services to a sink."""
    span = _CURRENT_SPAN.get()
    if span is None or not span.enabled:
        return
    span.event(name, **attributes)


def current_span() -> SpanHandle | None:
    return _CURRENT_SPAN.get()
