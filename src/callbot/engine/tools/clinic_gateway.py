"""Clinic Gateway — "kiểm soát đọc / ghi và retry" (kiến trúc); mọi lệnh tới clinic mock đi qua đây.

Đọc: đi hết mọi trang, chuẩn hóa về khóa canonical (`tools/normalize.py`), lỗi là `ClinicAPIError`.
Ghi:
- Kiểm tra đồng nhất phiên (FSM) + SF-01 / SF-02 / SF-05 + bằng chứng xác nhận TRƯỚC khi gửi
- Mỗi write đọc lại version mới nhất làm If-Match (§4.2.3)
- Idempotency-Key cố định theo call_id + lượt + thao tác (+ slot): gửi lại không tạo bản ghi trùng
- Lệnh được commit vào nhật ký trước khi gửi; kết quả về ba lớp (F-05 §5.4):
  thành công có bằng chứng | từ chối xác định `ClinicWriteRejected` | chưa rõ `WriteOutcomeUnknown`
- VERSION_CONFLICT: đọc lại version, gửi lại MỘT lần cùng key (§4.2.5).
- Phục hồi lỗi ghi (T-12), giới hạn `WRITE_MAX_SENDS` lần gửi trong `WRITE_BUDGET_S`:
  chưa rõ (timeout, 5xx) → gửi lại Y HỆT, cùng key và cùng If-Match, để mock replay phản hồi cũ;
  lỗi tạm thời chắc chắn chưa ghi (429, không kết nối được) → chờ ngắn rồi gửi lại cùng key.
- Thành công chỉ khi body có đúng trạng thái đích; 2xx mà trạng thái sai là chưa rõ (T-12 D-2).
"""

import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Optional

from callbot.engine.errors import (
    AppointmentNotActionable,
    ClinicAPIError,
    ClinicInvalidResponse,
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
from callbot.engine.tools.telemetry import ApiCallRecord, collect_api_calls
from callbot.engine.types import CancelReason, TransferReason, UnreachableReason
from callbot.tracing import Tracer, current_span, null_tracer

logger = logging.getLogger(__name__)

# Mock giới hạn `to - from` tối đa 14 ngày
SLOT_WINDOW_DAYS = 14
# Policy kỹ thuật nội bộ: tìm tuần tự tối đa 5 cửa sổ (khoảng 70 ngày), không phải yêu cầu
# của Product Contract. Giới hạn hữu hạn này tránh quét Clinic API vô hạn trong một lượt.
SLOT_SEARCH_MAX_WINDOWS = 5
# Trần số trang một lần đọc: 20 × 100 bản ghi — vượt là mock trả cursor hỏng, không phải dữ liệu thật
MAX_PAGES = 20
ACTIONABLE_APPOINTMENT_STATUSES = frozenset({"SCHEDULED", "BOOKED", "CONFIRMED"})

# T-12: một thao tác ghi (kể cả đọc version) gửi tối đa 3 lần và dừng thử lại khi còn dưới 1 giây
# của ngân sách 4 giây — phần còn lại của 8 giây/lượt dành cho ASR, IE và TTS.
WRITE_MAX_SENDS = 3
WRITE_BUDGET_S = 4.0
WRITE_MIN_ATTEMPT_S = 1.0
# Chờ trước lần gửi thứ 2, thứ 3 khi lỗi tạm thời
WRITE_BACKOFF_S = (0.2, 0.5)

_CLINIC_API_OPERATIONS = {
    "clinic.find_patient_by_phone": "find_patient_by_phone",
    "clinic.get_appointment": "get_appointment",
    "clinic.get_slots": "get_slots",
    "clinic.create_appointment": "create_appointment",
    "clinic.confirm_appointment": "confirm_appointment",
    "clinic.cancel_appointment": "cancel_appointment",
    "clinic.reschedule_appointment": "reschedule_appointment",
    "clinic.transfer_appointment": "transfer_appointment",
    "clinic.mark_unreachable": "mark_unreachable",
}


def _clinic_error_code(record: ApiCallRecord) -> str | None:
    if record.code == "VERSION_CONFLICT":
        return "CLINIC_VERSION_CONFLICT"
    if record.code and "TIMEOUT" in record.code:
        return "CLINIC_TIMEOUT"
    if record.code and "CONNECT" in record.code:
        return "CLINIC_CONNECT_ERROR"
    if record.outcome != "ok":
        return "CLINIC_REJECTED"
    return None


def _clinic_result_code(record: ApiCallRecord) -> str:
    return _clinic_error_code(record) or "CLINIC_OK"


def traced_clinic(
    operation: str, endpoint_template: str, http_method: str, *, idempotency_used: bool = False
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Trace one logical gateway operation, including its existing retry loop."""

    def decorate(function: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(function)
        def wrapper(self: "ClinicGateway", *args: Any, **kwargs: Any) -> Any:
            active = current_span()
            if active is not None and active.component == "CLINIC":
                return function(self, *args, **kwargs)
            if active is not None:
                active.increment_ancestor_counter("CORE", "clinic_call_count")
            with self._tracer.span(component="CLINIC", operation=operation) as span:
                with collect_api_calls() as records:
                    try:
                        return function(self, *args, **kwargs)
                    finally:
                        try:
                            expected = _CLINIC_API_OPERATIONS[operation]
                            attempts = [
                                record for record in records if record.operation == expected
                            ]
                            version_conflict = any(
                                record.code == "VERSION_CONFLICT" for record in attempts
                            )
                            last = attempts[-1] if attempts else None
                            span.enrich(
                                endpoint_template=endpoint_template,
                                http_method=http_method,
                                http_status=last.status if last else None,
                                latency_ms=sum(record.latency_ms for record in records),
                                attempt_count=len(attempts),
                                version_conflict=version_conflict,
                                idempotency_used=idempotency_used and bool(attempts),
                                result_code=_clinic_result_code(last) if last else None,
                            )
                            for number, record in enumerate(attempts, start=1):
                                span.event(
                                    "clinic.attempt",
                                    attempt=number,
                                    http_status=record.status,
                                    latency_ms=record.latency_ms,
                                    error_code=_clinic_error_code(record),
                                )
                        except Exception:
                            logger.warning("TRACE_CLINIC_METADATA_REJECTED")

        return wrapper

    return decorate


class ClinicGateway:
    def __init__(
        self,
        api: ClinicAPI,
        clinic_id: str,
        tracer: Tracer | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._api = api
        self._clinic_id = clinic_id
        self._tracer = tracer if isinstance(tracer, Tracer) else null_tracer()
        # Điểm thay thế trong test: không chờ thật, đồng hồ giả để thử hết ngân sách
        self._sleep = sleep
        self._clock = clock

    # --- Đọc -----------------------------------------------------------------

    @traced_clinic("clinic.get_appointment", "/appointments/{id}", "GET")
    def get_appointment(self, ctx: CallContext) -> dict[str, Any]:
        """Appointment của cuộc gọi (SF-01). Đọc được ngay lượt 0 — SF-03 cấm tiết lộ, không cấm đọc."""
        guardrails.assert_target_appointment(ctx, ctx.target_appointment_id)
        assert ctx.target_appointment_id is not None
        appointment = normalize_appointment(self._api.get_appointment(ctx.target_appointment_id))
        if appointment["appointment_id"] != ctx.target_appointment_id:
            raise ClinicInvalidResponse("BAD_RESPONSE")
        return appointment

    def get_actionable_appointment(
        self,
        ctx: CallContext,
        allowed_statuses: frozenset[str] = ACTIONABLE_APPOINTMENT_STATUSES,
    ) -> dict[str, Any]:
        """Đọc lịch và chặn fail-closed nếu lifecycle không còn cho phép thao tác."""
        appointment = self.get_appointment(ctx)
        if appointment["status"] not in allowed_statuses:
            raise AppointmentNotActionable()
        return appointment

    @traced_clinic("clinic.find_patient_by_phone", "/patients", "GET")
    def find_patients_by_phone(self, phone: str) -> list[dict[str, Any]]:
        """Ứng viên inbound theo số đã chuẩn hóa (Verifier lo, T-01) — mọi trang, mỗi phần tử
        {patient_id, full_name, dob, verifiable}. Chỉ là tra cứu, không phải bằng chứng danh tính (§1.1.9)."""
        rows = self._all_pages(
            lambda cursor: self._api.find_patient_by_phone(phone, cursor=cursor, limit=PAGE_LIMIT)
        )
        return [normalize_patient_candidate(row) for row in rows]

    @traced_clinic("clinic.get_slots", "/slots", "GET")
    def list_open_slots(self, ctx: CallContext, now: datetime) -> list[dict[str, Any]]:
        """Nguồn slot hợp lệ duy nhất để đề xuất; thay toàn bộ `ctx.slots` (SF-02).

        `now` là thời điểm tiếp nhận lượt, để xử lý lại lượt đọc đúng cửa sổ thời gian cũ.
        """
        start = now
        for _ in range(SLOT_SEARCH_MAX_WINDOWS):
            end = start + timedelta(days=SLOT_WINDOW_DAYS)
            from_, to = iso_local(start), iso_local(end)
            rows = self._all_pages(
                lambda cursor, from_=from_, to=to: self._api.get_slots(
                    self._clinic_id, from_, to, cursor=cursor, limit=PAGE_LIMIT
                )
            )
            if rows:
                # Các cửa sổ nối liền tại biên; dedupe bảo vệ khỏi bản ghi lặp do semantics
                # biên hoặc pagination mà không làm thay đổi thứ tự ưu tiên của Clinic.
                normalized = [normalize_slot(row) for row in rows]
                ctx.slots = list({slot["slot_id"]: slot for slot in normalized}.values())
                return list(ctx.slots)
            start = end

        ctx.slots = []
        return []

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

    @traced_clinic(
        "clinic.confirm_appointment",
        "/appointments/{id}/confirm",
        "POST",
        idempotency_used=True,
    )
    def confirm(self, ctx: CallContext) -> dict[str, Any]:
        fsm.check_write(ctx, "CONFIRM")
        guardrails.assert_action_confirmed(ctx, "CONFIRM")
        appointment_id = self._target(ctx)
        written = self._write(
            ctx,
            "confirm",
            f"/appointments/{appointment_id}/confirm",
            {},
            lambda version, key: self._api.confirm_appointment(appointment_id, version, key),
        )
        return self._require_written(ctx, "confirm", written, "CONFIRMED")

    @traced_clinic(
        "clinic.cancel_appointment",
        "/appointments/{id}/cancel",
        "POST",
        idempotency_used=True,
    )
    def cancel(self, ctx: CallContext, reason: CancelReason) -> dict[str, Any]:
        fsm.check_write(ctx, "CANCEL")
        guardrails.assert_action_confirmed(ctx, "CANCEL")
        appointment_id = self._target(ctx)
        written = self._write(
            ctx,
            "cancel",
            f"/appointments/{appointment_id}/cancel",
            {"cancel_reason": reason, "confirmed": True},
            lambda version, key: self._api.cancel_appointment(
                appointment_id, reason, version, key, confirmed=True
            ),
        )
        return self._require_written(ctx, "cancel", written, "CANCELLED")

    @traced_clinic(
        "clinic.reschedule_appointment",
        "/appointments/{id}/reschedule",
        "POST",
        idempotency_used=True,
    )
    def reschedule(self, ctx: CallContext, new_slot_id: str) -> dict[str, Any]:
        fsm.check_write(ctx, "RESCHEDULE", new_slot_id)
        guardrails.assert_slot_offered(ctx, new_slot_id)
        guardrails.assert_action_confirmed(ctx, "RESCHEDULE", new_slot_id)
        appointment_id = self._target(ctx)
        written = self._write(
            ctx,
            f"reschedule:{new_slot_id}",
            f"/appointments/{appointment_id}/reschedule",
            {"new_slot_id": new_slot_id, "requested_by": "PATIENT"},
            lambda version, key: self._api.reschedule_appointment(
                appointment_id, new_slot_id, version, key
            ),
        )
        # Listing 4: slot mới phải đúng slot người gọi đã chọn và xác nhận
        return self._require_written(
            ctx, "reschedule", written, "RESCHEDULED", new_slot_id=new_slot_id
        )

    @traced_clinic("clinic.create_appointment", "/appointments", "POST", idempotency_used=True)
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
        appointment_id = created.get("appointment_id")
        status = created.get("status")
        if not appointment_id or status != "BOOKED":
            raise WriteOutcomeUnknown(
                f"{ctx.call_id}: book trả status {status}, appointment_id {appointment_id}"
            )
        ctx.created_appointment_id = appointment_id
        return created

    @traced_clinic(
        "clinic.transfer_appointment",
        "/appointments/{id}/transfer",
        "POST",
        idempotency_used=True,
    )
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
        written = self._write(
            ctx,
            "transfer",
            f"/appointments/{appointment_id}/transfer",
            {"transfer_reason": reason},
            lambda version, key: self._api.transfer_appointment(
                appointment_id, reason, version, key
            ),
        )
        return self._require_written(ctx, "transfer", written, "TRANSFERRED")

    @traced_clinic(
        "clinic.mark_unreachable",
        "/appointments/{id}/unreachable",
        "POST",
        idempotency_used=True,
    )
    def mark_unreachable(self, ctx: CallContext, reason: UnreachableReason) -> dict[str, Any]:
        fsm.check_closing_write(ctx)
        if ctx.call.direction != "outbound":
            raise guardrails.SevereFailureBlocked("SF-01", "Inbound không ghi UNREACHABLE")
        appointment_id = self._target(ctx)
        written = self._write(
            ctx,
            "unreachable",
            f"/appointments/{appointment_id}/unreachable",
            {"unreachable_reason": reason},
            lambda version, key: self._api.mark_unreachable(appointment_id, reason, version, key),
            allowed_statuses=frozenset({"SCHEDULED", "BOOKED", "UNREACHABLE"}),
        )
        return self._require_written(ctx, "unreachable", written, "UNREACHABLE")

    # --- Thực thi lệnh ghi qua nhật ký --------------------------------------------

    def _write(
        self,
        ctx: CallContext,
        operation: str,
        endpoint: str,
        payload: dict[str, Any],
        send: Callable[[Optional[int], str], dict[str, Any]],
        read_version: bool = True,
        allowed_statuses: frozenset[str] = ACTIONABLE_APPOINTMENT_STATUSES,
    ) -> dict[str, Any]:
        journal = current_journal()
        key = f"{ctx.call_id}:{ctx.turn}:{operation}"
        kind = operation.split(":")[0]
        deadline = self._clock() + WRITE_BUDGET_S
        version = self._read_version(ctx, allowed_statuses, deadline) if read_version else None
        command = ClinicCommand(kind, endpoint, payload, version, key)
        # Không lưu được nhật ký -> SessionStoreUnavailable, lệnh không được gửi
        journal.begin(command)
        sends = 0
        conflict_retried = False
        while True:
            sends += 1
            try:
                result = send(version, key)
            except ClinicAPIError as exc:
                if not exc.outcome_known:
                    # Không biết mock đã áp dụng chưa: gửi lại Y HỆT (cùng key, cùng If-Match) — đã áp
                    # dụng thì mock replay 200 cũ, chưa thì xử lý lần đầu. Đọc lại version ở đây sẽ đổi
                    # If-Match, mock coi là payload khác và trả 422 thay vì replay. Lệnh vẫn PENDING.
                    if self._may_resend(sends, deadline, self._backoff(sends)):
                        continue
                    raise self._unknown(journal, command, f"{exc.code} {exc.message}") from exc
                journal.failed(command, f"HTTP {exc.status} {exc.code}")
                if exc.code == "VERSION_CONFLICT":
                    # §4.2.5: đọc lại version, gửi lại MỘT lần với cùng Idempotency-Key
                    if not conflict_retried and self._may_resend(sends, deadline, 0.0):
                        conflict_retried = True
                        version = (
                            self._read_version(ctx, allowed_statuses, deadline)
                            if read_version
                            else None
                        )
                        command = ClinicCommand(kind, endpoint, payload, version, key)
                        journal.begin(command)
                        continue
                elif exc.retryable and self._may_resend(sends, deadline, self._backoff(sends)):
                    # 429 / không kết nối được: lệnh chắc chắn chưa áp dụng, gửi lại cùng key
                    journal.begin(command)
                    continue
                if exc.code == "SLOT_TAKEN":
                    raise SlotTaken(exc.status, exc.code) from exc
                if exc.code == "INVALID_STATE_TRANSITION":
                    raise AppointmentNotActionable(exc.code) from exc
                raise ClinicWriteRejected(exc.status, exc.code, retryable=exc.retryable) from exc
            except Exception as exc:
                # Lỗi ngoài hợp đồng cổng (bug, ngoại lệ transport lạ): không biết Clinic đã áp dụng chưa
                raise self._unknown(journal, command, repr(exc)) from exc
            journal.succeeded(command, result if isinstance(result, dict) else {"result": result})
            return result

    def _read_version(
        self, ctx: CallContext, allowed_statuses: frozenset[str], deadline: float
    ) -> int:
        reads = 0
        while True:
            reads += 1
            try:
                return self.get_actionable_appointment(ctx, allowed_statuses)["version"]
            except ClinicAPIError as exc:
                # Chưa gửi lệnh ghi nào nên đọc lại luôn an toàn; hết lượt là từ chối xác định
                if exc.retryable and self._may_resend(reads, deadline, self._backoff(reads)):
                    continue
                raise ClinicWriteRejected(exc.status, exc.code, retryable=exc.retryable) from exc

    def _may_resend(self, sends: int, deadline: float, pause: float) -> bool:
        """Còn lượt và còn đủ ngân sách cho một lần gửi nữa (sau khi chờ `pause`) thì chờ rồi trả True."""
        if sends >= WRITE_MAX_SENDS:
            return False
        if deadline - self._clock() - pause < WRITE_MIN_ATTEMPT_S:
            return False
        if pause > 0:
            self._sleep(pause)
        return True

    @staticmethod
    def _backoff(sends: int) -> float:
        return WRITE_BACKOFF_S[min(sends, len(WRITE_BACKOFF_S)) - 1]

    @staticmethod
    def _require_written(
        ctx: CallContext, operation: str, written: dict[str, Any], status: str, **fields: Any
    ) -> dict[str, Any]:
        """2xx chưa đủ: body phải ở đúng trạng thái đích, nếu không thì chưa rõ Clinic đã ghi gì.

        Lệnh đã được mock nhận nên không ghi /transfer thay thế — chặn lượt để đối soát.
        """
        if written.get("status") != status or any(
            written.get(name) != value for name, value in fields.items()
        ):
            raise WriteOutcomeUnknown(
                f"{ctx.call_id}: {operation} trả status {written.get('status')}"
            )
        return written

    @staticmethod
    def _unknown(journal: Any, command: ClinicCommand, error: str) -> WriteOutcomeUnknown:
        try:
            journal.unknown(command, error)
        except SessionStoreUnavailable:
            # Lệnh vẫn PENDING trong nhật ký — lần xử lý sau cũng bị chặn đối soát
            logger.error("Không ghi được trạng thái UNKNOWN cho %s", command.idempotency_key)
        return WriteOutcomeUnknown(f"{command.idempotency_key}: {error}")

    @staticmethod
    def _target(ctx: CallContext) -> str:
        appointment_id = ctx.target_appointment_id
        guardrails.assert_target_appointment(ctx, appointment_id)
        assert appointment_id is not None
        return appointment_id
