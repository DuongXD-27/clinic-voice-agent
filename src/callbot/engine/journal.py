"""Nhật ký lệnh ghi Clinic (F-03).

Gateway ghi lệnh vào nhật ký và commit TRƯỚC khi gửi, rồi cập nhật kết quả. Nhờ vậy khi worker chết
giữa chừng, lượt đó biết mình đã (có thể) gửi lệnh và bị chặn đối soát thay vì gửi lại mù.

Nhật ký gắn với lượt đang xử lý qua ContextVar: SessionManager bind trong `run_turn`, Gateway đọc ra.
Dùng ContextVar thay vì truyền tham số qua Dialogue để Dialogue không phải biết tới lưu trữ; mỗi request
FastAPI chạy trong context riêng nên hai cuộc gọi đồng thời không lẫn nhật ký.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Literal, Optional, Protocol


@dataclass(frozen=True)
class ClinicCommand:
    operation: str  # confirm | cancel | reschedule | transfer | unreachable | book
    endpoint: str
    payload: dict[str, Any]
    if_match: Optional[int]
    idempotency_key: str


EntryStatus = Literal["PENDING", "SUCCEEDED", "FAILED", "UNKNOWN"]


@dataclass(frozen=True)
class JournalEntry:
    """Một lệnh ghi của lượt, giữ trong RAM (R-01 §3.3).

    `result` chỉ có khi nhật ký bền vững đã ghi `SUCCEEDED` (receipt). Session store không giữ được
    receipt: Redis ghi `result=None` và purge phiên ngay khi lệnh thành công.
    """

    command: ClinicCommand
    status: EntryStatus
    result: Optional[dict[str, Any]] = None


class CommandJournal(Protocol):
    def begin(self, command: ClinicCommand) -> None: ...

    def succeeded(self, command: ClinicCommand, result: dict[str, Any]) -> None: ...

    def failed(self, command: ClinicCommand, error: str) -> None: ...

    def unknown(self, command: ClinicCommand, error: str) -> None: ...

    def entries(self) -> list[JournalEntry]:
        """Các lệnh ghi của lượt theo thứ tự `begin`; nguồn duy nhất của receipt gate và Output Guard."""
        ...


_current: ContextVar[Optional[CommandJournal]] = ContextVar("clinic_command_journal", default=None)


@contextmanager
def bind_journal(journal: CommandJournal) -> Iterator[None]:
    token = _current.set(journal)
    try:
        yield
    finally:
        _current.reset(token)


def turn_entries() -> list[JournalEntry]:
    """Lệnh ghi của lượt đang xử lý; không bind nhật ký (ngoài một lượt) thì không có lệnh nào."""
    journal = _current.get()
    return journal.entries() if journal is not None else []


def current_journal() -> CommandJournal:
    journal = _current.get()
    if journal is None:
        # Ghi Clinic ngoài một lượt đã đặt chỗ là lỗi lập trình: không có chỗ lưu lệnh để đối soát
        raise RuntimeError("Lệnh ghi Clinic phải chạy trong một lượt có nhật ký lệnh")
    return journal
