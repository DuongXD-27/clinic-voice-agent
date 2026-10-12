"""One bounded model operation per IE turn; late results never re-enter the conversation."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from queue import Empty, Queue
from threading import BoundedSemaphore, Thread
from time import monotonic
from typing import Any

MODEL_TIMEOUT_S = 3.0
# Bound abandoned synchronous requests as well as active ones. Workers have no Clinic capability.
_workers = BoundedSemaphore(16)
_current: ContextVar["ModelBudget | None"] = ContextVar("ie_model_budget", default=None)


class ModelBudget:
    def __init__(self) -> None:
        self.used = False
        self.status: str | None = None
        self.model = "test-double"
        # Provider của model trả lời lượt; `backup_for` = provider chính đã lỗi khi dự phòng trả lời
        self.provider: str | None = None
        self.backup_for: str | None = None
        self.latency_ms = 0.0

    def run(self, adapter: Any, operation: Callable[[], Any]) -> Any:
        if self.used:
            return None
        self.used = True
        gateway = getattr(adapter, "_gateway", None)
        self.model = getattr(gateway, "model", "test-double")
        self.provider = getattr(gateway, "provider_name", None)
        config = getattr(getattr(gateway, "_provider", None), "_config", None)
        timeout = min(MODEL_TIMEOUT_S, getattr(config, "timeout_s", MODEL_TIMEOUT_S))
        started = monotonic()
        result: Queue[tuple[Any, str | None]] = Queue(maxsize=1)
        if not _workers.acquire(blocking=False):
            self.status = "ERROR"
            return None
        context = copy_context()

        def worker() -> None:
            try:
                try:
                    value = context.run(operation)
                    result.put((value, None))
                except Exception:
                    result.put((None, "ERROR"))
            finally:
                _workers.release()

        Thread(target=worker, daemon=True, name="ie-model-request").start()
        try:
            value, error = result.get(timeout=max(0.0, timeout - (monotonic() - started)))
            self.status = error or self.status or ("OK" if value is not None else "INVALID")
            return value if self.status == "OK" else None
        except Empty:
            self.status = "TIMEOUT"
            return None
        finally:
            self.latency_ms = (monotonic() - started) * 1000


@contextmanager
def model_turn() -> Iterator[ModelBudget]:
    budget = ModelBudget()
    token = _current.set(budget)
    try:
        yield budget
    finally:
        _current.reset(token)


def invoke_model(adapter: Any, operation: Callable[[], Any]) -> Any:
    budget = _current.get()
    return operation() if budget is None else budget.run(adapter, operation)


def model_used() -> bool:
    budget = _current.get()
    return budget is not None and budget.used


def hand_over_model(model: str, provider: str) -> None:
    """Provider chính lỗi, provider dự phòng chạy tiếp trong CÙNG ngân sách lượt: bỏ trạng thái lỗi
    đã báo (TIMEOUT / ERROR không bị ghi đè) để kết quả của provider dự phòng được dùng, và ghi đúng
    tên model / provider trả lời. Thời gian vẫn tính từ đầu lượt, không cộng thêm."""
    budget = _current.get()
    if budget is not None:
        budget.status = None
        budget.backup_for = budget.provider
        budget.provider = provider
        budget.model = model


def report_model_status(status: str) -> None:
    budget = _current.get()
    if budget is None or budget.status in {"TIMEOUT", "ERROR"}:
        return
    budget.status = (
        "OK"
        if status in {"accepted", "no_name"}
        else "TIMEOUT"
        if status == "timeout"
        else "ERROR"
        if status in {"http_error", "network_error"}
        else "INVALID"
    )
