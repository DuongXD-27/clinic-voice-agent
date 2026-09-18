"""Session-store contract and serializable records.

The application implementation is RedisSessionStore. There is intentionally no second in-process
implementation: tests exercise the same Redis code path through a Redis-compatible test server.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Optional, Protocol

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
    purged_reason: Optional[str] = None


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
    def expire_session(self, call_id: str) -> None: ...

    def purge_expired(self) -> int: ...

    def call_lock(self, call_id: str, timeout_s: float) -> Any: ...

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
    ) -> None: ...

    def mark_reconciliation_required(self, call_id: str, turn: int, detail: str) -> None: ...

    def list_commands(self, call_id: str, turn: Optional[int] = None) -> list[CommandRecord]: ...

    def begin_command(self, command: CommandRecord) -> None: ...

    def finish_command(
        self,
        call_id: str,
        idempotency_key: str,
        status: CommandStatus,
        result: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None: ...

    def check_ready(self) -> None: ...

    def close(self) -> None: ...


def same_command(left: CommandRecord, right: CommandRecord) -> bool:
    return (left.call_id, left.turn, left.operation, left.endpoint, left.payload) == (
        right.call_id,
        right.turn,
        right.operation,
        right.endpoint,
        json_copy(right.payload),
    )


def json_copy(value: Any) -> Any:
    return None if value is None else json.loads(json.dumps(value, ensure_ascii=False))
