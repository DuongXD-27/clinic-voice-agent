"""Trace sink boundary implemented by JSONL now and other backends later."""

from __future__ import annotations

import logging
from time import monotonic
from typing import Protocol

from callbot.tracing.models import CompletedSpan

logger = logging.getLogger(__name__)


class TraceSink(Protocol):
    def emit(self, span: CompletedSpan) -> None: ...


class NullTraceSink:
    def emit(self, span: CompletedSpan) -> None:
        del span


class CompositeTraceSink:
    """Fan out completed spans while isolating every sink from its siblings."""

    def __init__(self, *sinks: TraceSink) -> None:
        if not sinks:
            raise ValueError("at least one trace sink is required")
        self._sinks = sinks

    def emit(self, span: CompletedSpan) -> None:
        for sink in self._sinks:
            try:
                sink.emit(span)
            except Exception:
                logger.warning("TRACE_COMPOSITE_SINK_FAILED")

    def flush(self, timeout: float) -> bool:
        deadline = monotonic() + max(0.0, timeout)
        complete = True
        for sink in self._sinks:
            flush = getattr(sink, "flush", None)
            if flush is None:
                continue
            try:
                remaining = max(0.0, deadline - monotonic())
                complete = bool(flush(remaining)) and complete
            except Exception:
                logger.warning("TRACE_COMPOSITE_FLUSH_FAILED")
                complete = False
        return complete

    def close(self, timeout: float) -> bool:
        deadline = monotonic() + max(0.0, timeout)
        complete = True
        for sink in self._sinks:
            close = getattr(sink, "close", None)
            if close is None:
                continue
            try:
                remaining = max(0.0, deadline - monotonic())
                complete = bool(close(remaining)) and complete
            except Exception:
                logger.warning("TRACE_COMPOSITE_CLOSE_FAILED")
                complete = False
        return complete
