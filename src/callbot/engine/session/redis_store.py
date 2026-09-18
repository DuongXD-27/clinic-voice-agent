"""Redis-backed temporary session store.

One JSON value holds a call's session, turns and command journal. Each mutation replaces that value
atomically. Redis locks serialize a call across workers. Customer content is erased immediately after
a Clinic acknowledgement, on a terminal turn, on an unknown write outcome, or at retention expiry.
"""

import json
import secrets
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime
from typing import Any, Optional

from redis import Redis
from redis.exceptions import RedisError, WatchError

from callbot.engine.errors import CallBusy, ReconciliationRequired, SessionStoreUnavailable
from callbot.engine.session.retention import RetentionPolicy, utcnow
from callbot.engine.session.store import (
    CommandRecord,
    CommandStatus,
    SessionRecord,
    TurnRecord,
    same_command,
)

_STATE_SCHEMA = 1


class RedisSessionStore:
    """Shared, bounded session store. Redis persistence must be disabled by deployment config."""

    def __init__(
        self,
        client: Redis,
        *,
        retention: Optional[RetentionPolicy] = None,
        key_prefix: str = "callbot",
        tombstone_ttl_s: int = 86400,
        max_session_bytes: int = 262_144,
        lock_lease_s: float = 60.0,
        clock: Callable[[], datetime] = utcnow,
        close_client: bool = True,
    ) -> None:
        if tombstone_ttl_s <= 0 or max_session_bytes <= 0 or lock_lease_s <= 0:
            raise ValueError("Redis session limits must be positive")
        self._client = client
        self._retention = retention or RetentionPolicy()
        self._prefix = key_prefix.rstrip(":")
        self._tombstone_ttl_s = tombstone_ttl_s
        self._max_session_bytes = max_session_bytes
        self._lock_lease_s = lock_lease_s
        self._clock = clock
        self._close_client = close_client
        self._closed = False
        self._held_locks = threading.local()
        if not self._prefix:
            raise ValueError("Redis key prefix must not be empty")

    @classmethod
    def from_url(cls, url: str, **kwargs: Any) -> "RedisSessionStore":
        client = Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
            health_check_interval=30,
            retry_on_timeout=False,
        )
        return cls(client, **kwargs)

    def validate_server_config(self) -> None:
        """Fail startup if Redis could persist or silently evict an active call."""
        try:
            config = self._client.config_get("save", "appendonly", "maxmemory", "maxmemory-policy")
        except RedisError as exc:
            raise SessionStoreUnavailable("Không đọc được cấu hình Redis") from exc
        invalid = []
        if str(config.get("save", "")).strip():
            invalid.append("save must be empty")
        if str(config.get("appendonly", "no")).lower() != "no":
            invalid.append("appendonly must be no")
        if int(config.get("maxmemory", 0)) <= 0:
            invalid.append("maxmemory must be set")
        if str(config.get("maxmemory-policy", "")).lower() != "noeviction":
            invalid.append("maxmemory-policy must be noeviction")
        if invalid:
            raise SessionStoreUnavailable("Cấu hình Redis không an toàn: " + ", ".join(invalid))

    @contextmanager
    def call_lock(self, call_id: str, timeout_s: float) -> Iterator[None]:
        self.check_ready()
        key = self._lock_key(call_id)
        token = secrets.token_hex(16)
        deadline = time.monotonic() + max(timeout_s, 0)
        while True:
            try:
                acquired = self._client.set(
                    key, token, nx=True, px=max(1, int(self._lock_lease_s * 1000))
                )
            except RedisError as exc:
                raise SessionStoreUnavailable("Không lấy được khóa Redis") from exc
            if acquired:
                break
            if time.monotonic() >= deadline:
                raise CallBusy(call_id)
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        self._lock_tokens()[key] = token
        body_error = False
        try:
            yield
        except BaseException:
            body_error = True
            raise
        finally:
            try:
                self._release_lock(key, token)
            except (RedisError, SessionStoreUnavailable) as exc:
                # A lost/expired lock makes the completed operation unsafe to replay.
                if not body_error:
                    raise SessionStoreUnavailable("Mất khóa Redis khi xử lý lượt") from exc
            finally:
                self._lock_tokens().pop(key, None)

    def _release_lock(self, key: str, token: str) -> None:
        while True:
            try:
                with self._client.pipeline() as pipe:
                    pipe.watch(key)
                    if pipe.get(key) != token:
                        raise SessionStoreUnavailable("Khóa Redis đã hết hạn hoặc đổi chủ")
                    pipe.multi()
                    pipe.delete(key)
                    pipe.execute()
                    return
            except WatchError:
                continue

    def get_session(self, call_id: str) -> Optional[SessionRecord]:
        state = self._load(call_id)
        if state is None:
            return None
        return SessionRecord(**state["session"])

    def create_session(self, record: SessionRecord) -> None:
        now = self._clock()
        state = {
            "schema": _STATE_SCHEMA,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "session": asdict(record),
            "turns": {},
            "commands": {},
        }
        if not self._save(record.call_id, state, only_if_absent=True):
            raise ValueError(f"Session {record.call_id} đã tồn tại")

    def get_turn(self, call_id: str, turn: int) -> Optional[TurnRecord]:
        state = self._load(call_id)
        if state is None:
            return None
        raw = state["turns"].get(str(turn))
        return self._turn_from_dict(raw) if raw else None

    def find_blocked_turn(self, call_id: str) -> Optional[int]:
        state = self._load(call_id)
        if state is None:
            return None
        blocked = [
            int(number)
            for number, turn in state["turns"].items()
            if turn["status"] == "RECONCILIATION_REQUIRED"
        ]
        return min(blocked) if blocked else None

    def reserve_turn(
        self, call_id: str, turn: int, input: dict[str, Any], received_at: datetime
    ) -> None:
        state = self._required(call_id)
        if state["session"].get("purged_reason"):
            raise ReconciliationRequired(call_id, turn)
        key = str(turn)
        if key in state["turns"]:
            raise ValueError(f"Lượt {call_id}/{turn} đã tồn tại")
        state["turns"][key] = asdict(TurnRecord(call_id, turn, input, received_at, "PROCESSING"))
        state["turns"][key]["received_at"] = received_at.isoformat()
        self._save(call_id, state)

    def complete_turn(
        self,
        call_id: str,
        turn: int,
        context: dict[str, Any],
        result: dict[str, Any],
        extraction: Optional[dict[str, Any]],
        ended: bool,
    ) -> None:
        state = self._required(call_id)
        session = SessionRecord(**state["session"])
        raw_turn = state["turns"].get(str(turn))
        record = self._turn_from_dict(raw_turn) if raw_turn else None
        if session.purged_reason:
            if session.purged_reason != "CLINIC_COMMITTED":
                raise ReconciliationRequired(call_id, turn)
            if (
                record is None
                or record.status != "PROCESSING"
                or (session.last_completed_turn != turn - 1 or not ended)
            ):
                raise ValueError("A successful Clinic write must close its processing turn")
            state["session"]["last_completed_turn"] = turn
            state["session"]["purged_reason"] = "ENDED"
            raw_turn.update(status="COMPLETED", result={})
            self._save(call_id, state, retired=True)
            return
        if record is None or record.status != "PROCESSING":
            raise ValueError(f"Lượt {call_id}/{turn} không ở trạng thái PROCESSING")
        if session.last_completed_turn != turn - 1:
            raise ValueError(f"Session {call_id} không chờ lượt {turn}")
        raw_turn.update(status="COMPLETED", result=result, extraction=extraction)
        state["session"].update(context=context, last_completed_turn=turn, ended=ended)
        state["updated_at"] = self._clock().isoformat()
        if ended:
            self._purge_state(state, "ENDED")
        self._save(call_id, state, retired=ended)

    def mark_reconciliation_required(self, call_id: str, turn: int, detail: str) -> None:
        state = self._load(call_id)
        if state is None:
            return
        raw = state["turns"].get(str(turn))
        if raw is not None and raw["status"] != "COMPLETED":
            raw.update(status="RECONCILIATION_REQUIRED", detail=detail)
        self._purge_state(state, "RECONCILIATION_REQUIRED")
        self._save(call_id, state, retired=True)

    def list_commands(self, call_id: str, turn: Optional[int] = None) -> list[CommandRecord]:
        state = self._load(call_id)
        if state is None:
            return []
        commands = [CommandRecord(**raw) for raw in state["commands"].values()]
        return sorted(
            (command for command in commands if turn is None or command.turn == turn),
            key=lambda command: command.idempotency_key,
        )

    def begin_command(self, command: CommandRecord) -> None:
        state = self._required(command.call_id)
        if state["session"].get("purged_reason"):
            raise ReconciliationRequired(command.call_id, command.turn)
        if str(command.turn) not in state["turns"]:
            raise KeyError(f"{command.call_id}/{command.turn}")
        existing_raw = state["commands"].get(command.idempotency_key)
        if existing_raw is None:
            state["commands"][command.idempotency_key] = asdict(
                replace(command, status="PENDING", attempts=1, result=None, error=None)
            )
            self._save(command.call_id, state)
            return
        existing = CommandRecord(**existing_raw)
        if not same_command(existing, command) or existing.status != "FAILED":
            raise ReconciliationRequired(
                command.call_id, command.turn, f"lệnh {command.idempotency_key} đã tồn tại"
            )
        existing_raw.update(
            status="PENDING",
            attempts=existing.attempts + 1,
            if_match=command.if_match,
            result=None,
            error=None,
        )
        self._save(command.call_id, state)

    def finish_command(
        self,
        call_id: str,
        idempotency_key: str,
        status: CommandStatus,
        result: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        state = self._required(call_id)
        raw = state["commands"].get(idempotency_key)
        if raw is None:
            raise KeyError(idempotency_key)
        if state["session"].get("purged_reason"):
            raise ReconciliationRequired(call_id, raw["turn"])
        raw.update(status=status, result=None, error=error if status == "FAILED" else None)
        if status in ("SUCCEEDED", "UNKNOWN"):
            reason = "CLINIC_COMMITTED" if status == "SUCCEEDED" else "RECONCILIATION_REQUIRED"
            self._purge_state(state, reason)
            self._save(call_id, state, retired=True)
        else:
            self._save(call_id, state)

    def expire_session(self, call_id: str) -> None:
        state = self._load(call_id)
        if state is None or state["session"].get("purged_reason"):
            return
        now = self._clock()
        created = datetime.fromisoformat(state["created_at"])
        updated = datetime.fromisoformat(state["updated_at"])
        commands = [CommandRecord(**raw) for raw in state["commands"].values()]
        uncertain = any(command.status in ("PENDING", "UNKNOWN") for command in commands)
        blocked = any(
            turn["status"] == "RECONCILIATION_REQUIRED" for turn in state["turns"].values()
        )
        committed = any(command.status == "SUCCEEDED" for command in commands)
        expired = (now - updated).total_seconds() >= self._retention.idle_seconds or (
            now - created
        ).total_seconds() >= self._retention.max_age_seconds
        if state["session"]["ended"] or blocked or committed or expired:
            reason = (
                "RECONCILIATION_REQUIRED"
                if uncertain or blocked
                else (
                    "ENDED"
                    if state["session"]["ended"]
                    else "CLINIC_COMMITTED"
                    if committed
                    else "EXPIRED"
                )
            )
            self._purge_state(state, reason)
            self._save(call_id, state, retired=True)

    def purge_expired(self) -> int:
        purged = 0
        try:
            keys = self._client.scan_iter(match=f"{self._prefix}:call:*")
            for key in keys:
                call_id = str(key).removeprefix(f"{self._prefix}:call:")
                try:
                    with self.call_lock(call_id, 0.01):
                        before = self.get_session(call_id)
                        self.expire_session(call_id)
                        after = self.get_session(call_id)
                        purged += bool(
                            before and not before.purged_reason and after and after.purged_reason
                        )
                except CallBusy:
                    continue
        except RedisError as exc:
            raise SessionStoreUnavailable("Không dọn được session Redis") from exc
        return purged

    def check_ready(self) -> None:
        if self._closed:
            raise SessionStoreUnavailable("Session store đã đóng")
        try:
            if not self._client.ping():
                raise SessionStoreUnavailable("Redis không phản hồi PING")
        except RedisError as exc:
            raise SessionStoreUnavailable("Redis không sẵn sàng") from exc

    def close(self) -> None:
        self._closed = True
        if self._close_client:
            self._client.close()

    def _load(self, call_id: str) -> Optional[dict[str, Any]]:
        try:
            raw = self._client.get(self._state_key(call_id))
        except RedisError as exc:
            raise SessionStoreUnavailable("Không đọc được session Redis") from exc
        if raw is None:
            return None
        try:
            state = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise SessionStoreUnavailable("Session Redis bị hỏng") from exc
        if not isinstance(state, dict) or state.get("schema") != _STATE_SCHEMA:
            raise SessionStoreUnavailable("Schema session Redis không được hỗ trợ")
        if not all(key in state for key in ("session", "turns", "commands")):
            raise SessionStoreUnavailable("Session Redis thiếu trường bắt buộc")
        return state

    def _required(self, call_id: str) -> dict[str, Any]:
        state = self._load(call_id)
        if state is None:
            raise KeyError(call_id)
        return state

    def _save(
        self,
        call_id: str,
        state: dict[str, Any],
        *,
        retired: bool = False,
        only_if_absent: bool = False,
    ) -> bool:
        try:
            encoded = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise SessionStoreUnavailable("Session chứa dữ liệu không tuần tự hóa được") from exc
        size = len(encoded.encode("utf-8"))
        if size > self._max_session_bytes:
            raise SessionStoreUnavailable(f"Session vượt giới hạn {self._max_session_bytes} byte")
        ttl = self._tombstone_ttl_s if retired else self._active_ttl(state)
        if ttl <= 0:
            self._purge_state(state, "EXPIRED")
            encoded = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
            ttl = self._tombstone_ttl_s
        state_key = self._state_key(call_id)
        lock_key = self._lock_key(call_id)
        token = self._lock_tokens().get(lock_key)
        try:
            if token is None:
                return bool(self._client.set(state_key, encoded, ex=ttl, nx=only_if_absent))
            while True:
                try:
                    with self._client.pipeline() as pipe:
                        pipe.watch(lock_key)
                        if pipe.get(lock_key) != token:
                            raise SessionStoreUnavailable("Mất khóa Redis trước khi ghi session")
                        pipe.multi()
                        pipe.set(state_key, encoded, ex=ttl, nx=only_if_absent)
                        [result] = pipe.execute()
                        return bool(result)
                except WatchError:
                    continue
        except RedisError as exc:
            raise SessionStoreUnavailable("Không ghi được session Redis") from exc

    def _active_ttl(self, state: dict[str, Any]) -> int:
        created = datetime.fromisoformat(state["created_at"])
        remaining = self._retention.max_age_seconds - int((self._clock() - created).total_seconds())
        return max(0, min(self._retention.idle_seconds, remaining))

    @staticmethod
    def _purge_state(state: dict[str, Any], reason: str) -> None:
        state["session"].update(
            start_config={}, opening={}, context={}, ended=True, purged_reason=reason
        )
        for turn in state["turns"].values():
            turn.update(
                input={},
                result={} if turn["status"] == "COMPLETED" else None,
                extraction=None,
                detail=None,
            )
        for command in state["commands"].values():
            command.update(endpoint="", payload={}, result=None, error=None)

    @staticmethod
    def _turn_from_dict(raw: dict[str, Any]) -> TurnRecord:
        values = dict(raw)
        values["received_at"] = datetime.fromisoformat(values["received_at"])
        return TurnRecord(**values)

    def _state_key(self, call_id: str) -> str:
        return f"{self._prefix}:call:{call_id}"

    def _lock_key(self, call_id: str) -> str:
        return f"{self._prefix}:lock:{call_id}"

    def _lock_tokens(self) -> dict[str, str]:
        tokens = getattr(self._held_locks, "tokens", None)
        if tokens is None:
            tokens = {}
            self._held_locks.tokens = tokens
        return tokens
