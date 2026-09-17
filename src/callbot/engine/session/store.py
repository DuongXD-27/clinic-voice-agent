"""Hợp đồng lưu phiên (F-03): session, lượt và nhật ký lệnh Clinic.

`InMemorySessionStore` và `postgres.PostgresSessionStore` cùng thoả hợp đồng này và chạy chung bộ test
(`tests/engine/session/test_store_contract.py`). Bản in-memory chỉ cho unit test / một process;
ứng dụng HTTP luôn dùng PostgreSQL.

Mọi giá trị trả về là bản sao: sửa đối tượng đọc ra không đổi dữ liệu đã lưu.
"""

import copy
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal, Optional, Protocol

from callbot.engine.errors import CallBusy, ReconciliationRequired

TurnStatus = Literal["PROCESSING", "COMPLETED", "RECONCILIATION_REQUIRED"]
CommandStatus = Literal["PENDING", "SUCCEEDED", "FAILED", "UNKNOWN"]


@dataclass(frozen=True)
class SessionRecord:
    call_id: str
    start_config: dict[str, Any]
    opening: dict[str, Any]
    context: dict[str, Any]
    last_completed_turn: int = 0
    ended: bool = False


@dataclass(frozen=True)
class TurnRecord:
    call_id: str
    turn: int
    input: dict[str, Any]
    received_at: datetime
    status: TurnStatus
    result: Optional[dict[str, Any]] = None
    extraction: Optional[dict[str, Any]] = None
    detail: Optional[str] = None


@dataclass(frozen=True)
class CommandRecord:
    idempotency_key: str
    call_id: str
    turn: int
    operation: str
    endpoint: str
    payload: dict[str, Any]
    if_match: Optional[int]
    status: CommandStatus = "PENDING"
    attempts: int = 1
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class SessionStore(Protocol):
    def call_lock(self, call_id: str, timeout_s: float) -> Any:
        """Context manager khóa theo `call_id` cho cả lượt; hết `timeout_s` -> `CallBusy`."""
        ...

    def get_session(self, call_id: str) -> Optional[SessionRecord]: ...

    def create_session(self, record: SessionRecord) -> None: ...

    def get_turn(self, call_id: str, turn: int) -> Optional[TurnRecord]: ...

    def find_blocked_turn(self, call_id: str) -> Optional[int]: ...

    def reserve_turn(
        self, call_id: str, turn: int, input: dict[str, Any], received_at: datetime
    ) -> None: ...

    def complete_turn(
        self,
        call_id: str,
        turn: int,
        context: dict[str, Any],
        result: dict[str, Any],
        extraction: Optional[dict[str, Any]],
        ended: bool,
    ) -> None:
        """Một transaction: context + history + kết quả lượt + last_completed_turn."""
        ...

    def mark_reconciliation_required(self, call_id: str, turn: int, detail: str) -> None: ...

    def list_commands(self, call_id: str, turn: Optional[int] = None) -> list[CommandRecord]: ...

    def begin_command(self, command: CommandRecord) -> None:
        """Commit lệnh PENDING trước khi gửi. Khóa đã tồn tại chỉ dùng lại được khi lần trước FAILED
        với cùng nội dung; trường hợp khác -> `ReconciliationRequired`."""
        ...

    def finish_command(
        self,
        idempotency_key: str,
        status: CommandStatus,
        result: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None: ...

    def check_ready(self) -> None:
        """Raise `SessionStoreUnavailable` nếu chưa phục vụ được (DB / schema)."""
        ...

    def close(self) -> None: ...


class InMemorySessionStore:
    """Một process. Khóa theo call_id bằng threading.Lock; dữ liệu lưu dạng JSON như PostgreSQL."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._call_locks: dict[str, threading.Lock] = {}
        self._sessions: dict[str, SessionRecord] = {}
        self._turns: dict[tuple[str, int], TurnRecord] = {}
        self._commands: dict[str, CommandRecord] = {}

    @contextmanager
    def call_lock(self, call_id: str, timeout_s: float) -> Iterator[None]:
        with self._guard:
            lock = self._call_locks.setdefault(call_id, threading.Lock())
        if not lock.acquire(timeout=timeout_s):
            raise CallBusy(call_id)
        try:
            yield
        finally:
            lock.release()

    def get_session(self, call_id: str) -> Optional[SessionRecord]:
        with self._guard:
            return _copy(self._sessions.get(call_id))

    def create_session(self, record: SessionRecord) -> None:
        with self._guard:
            if record.call_id in self._sessions:
                raise ValueError(f"Session {record.call_id} đã tồn tại")
            self._sessions[record.call_id] = _json_copy(record)

    def get_turn(self, call_id: str, turn: int) -> Optional[TurnRecord]:
        with self._guard:
            return _copy(self._turns.get((call_id, turn)))

    def find_blocked_turn(self, call_id: str) -> Optional[int]:
        with self._guard:
            blocked = [
                record.turn
                for (owner, _), record in self._turns.items()
                if owner == call_id and record.status == "RECONCILIATION_REQUIRED"
            ]
        return min(blocked) if blocked else None

    def reserve_turn(
        self, call_id: str, turn: int, input: dict[str, Any], received_at: datetime
    ) -> None:
        with self._guard:
            if call_id not in self._sessions:
                raise KeyError(call_id)
            if (call_id, turn) in self._turns:
                raise ValueError(f"Lượt {call_id}/{turn} đã tồn tại")
            self._turns[(call_id, turn)] = TurnRecord(
                call_id, turn, _json_roundtrip(input), received_at, "PROCESSING"
            )

    def complete_turn(
        self,
        call_id: str,
        turn: int,
        context: dict[str, Any],
        result: dict[str, Any],
        extraction: Optional[dict[str, Any]],
        ended: bool,
    ) -> None:
        with self._guard:
            record = self._turns.get((call_id, turn))
            session = self._sessions.get(call_id)
            if record is None or record.status != "PROCESSING":
                raise ValueError(f"Lượt {call_id}/{turn} không ở trạng thái PROCESSING")
            if session is None or session.last_completed_turn != turn - 1:
                raise ValueError(f"Session {call_id} không chờ lượt {turn}")
            self._turns[(call_id, turn)] = replace(
                record,
                status="COMPLETED",
                result=_json_roundtrip(result),
                extraction=_json_roundtrip(extraction),
            )
            self._sessions[call_id] = replace(
                session,
                context=_json_roundtrip(context),
                last_completed_turn=turn,
                ended=ended,
            )

    def mark_reconciliation_required(self, call_id: str, turn: int, detail: str) -> None:
        with self._guard:
            record = self._turns.get((call_id, turn))
            if record is not None and record.status != "COMPLETED":
                self._turns[(call_id, turn)] = replace(
                    record, status="RECONCILIATION_REQUIRED", detail=detail
                )

    def list_commands(self, call_id: str, turn: Optional[int] = None) -> list[CommandRecord]:
        with self._guard:
            return [
                _copy(command)
                for command in self._commands.values()
                if command.call_id == call_id and (turn is None or command.turn == turn)
            ]

    def begin_command(self, command: CommandRecord) -> None:
        with self._guard:
            if (command.call_id, command.turn) not in self._turns:
                raise KeyError(f"{command.call_id}/{command.turn}")
            existing = self._commands.get(command.idempotency_key)
            if existing is None:
                self._commands[command.idempotency_key] = _json_copy(
                    replace(command, status="PENDING", attempts=1, result=None, error=None)
                )
                return
            if not _same_command(existing, command) or existing.status != "FAILED":
                raise ReconciliationRequired(
                    command.call_id, command.turn, f"lệnh {command.idempotency_key} đã tồn tại"
                )
            self._commands[command.idempotency_key] = replace(
                existing,
                status="PENDING",
                attempts=existing.attempts + 1,
                if_match=command.if_match,
                result=None,
                error=None,
            )

    def finish_command(
        self,
        idempotency_key: str,
        status: CommandStatus,
        result: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        with self._guard:
            existing = self._commands[idempotency_key]
            self._commands[idempotency_key] = replace(
                existing, status=status, result=_json_roundtrip(result), error=error
            )

    def check_ready(self) -> None:
        return None

    def close(self) -> None:
        return None


def _same_command(left: CommandRecord, right: CommandRecord) -> bool:
    return (left.call_id, left.turn, left.operation, left.endpoint, left.payload) == (
        right.call_id,
        right.turn,
        right.operation,
        right.endpoint,
        _json_roundtrip(right.payload),
    )


def _json_roundtrip(value: Any) -> Any:
    # Cùng ràng buộc với JSONB: dữ liệu không tuần tự hoá được phải lỗi ngay ở unit test
    return None if value is None else json.loads(json.dumps(value, ensure_ascii=False))


def _json_copy(record: Any) -> Any:
    fields = {
        name: _json_roundtrip(getattr(record, name))
        for name in ("start_config", "opening", "context", "input", "payload", "result")
        if hasattr(record, name)
    }
    return replace(record, **fields)


def _copy(record: Any) -> Any:
    return copy.deepcopy(record)
