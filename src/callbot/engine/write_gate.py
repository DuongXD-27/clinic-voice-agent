"""Cổng gửi lệnh ghi Clinic của một lượt (R-36): khách đã rời cuộc gọi thì không gửi thêm request nào.

SessionManager gắn cổng cho mỗi lượt; ClinicGateway hỏi ngay trước mỗi lần gửi (kể cả gửi lại).
Ngoài một lượt (test gọi thẳng gateway) thì luôn cho gửi.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

_gate: ContextVar[Optional[Callable[[], bool]]] = ContextVar("clinic_write_gate", default=None)


@contextmanager
def bind_write_gate(allowed: Callable[[], bool]) -> Iterator[None]:
    token = _gate.set(allowed)
    try:
        yield
    finally:
        _gate.reset(token)


def write_allowed() -> bool:
    allowed = _gate.get()
    return allowed() if allowed is not None else True
