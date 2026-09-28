"""Session Manager: mở phiên, thứ tự lượt, replay, khóa theo call_id, state machine (F-03).

Một lượt đi qua các bước:

1. Khóa `call_id` (chờ tối đa `lock_timeout_s`, quá thì `CallBusy`).
2. Lượt đã có bản ghi: COMPLETED + cùng đầu vào -> trả nguyên kết quả cũ, không chạy lại gì.
   PROCESSING (worker trước chết / request trước lỗi) -> xử lý tiếp nếu chưa có lệnh ghi nào
   có thể đã tới Clinic; ngược lại chặn đối soát.
3. Lượt mới: phải đúng `last_completed_turn + 1`; đặt chỗ lượt (commit) với thời điểm tiếp nhận.
4. Chạy xử lý với nhật ký lệnh gắn vào lượt; commit context + history + kết quả trong một transaction.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from callbot.engine.diagnostics import TurnDiagnostics, build_diagnostics
from callbot.engine.errors import (
    CallConflict,
    CallEnded,
    ReconciliationRequired,
    SessionNotFound,
    TurnConflict,
    TurnOutOfOrder,
    WriteOutcomeUnknown,
)
from callbot.engine.extraction.schema import VN_TZ
from callbot.engine.journal import ClinicCommand, bind_journal
from callbot.engine.session.context import CallContext
from callbot.engine.session.fsm import check_invariants, ensure_transition
from callbot.engine.session.store import CommandRecord, SessionRecord, SessionStore
from callbot.engine.types import (
    BotAction,
    CallerInput,
    CallStart,
    CallState,
    Outcome,
    TransferReason,
    UnreachableReason,
)
from callbot.tracing import trace_event

logger = logging.getLogger(__name__)

LOCK_TIMEOUT_S = 5.0


def now_vn() -> datetime:
    return datetime.now(VN_TZ)


@dataclass(frozen=True)
class TurnOutcome:
    action: BotAction
    extraction: Optional[dict[str, Any]] = None
    # Không lưu vào session store; lượt replay dựng lại từ extraction + action
    diagnostics: Optional[TurnDiagnostics] = None


@dataclass(frozen=True)
class TurnRun:
    action: BotAction
    replayed: bool
    extraction: Optional[dict[str, Any]] = None
    diagnostics: Optional[TurnDiagnostics] = None


TurnProcessor = Callable[[CallContext, CallerInput, datetime], TurnOutcome]


class SessionManager:
    def __init__(
        self,
        store: SessionStore,
        lock_timeout_s: float = LOCK_TIMEOUT_S,
        clock: Callable[[], datetime] = now_vn,
    ) -> None:
        self._store = store
        self._lock_timeout_s = lock_timeout_s
        self._clock = clock

    @property
    def store(self) -> SessionStore:
        return self._store

    # --- Mở phiên ----------------------------------------------------------------

    def open(
        self, call: CallStart, opening: Callable[[CallContext], BotAction]
    ) -> tuple[BotAction, bool]:
        """Trả (phản hồi mở phiên, có phải replay không). Không bao giờ reset context đã có."""
        config = call.to_dict()
        with self._store.call_lock(call.call_id, self._lock_timeout_s):
            self._store.expire_session(call.call_id)
            existing = self._store.get_session(call.call_id)
            if existing is not None:
                self._check_retired(existing)
                if existing.start_config != config:
                    raise CallConflict(call.call_id)
                return BotAction.from_dict(existing.opening), True

            ctx = CallContext(call=call, opened_at=self._clock())
            action = opening(ctx)
            ctx.record("bot", action.utterance)
            self.transition(ctx, action.state)
            self._store.create_session(
                SessionRecord(
                    call_id=call.call_id,
                    start_config=config,
                    opening=action.to_dict(),
                    context=ctx.to_dict(),
                )
            )
            return action, False

    # --- Một lượt ------------------------------------------------------------------

    def run_turn(self, call_id: str, caller: CallerInput, process: TurnProcessor) -> TurnRun:
        with self._store.call_lock(call_id, self._lock_timeout_s):
            self._store.expire_session(call_id)
            session = self._store.get_session(call_id)
            if session is None:
                raise SessionNotFound(call_id)
            self._check_retired(session)

            received_at = self._admit(session, caller)
            if isinstance(received_at, TurnRun):
                trace_event(
                    "session.replayed",
                    replayed=True,
                    terminal=received_at.action.ended,
                    storage_status="COMPLETED",
                    turn_ordering="REPLAY",
                )
                return received_at

            trace_event(
                "session.admitted",
                replayed=False,
                terminal=False,
                storage_status="PROCESSING",
                turn_ordering="ACCEPTED",
            )

            ctx = CallContext.from_dict(session.context)
            journal = StoreCommandJournal(self._store, call_id, caller.turn)
            try:
                with bind_journal(journal):
                    outcome = process(ctx, caller, received_at)
            except WriteOutcomeUnknown as exc:
                self._block(call_id, caller.turn, str(exc))
                blocked = ReconciliationRequired(call_id, caller.turn, str(exc))
                blocked.diagnostics, blocked.extraction = exc.diagnostics, exc.extraction
                raise blocked from exc
            except ReconciliationRequired as exc:
                # Nhật ký phát hiện khóa lệnh đã tồn tại với kết quả chưa rõ
                self._block(call_id, caller.turn, str(exc))
                raise

            self._store.complete_turn(
                call_id,
                caller.turn,
                ctx.to_dict(),
                outcome.action.to_dict(),
                outcome.extraction,
                ended=ctx.ended,
            )
            trace_event(
                "session.committed",
                replayed=False,
                terminal=ctx.ended,
                storage_status="COMPLETED",
                turn_ordering="COMMITTED",
            )
            return TurnRun(
                outcome.action,
                replayed=False,
                extraction=outcome.extraction,
                diagnostics=outcome.diagnostics,
            )

    def _check_retired(self, session: SessionRecord) -> None:
        if session.purged_reason in ("RECONCILIATION_REQUIRED", "CLINIC_COMMITTED"):
            commands = self._store.list_commands(session.call_id)
            turn = max((c.turn for c in commands), default=session.last_completed_turn + 1)
            self._block(session.call_id, turn, "Customer content removed; reconcile in Clinic")
            raise ReconciliationRequired(session.call_id, turn)
        if session.purged_reason or session.ended:
            raise CallEnded(session.call_id)

    def _admit(self, session: SessionRecord, caller: CallerInput) -> "datetime | TurnRun":
        call_id, turn = session.call_id, caller.turn
        fingerprint = caller.fingerprint()
        existing = self._store.get_turn(call_id, turn)

        if existing is not None:
            if existing.input != fingerprint:
                raise TurnConflict(f"{call_id}: lượt {turn} đã nhận với đầu vào khác")
            if existing.status == "COMPLETED":
                assert existing.result is not None
                action = BotAction.from_dict(existing.result)
                return TurnRun(
                    action,
                    replayed=True,
                    extraction=existing.extraction,
                    diagnostics=build_diagnostics(
                        existing.extraction, transfer_reason=action.transfer_reason
                    ),
                )
            if existing.status == "RECONCILIATION_REQUIRED":
                raise ReconciliationRequired(call_id, turn, existing.detail or "")
            # PROCESSING còn lại: chỉ xử lý tiếp khi chắc chắn chưa lệnh ghi nào tới Clinic
            unsettled = [
                command
                for command in self._store.list_commands(call_id, turn)
                if command.status != "FAILED"
            ]
            if unsettled:
                detail = "lệnh chưa rõ kết quả: " + ", ".join(
                    f"{c.idempotency_key} ({c.status})" for c in unsettled
                )
                self._block(call_id, turn, detail)
                raise ReconciliationRequired(call_id, turn, detail)
            # Dùng lại thời điểm tiếp nhận cũ: "ngày mai" không đổi nghĩa khi xử lý lại
            return existing.received_at

        blocked = self._store.find_blocked_turn(call_id)
        if blocked is not None:
            raise ReconciliationRequired(call_id, blocked)
        if session.ended:
            raise CallEnded(call_id)
        expected = session.last_completed_turn + 1
        if turn != expected:
            raise TurnOutOfOrder(call_id, turn, expected)
        received_at = self._clock()
        self._store.reserve_turn(call_id, turn, fingerprint, received_at)
        return received_at

    def _block(self, call_id: str, turn: int, detail: str) -> None:
        try:
            self._store.mark_reconciliation_required(call_id, turn, detail)
        except Exception:
            # Không ghi được cờ chặn: lượt vẫn PROCESSING kèm lệnh chưa rõ, lần sau vẫn bị chặn
            logger.error("Không đánh dấu được lượt %s/%s cần đối soát", call_id, turn)

    # --- State machine -----------------------------------------------------------------

    @staticmethod
    def transition(ctx: CallContext, target: CallState) -> None:
        before = ctx.state
        try:
            ensure_transition(ctx.state, target)
            check_invariants(ctx, target)
        except Exception:
            trace_event(
                "fsm.transition",
                state_before=before,
                state_after=target,
                status="ERROR",
                error_type="INTERNAL",
                error_code="FSM_ILLEGAL_TRANSITION",
            )
            raise
        ctx.state = target
        trace_event("fsm.transition", state_before=before, state_after=target, status="OK")

    @staticmethod
    def close(
        ctx: CallContext,
        outcome: Outcome,
        transfer_reason: Optional[TransferReason] = None,
        unreachable_reason: Optional[UnreachableReason] = None,
    ) -> None:
        before = ctx.state
        try:
            ensure_transition(ctx.state, "ENDED")
        except Exception:
            trace_event(
                "fsm.transition",
                state_before=before,
                state_after="ENDED",
                outcome=outcome,
                status="ERROR",
                error_type="INTERNAL",
                error_code="FSM_ILLEGAL_TRANSITION",
            )
            raise
        ctx.outcome = outcome
        ctx.transfer_reason = transfer_reason
        ctx.unreachable_reason = unreachable_reason
        try:
            check_invariants(ctx, "ENDED")
        except Exception:
            trace_event(
                "fsm.transition",
                state_before=before,
                state_after="ENDED",
                outcome=outcome,
                status="ERROR",
                error_type="INTERNAL",
                error_code="FSM_ILLEGAL_TRANSITION",
            )
            raise
        ctx.state = "ENDED"
        trace_event(
            "fsm.transition", state_before=before, state_after="ENDED", outcome=outcome, status="OK"
        )


class StoreCommandJournal:
    """`journal.CommandJournal` trên session store, gắn với một lượt."""

    def __init__(self, store: SessionStore, call_id: str, turn: int) -> None:
        self._store = store
        self._call_id = call_id
        self._turn = turn

    def begin(self, command: ClinicCommand) -> None:
        self._store.begin_command(
            CommandRecord(
                idempotency_key=command.idempotency_key,
                call_id=self._call_id,
                turn=self._turn,
                operation=command.operation,
                endpoint=command.endpoint,
                payload=command.payload,
                if_match=command.if_match,
            )
        )

    def succeeded(self, command: ClinicCommand, result: dict[str, Any]) -> None:
        self._store.finish_command(
            self._call_id, command.idempotency_key, "SUCCEEDED", result=result
        )

    def failed(self, command: ClinicCommand, error: str) -> None:
        self._store.finish_command(self._call_id, command.idempotency_key, "FAILED", error=error)

    def unknown(self, command: ClinicCommand, error: str) -> None:
        self._store.finish_command(self._call_id, command.idempotency_key, "UNKNOWN", error=error)
