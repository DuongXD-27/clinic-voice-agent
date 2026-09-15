"""Session Manager: tạo / quản lý phiên, lưu trạng thái hội thoại, quản lý state machine."""

import threading
from typing import Optional, Protocol

from callbot.engine.session.context import CallContext
from callbot.engine.session.fsm import ensure_transition
from callbot.engine.types import CallStart, CallState, Outcome


class SessionRepository(Protocol):
    def get(self, call_id: str) -> Optional[CallContext]: ...

    def save(self, ctx: CallContext) -> None: ...


class InMemorySessionRepository:
    """Đủ cho 1 process. TODO: Redis nếu chạy nhiều worker."""

    def __init__(self) -> None:
        self._items: dict[str, CallContext] = {}
        self._lock = threading.Lock()

    def get(self, call_id: str) -> Optional[CallContext]:
        with self._lock:
            return self._items.get(call_id)

    def save(self, ctx: CallContext) -> None:
        with self._lock:
            self._items[ctx.call_id] = ctx


class SessionNotFound(Exception):
    pass


class SessionManager:
    def __init__(self, repository: SessionRepository) -> None:
        self._repository = repository

    def open(self, call: CallStart) -> CallContext:
        ctx = CallContext(call=call)
        self._repository.save(ctx)
        return ctx

    def get(self, call_id: str) -> CallContext:
        ctx = self._repository.get(call_id)
        if ctx is None:
            raise SessionNotFound(call_id)
        return ctx

    def transition(self, ctx: CallContext, target: CallState) -> None:
        ensure_transition(ctx.state, target)
        ctx.state = target

    def close(self, ctx: CallContext, outcome: Outcome) -> None:
        ctx.outcome = outcome
        ctx.state = "ENDED"
        self._repository.save(ctx)

    def save(self, ctx: CallContext) -> None:
        self._repository.save(ctx)
