"""Session store trên PostgreSQL (F-03) — dùng được với nhiều worker / nhiều máy.

Khóa theo call_id là advisory lock CẤP SESSION trên một connection riêng, giữ suốt lượt; dữ liệu đọc/ghi
bằng connection khác mượn từ pool. Khóa luôn được mở trước khi trả connection về pool; mở khóa lỗi thì
đóng hẳn connection (PostgreSQL tự nhả khóa khi session kết thúc), không trả connection còn giữ khóa.
https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS

Mọi lỗi psycopg / pool đổi thành `SessionStoreUnavailable` — HTTP trả 503, không gửi lệnh Clinic.
"""

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool, PoolTimeout

from callbot.engine.errors import CallBusy, ReconciliationRequired, SessionStoreUnavailable
from callbot.engine.session.context import SCHEMA_VERSION
from callbot.engine.session.postgres.schema import LATEST_SCHEMA_VERSION
from callbot.engine.session.store import (
    CommandRecord,
    CommandStatus,
    SessionRecord,
    TurnRecord,
)

logger = logging.getLogger(__name__)

_LOCK_POLL_S = 0.05
_DB_ERRORS = (psycopg.Error, PoolTimeout)


class PostgresSessionStore:
    def __init__(
        self,
        conninfo: str,
        min_size: int = 1,
        max_size: int = 10,
        timeout_s: float = 5.0,
    ) -> None:
        self._timeout_s = timeout_s
        self._pool = ConnectionPool(
            conninfo,
            min_size=min_size,
            max_size=max_size,
            timeout=timeout_s,
            kwargs={"autocommit": True, "row_factory": dict_row, "connect_timeout": 5},
            # Không chờ DB khi khởi động: worker vẫn lên, /ready và request trả 503 tới khi DB sẵn sàng
            open=False,
        )

    def open(self) -> None:
        self._pool.open(wait=False)

    def close(self) -> None:
        self._pool.close()

    # --- Khóa theo call_id ------------------------------------------------------------

    @contextmanager
    def call_lock(self, call_id: str, timeout_s: float) -> Iterator[None]:
        try:
            conn = self._pool.getconn(timeout=timeout_s)
        except _DB_ERRORS as exc:
            raise SessionStoreUnavailable("Không lấy được connection khóa") from exc

        discard = False
        try:
            try:
                acquired = self._try_lock_until(conn, call_id, timeout_s)
            except psycopg.Error as exc:
                discard = True
                raise SessionStoreUnavailable("Không lấy được khóa phiên") from exc
            if not acquired:
                raise CallBusy(call_id)
            try:
                yield
            finally:
                try:
                    conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (call_id,))
                except psycopg.Error:
                    discard = True
                    logger.exception("Mở khóa %s lỗi — đóng connection để nhả khóa", call_id)
        finally:
            if discard:
                conn.close()
            self._pool.putconn(conn)

    @staticmethod
    def _try_lock_until(conn: psycopg.Connection, call_id: str, timeout_s: float) -> bool:
        deadline = time.monotonic() + timeout_s
        while True:
            row = conn.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s, 0)) AS locked", (call_id,)
            ).fetchone()
            if row and row["locked"]:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(_LOCK_POLL_S, remaining))

    @contextmanager
    def _transaction(self) -> Iterator[psycopg.Connection]:
        try:
            with self._pool.connection(timeout=self._timeout_s) as conn:
                with conn.transaction():
                    yield conn
        except _DB_ERRORS as exc:
            raise SessionStoreUnavailable("Session store lỗi") from exc

    # --- Session -----------------------------------------------------------------------

    def get_session(self, call_id: str) -> Optional[SessionRecord]:
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT call_id, start_config, opening, context, last_completed_turn, ended"
                " FROM call_sessions WHERE call_id = %s",
                (call_id,),
            ).fetchone()
        return SessionRecord(**row) if row else None

    def create_session(self, record: SessionRecord) -> None:
        with self._transaction() as conn:
            conn.execute(
                "INSERT INTO call_sessions (call_id, start_config, opening, context,"
                " context_schema_version, last_completed_turn, ended)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    record.call_id,
                    Jsonb(record.start_config),
                    Jsonb(record.opening),
                    Jsonb(record.context),
                    SCHEMA_VERSION,
                    record.last_completed_turn,
                    record.ended,
                ),
            )

    # --- Lượt ----------------------------------------------------------------------------

    def get_turn(self, call_id: str, turn: int) -> Optional[TurnRecord]:
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT call_id, turn, input, received_at, status, result, extraction, detail"
                " FROM call_turns WHERE call_id = %s AND turn = %s",
                (call_id, turn),
            ).fetchone()
        return TurnRecord(**row) if row else None

    def find_blocked_turn(self, call_id: str) -> Optional[int]:
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT min(turn) AS turn FROM call_turns"
                " WHERE call_id = %s AND status = 'RECONCILIATION_REQUIRED'",
                (call_id,),
            ).fetchone()
        return row["turn"] if row else None

    def reserve_turn(
        self, call_id: str, turn: int, input: dict[str, Any], received_at: datetime
    ) -> None:
        with self._transaction() as conn:
            conn.execute(
                "INSERT INTO call_turns (call_id, turn, input, received_at, status)"
                " VALUES (%s, %s, %s, %s, 'PROCESSING')",
                (call_id, turn, Jsonb(input), received_at),
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
        with self._transaction() as conn:
            updated = conn.execute(
                "UPDATE call_turns SET status = 'COMPLETED', result = %s, extraction = %s,"
                " updated_at = now()"
                " WHERE call_id = %s AND turn = %s AND status = 'PROCESSING'",
                (
                    Jsonb(result),
                    Jsonb(extraction) if extraction is not None else None,
                    call_id,
                    turn,
                ),
            )
            if updated.rowcount != 1:
                raise ValueError(f"Lượt {call_id}/{turn} không ở trạng thái PROCESSING")
            updated = conn.execute(
                "UPDATE call_sessions SET context = %s, context_schema_version = %s,"
                " last_completed_turn = %s, ended = %s, updated_at = now()"
                " WHERE call_id = %s AND last_completed_turn = %s",
                (Jsonb(context), SCHEMA_VERSION, turn, ended, call_id, turn - 1),
            )
            if updated.rowcount != 1:
                raise ValueError(f"Session {call_id} không chờ lượt {turn}")

    def mark_reconciliation_required(self, call_id: str, turn: int, detail: str) -> None:
        with self._transaction() as conn:
            conn.execute(
                "UPDATE call_turns SET status = 'RECONCILIATION_REQUIRED', detail = %s,"
                " updated_at = now()"
                " WHERE call_id = %s AND turn = %s AND status <> 'COMPLETED'",
                (detail, call_id, turn),
            )

    # --- Nhật ký lệnh -------------------------------------------------------------------

    def list_commands(self, call_id: str, turn: Optional[int] = None) -> list[CommandRecord]:
        with self._transaction() as conn:
            rows = conn.execute(
                "SELECT idempotency_key, call_id, turn, operation, endpoint, payload, if_match,"
                " status, attempts, result, error FROM clinic_commands"
                " WHERE call_id = %s AND (%s::int IS NULL OR turn = %s)"
                " ORDER BY created_at, idempotency_key",
                (call_id, turn, turn),
            ).fetchall()
        return [CommandRecord(**row) for row in rows]

    def begin_command(self, command: CommandRecord) -> None:
        with self._transaction() as conn:
            existing = conn.execute(
                "SELECT call_id, turn, operation, endpoint, payload, status FROM clinic_commands"
                " WHERE idempotency_key = %s FOR UPDATE",
                (command.idempotency_key,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO clinic_commands (idempotency_key, call_id, turn, operation,"
                    " endpoint, payload, if_match, status)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, 'PENDING')",
                    (
                        command.idempotency_key,
                        command.call_id,
                        command.turn,
                        command.operation,
                        command.endpoint,
                        Jsonb(command.payload),
                        command.if_match,
                    ),
                )
                return
            same = (
                existing["call_id"],
                existing["turn"],
                existing["operation"],
                existing["endpoint"],
                existing["payload"],
            ) == (
                command.call_id,
                command.turn,
                command.operation,
                command.endpoint,
                command.payload,
            )
            if not same or existing["status"] != "FAILED":
                raise ReconciliationRequired(
                    command.call_id, command.turn, f"lệnh {command.idempotency_key} đã tồn tại"
                )
            conn.execute(
                "UPDATE clinic_commands SET status = 'PENDING', attempts = attempts + 1,"
                " if_match = %s, result = NULL, error = NULL, updated_at = now()"
                " WHERE idempotency_key = %s",
                (command.if_match, command.idempotency_key),
            )

    def finish_command(
        self,
        idempotency_key: str,
        status: CommandStatus,
        result: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        with self._transaction() as conn:
            conn.execute(
                "UPDATE clinic_commands SET status = %s, result = %s, error = %s,"
                " updated_at = now() WHERE idempotency_key = %s",
                (status, Jsonb(result) if result is not None else None, error, idempotency_key),
            )

    # --- Readiness ----------------------------------------------------------------------

    def check_ready(self) -> None:
        with self._transaction() as conn:
            row = conn.execute("SELECT max(version) AS version FROM schema_migrations").fetchone()
        version = row["version"] if row else None
        if version != LATEST_SCHEMA_VERSION:
            raise SessionStoreUnavailable(
                f"Schema phiên bản {version}, cần {LATEST_SCHEMA_VERSION} — chạy migrate"
            )
