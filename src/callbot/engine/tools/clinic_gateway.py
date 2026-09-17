"""Tool layer: mọi lệnh đọc/ghi clinic mock đi qua đây để guardrail luôn được áp dụng.

- Mỗi write đọc lại version mới nhất làm If-Match (§4.2.3)
- Idempotency-Key cố định theo call_id + lượt + thao tác (+ slot): gửi lại không tạo bản ghi trùng
- Kiểm tra đồng nhất phiên (FSM) + SF-01 / SF-02 / SF-05 + bằng chứng xác nhận TRƯỚC khi gửi
- Lệnh được commit vào nhật ký trước khi gửi; kết quả không xác định -> `WriteOutcomeUnknown`,
  không gửi lại và không phát sinh lệnh thay thế (F-03)
"""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx

from callbot.engine.errors import (
    ClinicWriteRejected,
    SessionStoreUnavailable,
    SlotTaken,
    WriteOutcomeUnknown,
)
from callbot.engine.extraction.schema import to_local
from callbot.engine.journal import ClinicCommand, current_journal
from callbot.engine.policy import guardrails
from callbot.engine.session import fsm
from callbot.engine.session.context import CallContext
from callbot.engine.tools.ports import ClinicAPI
from callbot.engine.types import CancelReason, TransferReason, UnreachableReason

logger = logging.getLogger(__name__)

# Mock giới hạn `to - from` tối đa 14 ngày
SLOT_WINDOW_DAYS = 14


class ClinicGateway:
    def __init__(self, api: ClinicAPI, clinic_id: str) -> None:
        self._api = api
        self._clinic_id = clinic_id

    # --- Đọc -----------------------------------------------------------------

    def get_appointment(self, ctx: CallContext) -> dict[str, Any]:
        guardrails.assert_target_appointment(ctx, ctx.target_appointment_id)
        return self._api.get_appointment(ctx.target_appointment_id)

    def find_patients_by_phone(self, phone: str) -> list[dict[str, Any]]:
        payload = self._api.find_patient_by_phone(phone)
        if isinstance(payload, list):
            return payload
        return payload.get("data") or payload.get("patients") or payload.get("items") or []

    def list_open_slots(self, ctx: CallContext, now: datetime) -> list[dict[str, Any]]:
        """Nguồn slot hợp lệ duy nhất để đề xuất; thay toàn bộ `ctx.slots` (SF-02).

        `now` là thời điểm tiếp nhận lượt, để xử lý lại lượt đọc đúng cửa sổ thời gian cũ.
        """
        start = to_local(now).replace(microsecond=0)
        payload = self._api.get_slots(
            self._clinic_id,
            start.isoformat(),
            (start + timedelta(days=SLOT_WINDOW_DAYS)).isoformat(),
        )
        raw = (
            payload if isinstance(payload, list) else payload.get("data", payload.get("slots", []))
        )
        ctx.slots = [_normalize_slot(slot) for slot in raw]
        return list(ctx.slots)

    # --- Ghi -----------------------------------------------------------------

    def confirm(self, ctx: CallContext) -> dict[str, Any]:
        fsm.check_write(ctx, "CONFIRM")
        guardrails.assert_action_confirmed(ctx, "CONFIRM")
        appointment_id = self._target(ctx)
        return self._write(
            ctx,
            "confirm",
            f"/appointments/{appointment_id}/confirm",
            {},
            lambda version, key: self._api.confirm_appointment(appointment_id, version, key),
        )

    def cancel(self, ctx: CallContext, reason: CancelReason) -> dict[str, Any]:
        fsm.check_write(ctx, "CANCEL")
        guardrails.assert_action_confirmed(ctx, "CANCEL")
        appointment_id = self._target(ctx)
        return self._write(
            ctx,
            "cancel",
            f"/appointments/{appointment_id}/cancel",
            {"cancel_reason": reason, "confirmed": True},
            lambda version, key: self._api.cancel_appointment(
                appointment_id, reason, version, key, confirmed=True
            ),
        )

    def reschedule(self, ctx: CallContext, new_slot_id: str) -> dict[str, Any]:
        fsm.check_write(ctx, "RESCHEDULE", new_slot_id)
        guardrails.assert_slot_offered(ctx, new_slot_id)
        guardrails.assert_action_confirmed(ctx, "RESCHEDULE", new_slot_id)
        appointment_id = self._target(ctx)
        return self._write(
            ctx,
            f"reschedule:{new_slot_id}",
            f"/appointments/{appointment_id}/reschedule",
            {"new_slot_id": new_slot_id, "requested_by": "PATIENT"},
            lambda version, key: self._api.reschedule_appointment(
                appointment_id, new_slot_id, version, key
            ),
        )

    def book(self, ctx: CallContext, slot_id: str) -> dict[str, Any]:
        """§1.1.10: inbound, tạo đúng MỘT appointment trên slot đã đề xuất."""
        if ctx.call.direction != "inbound" or ctx.created_appointment_id is not None:
            raise guardrails.SevereFailureBlocked("SF-01", "Chỉ inbound mới được tạo 1 appointment")
        guardrails.assert_can_disclose(ctx)
        fsm.check_write(ctx, "BOOK", slot_id)
        guardrails.assert_slot_offered(ctx, slot_id)
        guardrails.assert_action_confirmed(ctx, "BOOK", slot_id)
        if ctx.patient_id is None:
            raise ValueError("Chưa xác định patient_id")
        patient_id = ctx.patient_id
        created = self._write(
            ctx,
            f"book:{slot_id}",
            "/appointments",
            {"patient_id": patient_id, "slot_id": slot_id},
            lambda _version, key: self._api.create_appointment(patient_id, slot_id, key),
            read_version=False,
        )
        ctx.created_appointment_id = created["appointment_id"]
        return created

    def transfer(self, ctx: CallContext, reason: TransferReason) -> dict[str, Any]:
        fsm.check_closing_write(ctx)
        appointment_id = self._target(ctx)
        return self._write(
            ctx,
            "transfer",
            f"/appointments/{appointment_id}/transfer",
            {"transfer_reason": reason},
            lambda version, key: self._api.transfer_appointment(
                appointment_id, reason, version, key
            ),
        )

    def mark_unreachable(self, ctx: CallContext, reason: UnreachableReason) -> dict[str, Any]:
        fsm.check_closing_write(ctx)
        if ctx.call.direction != "outbound":
            raise guardrails.SevereFailureBlocked("SF-01", "Inbound không ghi UNREACHABLE")
        appointment_id = self._target(ctx)
        return self._write(
            ctx,
            "unreachable",
            f"/appointments/{appointment_id}/unreachable",
            {"unreachable_reason": reason},
            lambda version, key: self._api.mark_unreachable(appointment_id, reason, version, key),
        )

    # --- Thực thi lệnh ghi qua nhật ký --------------------------------------------

    def _write(
        self,
        ctx: CallContext,
        operation: str,
        endpoint: str,
        payload: dict[str, Any],
        send: Callable[[Optional[int], str], dict[str, Any]],
        read_version: bool = True,
    ) -> dict[str, Any]:
        journal = current_journal()
        key = f"{ctx.call_id}:{ctx.turn}:{operation}"
        # VERSION_CONFLICT: đọc lại version, gửi lại MỘT lần với cùng Idempotency-Key
        for attempt in (1, 2):
            version = self._current_version(ctx) if read_version else None
            command = ClinicCommand(operation.split(":")[0], endpoint, payload, version, key)
            # Không lưu được nhật ký -> SessionStoreUnavailable, lệnh không được gửi
            journal.begin(command)
            try:
                result = send(version, key)
            except httpx.HTTPStatusError as exc:
                status, code = exc.response.status_code, _error_code(exc.response)
                if status >= 500:
                    raise self._unknown(journal, command, f"HTTP {status} {code}") from exc
                journal.failed(command, f"HTTP {status} {code}")
                if code == "VERSION_CONFLICT" and attempt == 1:
                    continue
                if code == "SLOT_TAKEN":
                    raise SlotTaken(status, code) from exc
                raise ClinicWriteRejected(status, code) from exc
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                # Chưa mở được kết nối: request chắc chắn chưa tới Clinic
                journal.failed(command, type(exc).__name__)
                raise ClinicWriteRejected(None, type(exc).__name__) from exc
            except Exception as exc:
                # Timeout đọc, mất kết nối giữa chừng, lỗi lạ: không biết Clinic đã áp dụng chưa
                raise self._unknown(journal, command, repr(exc)) from exc
            journal.succeeded(command, result if isinstance(result, dict) else {"result": result})
            return result
        raise AssertionError("unreachable")

    @staticmethod
    def _unknown(journal: Any, command: ClinicCommand, error: str) -> WriteOutcomeUnknown:
        try:
            journal.unknown(command, error)
        except SessionStoreUnavailable:
            # Lệnh vẫn PENDING trong nhật ký — lần xử lý sau cũng bị chặn đối soát
            logger.exception("Không ghi được trạng thái UNKNOWN cho %s", command.idempotency_key)
        return WriteOutcomeUnknown(f"{command.idempotency_key}: {error}")

    def _current_version(self, ctx: CallContext) -> int:
        current = self._api.get_appointment(self._target(ctx))
        return int(current["version"])

    @staticmethod
    def _target(ctx: CallContext) -> str:
        appointment_id = ctx.target_appointment_id
        guardrails.assert_target_appointment(ctx, appointment_id)
        assert appointment_id is not None
        return appointment_id


def _normalize_slot(slot: dict[str, Any]) -> dict[str, Any]:
    """Mock trả `start_time`; engine và IE đọc `starts_at`."""
    normalized = dict(slot)
    if "starts_at" not in normalized and "start_time" in normalized:
        normalized["starts_at"] = normalized["start_time"]
    return normalized


def _error_code(response: httpx.Response) -> Optional[str]:
    try:
        body = response.json()
    except ValueError:
        return None
    error = body.get("error") if isinstance(body, dict) else None
    return error.get("code") if isinstance(error, dict) else None
