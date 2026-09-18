"""Clinic Gateway — "kiểm soát đọc / ghi và retry" (kiến trúc); mọi lệnh tới clinic mock đi qua đây.

Đọc: đi hết mọi trang, chuẩn hóa về khóa canonical (`tools/normalize.py`), lỗi là `ClinicAPIError`.
Ghi:
- Kiểm tra đồng nhất phiên (FSM) + SF-01 / SF-02 / SF-05 + bằng chứng xác nhận TRƯỚC khi gửi
- Mỗi write đọc lại version mới nhất làm If-Match (§4.2.3)
- Idempotency-Key cố định theo call_id + lượt + thao tác (+ slot): gửi lại không tạo bản ghi trùng
- Lệnh được commit vào nhật ký trước khi gửi; kết quả về ba lớp (F-05 §5.4):
  thành công có bằng chứng | từ chối xác định `ClinicWriteRejected` | chưa rõ `WriteOutcomeUnknown`
- VERSION_CONFLICT: đọc lại version, gửi lại MỘT lần cùng key. Retry cho lỗi tạm thời khác: T-12.
"""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Optional

from callbot.engine.errors import (
    ClinicAPIError,
    ClinicWriteRejected,
    SessionStoreUnavailable,
    SlotTaken,
    WriteOutcomeUnknown,
)
from callbot.engine.journal import ClinicCommand, current_journal
from callbot.engine.policy import guardrails
from callbot.engine.session import fsm
from callbot.engine.session.context import CallContext
from callbot.engine.tools.normalize import (
    iso_local,
    normalize_appointment,
    normalize_patient_candidate,
    normalize_slot,
)
from callbot.engine.tools.ports import PAGE_LIMIT, ClinicAPI, Page
from callbot.engine.types import CancelReason, TransferReason, UnreachableReason

logger = logging.getLogger(__name__)

# Mock giới hạn `to - from` tối đa 14 ngày
SLOT_WINDOW_DAYS = 14
# Trần số trang một lần đọc: 20 × 100 bản ghi — vượt là mock trả cursor hỏng, không phải dữ liệu thật
MAX_PAGES = 20


class ClinicGateway:
    def __init__(self, api: ClinicAPI, clinic_id: str) -> None:
        self._api = api
        self._clinic_id = clinic_id

    # --- Đọc -----------------------------------------------------------------

    def get_appointment(self, ctx: CallContext) -> dict[str, Any]:
        """Appointment của cuộc gọi (SF-01). Đọc được ngay lượt 0 — SF-03 cấm tiết lộ, không cấm đọc."""
        guardrails.assert_target_appointment(ctx, ctx.target_appointment_id)
        assert ctx.target_appointment_id is not None
        return normalize_appointment(self._api.get_appointment(ctx.target_appointment_id))

    def find_patients_by_phone(self, phone: str) -> list[dict[str, Any]]:
        """Ứng viên inbound theo số đã chuẩn hóa (Verifier lo, T-01) — mọi trang, mỗi phần tử
        {patient_id, full_name, dob, verifiable}. Chỉ là tra cứu, không phải bằng chứng danh tính (§1.1.9)."""
        rows = self._all_pages(
            lambda cursor: self._api.find_patient_by_phone(phone, cursor=cursor, limit=PAGE_LIMIT)
        )
        return [normalize_patient_candidate(row) for row in rows]

    def list_open_slots(self, ctx: CallContext, now: datetime) -> list[dict[str, Any]]:
        """Nguồn slot hợp lệ duy nhất để đề xuất; thay toàn bộ `ctx.slots` (SF-02).

        `now` là thời điểm tiếp nhận lượt, để xử lý lại lượt đọc đúng cửa sổ thời gian cũ.
        """
        start = now
        from_, to = iso_local(start), iso_local(start + timedelta(days=SLOT_WINDOW_DAYS))
        rows = self._all_pages(
            lambda cursor: self._api.get_slots(
                self._clinic_id, from_, to, cursor=cursor, limit=PAGE_LIMIT
            )
        )
        ctx.slots = [normalize_slot(row) for row in rows]
        return list(ctx.slots)

    @staticmethod
    def _all_pages(fetch: Callable[[Optional[str]], Page]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        cursor: Optional[str] = None
        for _ in range(MAX_PAGES):
            page = fetch(cursor)
            rows.extend(page["data"])
            if not page["has_more"] or not page["next_cursor"]:
                return rows
            cursor = page["next_cursor"]
        raise ClinicAPIError(
            None, "PAGINATION_OVERFLOW", f"Quá {MAX_PAGES} trang, cursor có thể hỏng"
        )

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

    def transfer(self, ctx: CallContext, reason: TransferReason) -> Optional[dict[str, Any]]:
        """Outbound: ghi TRANSFERRED lên appointment của cuộc gọi.

        Inbound chưa tạo lịch: không có gì để ghi (rev 1.1 §2.1) — trả None, không gửi request.
        Gateway tự quyết theo hướng gọi để Dialogue gọi vô điều kiện (luồng "Chuyển nhân viên — không ghi Mock").
        """
        fsm.check_closing_write(ctx)
        if ctx.call.direction == "inbound" and ctx.created_appointment_id is None:
            logger.info(
                "%s: inbound chưa tạo lịch, chuyển máy %s không ghi Mock", ctx.call_id, reason
            )
            return None
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
            try:
                version = self._current_version(ctx) if read_version else None
            except ClinicAPIError as exc:
                # Chưa gửi lệnh ghi nào: từ chối xác định, có thể thử lại nếu lỗi tạm thời
                raise ClinicWriteRejected(exc.status, exc.code, retryable=exc.retryable) from exc
            command = ClinicCommand(operation.split(":")[0], endpoint, payload, version, key)
            # Không lưu được nhật ký -> SessionStoreUnavailable, lệnh không được gửi
            journal.begin(command)
            try:
                result = send(version, key)
            except ClinicAPIError as exc:
                if not exc.outcome_known:
                    raise self._unknown(journal, command, f"{exc.code} {exc.message}") from exc
                journal.failed(command, f"HTTP {exc.status} {exc.code}")
                if exc.code == "VERSION_CONFLICT" and attempt == 1:
                    continue
                if exc.code == "SLOT_TAKEN":
                    raise SlotTaken(exc.status, exc.code) from exc
                raise ClinicWriteRejected(exc.status, exc.code, retryable=exc.retryable) from exc
            except Exception as exc:
                # Lỗi ngoài hợp đồng cổng (bug, ngoại lệ transport lạ): không biết Clinic đã áp dụng chưa
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
            logger.error("Không ghi được trạng thái UNKNOWN cho %s", command.idempotency_key)
        return WriteOutcomeUnknown(f"{command.idempotency_key}: {error}")

    def _current_version(self, ctx: CallContext) -> int:
        return self.get_appointment(ctx)["version"]

    @staticmethod
    def _target(ctx: CallContext) -> str:
        appointment_id = ctx.target_appointment_id
        guardrails.assert_target_appointment(ctx, appointment_id)
        assert appointment_id is not None
        return appointment_id
