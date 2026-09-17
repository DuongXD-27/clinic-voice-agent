"""Clinic mock trong bộ nhớ — cài `ports.ClinicAPI` y như `clinic-mock/src/clinic_mock/routes.py`.

Dùng để test engine không cần docker/mạng, tạo dữ liệu cho tình huống mock thật không có (hai bệnh
nhân cùng số, `verify` null, 30 slot...) và gây lỗi theo ý (`fail_next`). Không thay mock thật: bộ contract
test `tests/engine/tools/test_clinic_api_contract.py` chạy cùng case trên fake và trên mock để giữ fake
không lệch.

Hành vi mô phỏng (đối chiếu routes.py, lifecycle.py, errors.py của mock):
- Danh sách phân trang {"data", "next_cursor", "has_more"}, limit kẹp [1, 100], cursor = offset.
- /patients: phone phải khớp ^(02|03|05|07|08|09)\\d{8}$ → 400 INVALID_REQUEST.
- /slots: from/to RFC 3339 đủ giây + offset, to > from, ≤ 14 ngày → 400; slot trả shape mock (start_time).
- Idempotency-Key kiểm tra TRƯỚC If-Match; cùng key khác payload → 422 IDEMPOTENCY_CONFLICT;
  payload hash của confirm/cancel/transfer/reschedule gồm cả if_match, của unreachable/create chỉ body.
- If-Match lệch → 409 VERSION_CONFLICT; sai lifecycle → 409 INVALID_STATE_TRANSITION;
  cancel thiếu confirmed → 409 CONFIRMATION_REQUIRED; reschedule slot không còn → 409 SLOT_TAKEN.
- unreachable tăng attempt_count, replay không tăng; create trả appointment BOOKED version 1.

Bề mặt quan sát giữ cho test hiện có: `writes` [(appointment_id, STATUS, extra)], `requests` [(key, op)],
`appointments`, `slots`, `taken_slots`, `slot_reads`, `patient_lookups`.
"""

import base64
import copy
import json
import re
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from callbot.engine.errors import ClinicAPIError
from callbot.engine.tools.ports import PAGE_LIMIT, Page
from callbot.engine.tools.telemetry import ApiCallRecord, record_api_call

PHONE_RE = re.compile(r"^(02|03|05|07|08|09)\d{8}$")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")
SLOT_WINDOW_MAX = timedelta(days=14)
DEFAULT_LIMIT = 25

# lifecycle.py của mock
TRANSITIONS: dict[str, set[str]] = {
    "confirm": {"SCHEDULED", "BOOKED", "CONFIRMED"},
    "cancel": {"SCHEDULED", "BOOKED", "CONFIRMED"},
    "transfer": {"SCHEDULED", "BOOKED", "CONFIRMED"},
    "reschedule": {"SCHEDULED", "BOOKED", "CONFIRMED"},
    "unreachable": {"SCHEDULED", "BOOKED", "UNREACHABLE"},
}

# Fixture mặc định: giá trị Listing 3 của contract (test engine hiện có ghi cứng giờ 09:00 và hai slot).
# Mock mentor seed apt_00417 lúc 15:30 và chỉ một slot — dùng `FakeClinicAPI.with_mock_fixtures()`.
DEFAULT_PATIENT = {
    "patient_id": "pt_3391",
    "display_name": "N. V. A.",
    "phone": "0912345600",
    "dob": "1978-03-14",
    "verify": {"full_name": "Nguyễn Văn A", "dob": "1978-03-14"},
}
DEFAULT_APPOINTMENT = {
    "appointment_id": "apt_00417",
    "status": "SCHEDULED",
    "clinic_id": "cl_vinmec",
    "starts_at": "2026-10-14T09:00:00+07:00",
    "ends_at": "2026-10-14T09:30:00+07:00",
    "department": "Nội tổng quát",
    "patient": {
        "patient_id": "pt_3391",
        "display_name": "N. V. A.",
        "verify": {"full_name": "Nguyễn Văn A", "dob": "1978-03-14"},
    },
    "attempt_count": 0,
    "version": 3,
}
DEFAULT_SLOTS = [
    {"slot_id": "slot_aa01", "starts_at": "2026-10-14T10:00:00+07:00"},
    {"slot_id": "slot_91d2", "starts_at": "2026-10-14T14:30:00+07:00"},
]

# store.py của mock: bộ per-tenant, không liên quan 7 kịch bản — dùng thử phân trang và cách ly
MOCK_TENANT_PATIENTS = [
    {
        "patient_id": "p_12345",
        "display_name": "Mai N.",
        "phone": "0912345678",
        "dob": "1985-04-12",
        "verify": {"full_name": "Nguyễn Thị Mai", "dob": "1985-04-12"},
    },
    {
        "patient_id": "p_67890",
        "display_name": "Nam T.",
        "phone": "0987654321",
        "dob": "1972-11-03",
        "verify": {"full_name": "Trần Văn Nam", "dob": "1972-11-03"},
    },
]
MOCK_TENANT_SLOTS = [
    {
        "slot_id": "s_987",
        "clinic_id": "c_001",
        "start_time": "2026-09-15T09:00:00Z",
        "end_time": "2026-09-15T09:30:00Z",
        "provider_id": "pr_456",
    },
    {
        "slot_id": "s_988",
        "clinic_id": "c_001",
        "start_time": "2026-09-15T09:30:00Z",
        "end_time": "2026-09-15T10:00:00Z",
        "provider_id": "pr_456",
    },
    {
        "slot_id": "s_1024",
        "clinic_id": "c_002",
        "start_time": "2026-09-15T11:00:00Z",
        "end_time": "2026-09-15T11:30:00Z",
        "provider_id": "pr_789",
    },
]


def clinic_error(status: int, code: str, message: str = "") -> ClinicAPIError:
    """Lỗi xác định như mock trả (envelope error.code); test dùng để giả một lần từ chối."""
    return ClinicAPIError(status, code, message or code, request_id="fake", outcome_known=True)


class FakeClinicAPI:
    def __init__(self, *, seed: bool = True, strict_slot_window: bool = False) -> None:
        self.patients: dict[str, dict[str, Any]] = {}
        # Slot còn trống. Test cũ append {"slot_id", "starts_at"}; khi trả ra sẽ đổi sang shape mock.
        self.slots: list[dict[str, Any]] = []
        self.appointments: dict[str, dict[str, Any]] = {}
        # slot_id đã bị chiếm (mock: pop khỏi db.slots). Test thêm vào đây để giả "người khác vừa lấy".
        self.taken_slots: set[str] = set()
        # Mock lọc slot theo cửa sổ from/to. Test engine hiện có dùng đồng hồ thật nên slot 14-10-2026 nằm
        # ngoài now+14d — mặc định không lọc; contract test bật `strict_slot_window=True`. Xem T-09.
        self.strict_slot_window = strict_slot_window

        # Quan sát
        self.writes: list[tuple[str, str, dict[str, Any]]] = []  # tương đương /_harness/writelog
        self.requests: list[
            tuple[str, str]
        ] = []  # (idempotency_key, op) mọi lệnh ghi, kể cả replay
        self.patient_lookups: list[str] = []
        self.slot_reads = 0
        self.calls: list[ApiCallRecord] = []

        self._idempotency: dict[str, tuple[int, dict[str, Any]]] = {}
        self._failures: dict[str, list[tuple[Optional[ClinicAPIError], bool]]] = {}
        # Mock giữ slot_id server-side để reschedule giải phóng; Listing 3 không trả ra
        self._slot_of: dict[str, str] = {}
        if seed:
            self.seed_patient(DEFAULT_PATIENT)
            self.seed_appointment(DEFAULT_APPOINTMENT, slot_id="slot_77aa")
            for slot in DEFAULT_SLOTS:
                self.seed_slot(slot)

    @classmethod
    def with_mock_fixtures(cls) -> "FakeClinicAPI":
        """Dữ liệu y như `store.py` của mock mentor sau /_harness/reset.

        Canonical: apt_00417 15:30 v3 chiếm slot_77aa; pt_3391; slot_91d2 15:00 trống.
        Per-tenant: p_12345, p_67890; s_987, s_988 (c_001, 15-09-2026), s_1024 (c_002) — mock gắn hậu tố
        tenant vào id, contract test không được ghi cứng id các bản ghi này.
        """
        fake = cls(seed=False, strict_slot_window=True)
        fake.seed_patient(DEFAULT_PATIENT)
        fake.seed_appointment(
            dict(
                DEFAULT_APPOINTMENT,
                starts_at="2026-10-14T15:30:00+07:00",
                ends_at="2026-10-14T16:00:00+07:00",
            ),
            slot_id="slot_77aa",
        )
        fake.seed_slot(
            {
                "slot_id": "slot_91d2",
                "clinic_id": "cl_vinmec",
                "start_time": "2026-10-14T15:00:00+07:00",
                "end_time": "2026-10-14T15:30:00+07:00",
                "provider_id": "pr_vinmec_1",
            }
        )
        for patient in MOCK_TENANT_PATIENTS:
            fake.seed_patient(patient)
        for slot in MOCK_TENANT_SLOTS:
            fake.seed_slot(slot)
        return fake

    # --- Seed ------------------------------------------------------------------

    def seed_patient(self, patient: dict[str, Any]) -> dict[str, Any]:
        record = copy.deepcopy(patient)
        record.setdefault("display_name", record["patient_id"])
        record.setdefault("verify", None)
        self.patients[record["patient_id"]] = record
        return record

    def seed_slot(self, slot: dict[str, Any]) -> dict[str, Any]:
        record = copy.deepcopy(slot)
        self.slots.append(record)
        return record

    def seed_appointment(self, appointment: dict[str, Any], slot_id: Optional[str] = None) -> dict:
        record = copy.deepcopy(appointment)
        record.setdefault("attempt_count", 0)
        record.setdefault("version", 1)
        if slot_id is not None:
            self._slot_of[record["appointment_id"]] = slot_id
        self.appointments[record["appointment_id"]] = record
        return record

    def fail_next(
        self,
        operation: str,
        error: Optional[ClinicAPIError] = None,
        *,
        outcome_unknown: bool = False,
        apply_first: bool = False,
    ) -> None:
        """Lần gọi `operation` kế tiếp thất bại.

        `error`: lỗi xác định (mặc định 503 UPSTREAM). `outcome_unknown=True`: giả timeout — với
        `apply_first=True` lệnh ghi vẫn được áp dụng trước khi lỗi (mock đã ghi, bot không biết).
        """
        if error is None:
            error = ClinicAPIError(
                None if outcome_unknown else 503,
                "TIMEOUT" if outcome_unknown else "UPSTREAM",
                "fail_next",
                request_id="fake",
                outcome_known=not outcome_unknown,
            )
        self._failures.setdefault(operation, []).append((error, apply_first))

    # --- Đọc -----------------------------------------------------------------

    def find_patient_by_phone(
        self, phone: str, cursor: Optional[str] = None, limit: int = PAGE_LIMIT
    ) -> Page:
        with self._call("find_patient_by_phone", "GET", "/patients"):
            self._maybe_fail("find_patient_by_phone")
            if not PHONE_RE.match(phone or ""):
                raise clinic_error(400, "INVALID_REQUEST", "Request validation failed.")
            self.patient_lookups.append(phone)
            matched = [dict(p) for p in self.patients.values() if p.get("phone") == phone]
            return _paginate(matched, cursor, limit)

    def get_slots(
        self,
        clinic_id: str,
        from_: str,
        to: str,
        cursor: Optional[str] = None,
        limit: int = PAGE_LIMIT,
    ) -> Page:
        with self._call("get_slots", "GET", "/slots"):
            self._maybe_fail("get_slots")
            if not ISO_RE.match(from_ or "") or not ISO_RE.match(to or ""):
                raise clinic_error(400, "INVALID_REQUEST", "Request validation failed.")
            if to <= from_:
                raise clinic_error(400, "INVALID_REQUEST", "'to' must be greater than 'from'.")
            start, end = datetime.fromisoformat(from_), datetime.fromisoformat(to)
            if end - start > SLOT_WINDOW_MAX:
                raise clinic_error(
                    400, "INVALID_REQUEST", "'from'..'to' window must be <= 14 days."
                )
            self.slot_reads += 1
            matched = []
            for slot in self.slots:
                out = self._slot_out(slot)
                if out["slot_id"] in self.taken_slots or out["clinic_id"] != clinic_id:
                    continue
                if self.strict_slot_window:
                    starts = datetime.fromisoformat(out["start_time"])
                    if not (start <= starts < end):
                        continue
                matched.append(out)
            return _paginate(matched, cursor, limit)

    def get_appointment(self, appointment_id: str) -> dict[str, Any]:
        with self._call("get_appointment", "GET", f"/appointments/{appointment_id}"):
            self._maybe_fail("get_appointment")
            return dict(self._appointment(appointment_id))

    # --- Ghi -----------------------------------------------------------------

    def create_appointment(
        self, patient_id: str, slot_id: str, idempotency_key: Optional[str] = None
    ) -> dict[str, Any]:
        endpoint = "POST /v1/appointments"
        payload = {"patient_id": patient_id, "slot_id": slot_id}

        def apply() -> tuple[int, dict[str, Any]]:
            patient = self.patients.get(patient_id)
            if patient is None:
                raise clinic_error(404, "NOT_FOUND", f"patient {patient_id} not found.")
            slot = self._open_slot(slot_id)
            if slot is None:
                raise clinic_error(404, "NOT_FOUND", f"slot {slot_id} not found.")
            # Giữ cách đặt tên cũ (apt_new_<số appointment hiện có>) để test engine hiện có không đổi
            new_id = f"apt_new_{len(self.appointments)}"
            record = {
                "appointment_id": new_id,
                "status": "BOOKED",
                "clinic_id": slot["clinic_id"],
                "starts_at": slot["start_time"],
                "ends_at": slot["end_time"],
                "department": "Tổng quát",
                "patient": {
                    "patient_id": patient["patient_id"],
                    "display_name": patient.get("display_name", ""),
                    "verify": patient.get("verify"),
                },
                "attempt_count": 0,
                "version": 1,
            }
            self.appointments[new_id] = record
            self._slot_of[new_id] = slot_id
            self.taken_slots.add(slot_id)
            self.writes.append((new_id, "BOOKED", {"slot_id": slot_id}))
            return 201, dict(record)

        return self._write("create_appointment", "book", endpoint, idempotency_key, payload, apply)

    def confirm_appointment(
        self, appointment_id: str, version: int, idempotency_key: Optional[str] = None
    ) -> dict[str, Any]:
        endpoint = f"POST /v1/appointments/{appointment_id}/confirm"

        def apply() -> tuple[int, dict[str, Any]]:
            appt = self._appointment(appointment_id)
            self._check_version(appt, version)
            self._check_transition(appt, "confirm")
            appt.update(
                status="CONFIRMED",
                confirmed_at=_now_iso(),
                confirmed_via="callbot",
                version=appt["version"] + 1,
            )
            self.writes.append((appointment_id, "CONFIRMED", {}))
            return 200, dict(appt)

        return self._write(
            "confirm_appointment",
            "CONFIRMED",
            endpoint,
            idempotency_key,
            {"if_match": version},
            apply,
        )

    def cancel_appointment(
        self,
        appointment_id: str,
        cancel_reason: str,
        version: int,
        idempotency_key: Optional[str] = None,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        endpoint = f"POST /v1/appointments/{appointment_id}/cancel"

        def apply() -> tuple[int, dict[str, Any]]:
            appt = self._appointment(appointment_id)
            self._check_version(appt, version)
            if not confirmed:
                raise clinic_error(
                    409,
                    "CONFIRMATION_REQUIRED",
                    "Cancellation requires an explicit second confirmation.",
                )
            self._check_transition(appt, "cancel")
            appt.update(
                status="CANCELLED", cancel_reason=cancel_reason, version=appt["version"] + 1
            )
            self.writes.append((appointment_id, "CANCELLED", {"cancel_reason": cancel_reason}))
            return 200, dict(appt)

        return self._write(
            "cancel_appointment",
            "CANCELLED",
            endpoint,
            idempotency_key,
            {"if_match": version, "cancel_reason": cancel_reason, "confirmed": confirmed},
            apply,
        )

    def transfer_appointment(
        self,
        appointment_id: str,
        transfer_reason: str,
        version: int,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        endpoint = f"POST /v1/appointments/{appointment_id}/transfer"

        def apply() -> tuple[int, dict[str, Any]]:
            appt = self._appointment(appointment_id)
            self._check_version(appt, version)
            self._check_transition(appt, "transfer")
            appt.update(
                status="TRANSFERRED", transfer_reason=transfer_reason, version=appt["version"] + 1
            )
            self.writes.append(
                (appointment_id, "TRANSFERRED", {"transfer_reason": transfer_reason})
            )
            return 200, dict(appt)

        return self._write(
            "transfer_appointment",
            "TRANSFERRED",
            endpoint,
            idempotency_key,
            {"if_match": version, "transfer_reason": transfer_reason},
            apply,
        )

    def reschedule_appointment(
        self,
        appointment_id: str,
        new_slot_id: str,
        version: int,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        endpoint = f"POST /v1/appointments/{appointment_id}/reschedule"

        def apply() -> tuple[int, dict[str, Any]]:
            appt = self._appointment(appointment_id)
            self._check_version(appt, version)
            self._check_transition(appt, "reschedule")
            new_slot = self._open_slot(new_slot_id)
            if new_slot is None:
                raise clinic_error(409, "SLOT_TAKEN", f"{new_slot_id} is no longer open")
            # Giải phóng slot cũ về danh sách trống (mock: db.slots[released] = Slot(...))
            released = self._slot_of.get(appointment_id, "")
            if released:
                self.taken_slots.discard(released)
                if self._open_slot(released) is None and not any(
                    s.get("slot_id") == released for s in self.slots
                ):
                    self.slots.append(
                        {
                            "slot_id": released,
                            "clinic_id": appt["clinic_id"],
                            "start_time": appt["starts_at"],
                            "end_time": appt.get("ends_at") or _plus_30(appt["starts_at"]),
                            "provider_id": new_slot["provider_id"],
                        }
                    )
            self.taken_slots.add(new_slot_id)
            self._slot_of[appointment_id] = new_slot_id
            appt.update(
                status="RESCHEDULED",
                clinic_id=new_slot["clinic_id"],
                starts_at=new_slot["start_time"],
                ends_at=new_slot["end_time"],
                new_slot_id=new_slot_id,
                version=appt["version"] + 1,
            )
            self.writes.append((appointment_id, "RESCHEDULED", {"new_slot_id": new_slot_id}))
            # Listing 4: response tối giản, không phải appointment đầy đủ
            return 200, {
                "status": "RESCHEDULED",
                "new_slot_id": new_slot_id,
                "released_slot_id": released,
                "version": appt["version"],
            }

        return self._write(
            "reschedule_appointment",
            "reschedule",
            endpoint,
            idempotency_key,
            {"if_match": version, "new_slot_id": new_slot_id, "requested_by": "PATIENT"},
            apply,
        )

    def mark_unreachable(
        self,
        appointment_id: str,
        unreachable_reason: str,
        version: int,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        endpoint = f"POST /v1/appointments/{appointment_id}/unreachable"

        def apply() -> tuple[int, dict[str, Any]]:
            appt = self._appointment(appointment_id)
            self._check_version(appt, version)
            self._check_transition(appt, "unreachable")
            appt.update(
                status="UNREACHABLE",
                unreachable_reason=unreachable_reason,
                attempt_count=appt["attempt_count"] + 1,
                version=appt["version"] + 1,
            )
            self.writes.append(
                (appointment_id, "UNREACHABLE", {"unreachable_reason": unreachable_reason})
            )
            return 200, dict(appt)

        # §4.2.5: payload idempotency chỉ có body — replay với If-Match cũ vẫn trả 200 cũ
        return self._write(
            "mark_unreachable",
            "unreachable",
            endpoint,
            idempotency_key,
            {"unreachable_reason": unreachable_reason},
            apply,
        )

    # --- Bên trong -----------------------------------------------------------------

    def _write(
        self,
        operation: str,
        op_label: str,
        endpoint: str,
        key: Optional[str],
        payload: dict[str, Any],
        apply: Callable[[], tuple[int, dict[str, Any]]],
    ) -> dict[str, Any]:
        method, _, path = endpoint.partition(" ")
        with self._call(operation, method, path.removeprefix("/v1")):
            self.requests.append((key or "", op_label))
            failure = self._pop_failure(operation)
            if failure is not None and not failure[1]:
                raise failure[0]
            # Idempotency trước If-Match (mock: _idempotent_check chạy trước _get_appt/_check_version)
            payload_hash = hash(json.dumps(payload, sort_keys=True))
            if key:
                cached = self._idempotency.get(f"{endpoint}:{key}")
                if cached is not None:
                    if cached[0] != payload_hash:
                        raise clinic_error(
                            422,
                            "IDEMPOTENCY_CONFLICT",
                            "Idempotency-Key reused with a different payload.",
                        )
                    return dict(cached[1])
            _status, body = apply()
            if key:
                self._idempotency[f"{endpoint}:{key}"] = (payload_hash, dict(body))
            if failure is not None:
                # apply_first: mock đã ghi nhưng bot không nhận được phản hồi
                raise failure[0]
            return body

    def _appointment(self, appointment_id: str) -> dict[str, Any]:
        appt = self.appointments.get(appointment_id)
        if appt is None:
            raise clinic_error(404, "NOT_FOUND", f"appointment {appointment_id} not found.")
        return appt

    @staticmethod
    def _check_version(appt: dict[str, Any], if_match: Optional[int]) -> None:
        if if_match is not None and int(if_match) != int(appt["version"]):
            raise clinic_error(
                409, "VERSION_CONFLICT", "If-Match version does not match current state."
            )

    @staticmethod
    def _check_transition(appt: dict[str, Any], action: str) -> None:
        if appt["status"] not in TRANSITIONS[action]:
            raise clinic_error(
                409,
                "INVALID_STATE_TRANSITION",
                f"Cannot {action} an appointment in status {appt['status']}.",
            )

    def _open_slot(self, slot_id: str) -> Optional[dict[str, Any]]:
        if slot_id in self.taken_slots:
            return None
        for slot in self.slots:
            if slot.get("slot_id") == slot_id:
                return self._slot_out(slot)
        return None

    @staticmethod
    def _slot_out(slot: dict[str, Any]) -> dict[str, Any]:
        """Shape mock: slot_id, clinic_id, start_time, end_time, provider_id — không có starts_at."""
        start = slot.get("start_time") or slot["starts_at"]
        return {
            "slot_id": slot["slot_id"],
            "clinic_id": slot.get("clinic_id", "cl_vinmec"),
            "start_time": start,
            "end_time": slot.get("end_time") or slot.get("ends_at") or _plus_30(start),
            "provider_id": slot.get("provider_id", "pr_vinmec_1"),
        }

    def _maybe_fail(self, operation: str) -> None:
        failure = self._pop_failure(operation)
        if failure is not None:
            raise failure[0]

    def _pop_failure(self, operation: str) -> Optional[tuple[ClinicAPIError, bool]]:
        queue = self._failures.get(operation)
        if not queue:
            return None
        error, apply_first = queue.pop(0)
        assert error is not None
        return error, apply_first

    def _call(self, operation: str, method: str, path: str) -> "_CallRecorder":
        return _CallRecorder(self, operation, method, path)


class _CallRecorder:
    """Ghi ApiCallRecord cho mỗi lần gọi fake — cùng dữ liệu trace như client thật."""

    def __init__(self, fake: FakeClinicAPI, operation: str, method: str, path: str) -> None:
        self._fake, self._operation, self._method, self._path = fake, operation, method, path

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, _tb) -> bool:
        if exc is None:
            record = self._record(200, None, "ok")
        elif isinstance(exc, ClinicAPIError):
            record = self._record(
                exc.status, exc.code, "rejected" if exc.outcome_known else "unknown"
            )
        else:
            record = self._record(None, type(exc).__name__, "unknown")
        self._fake.calls.append(record)
        record_api_call(record)
        return False

    def _record(self, status: Optional[int], code: Optional[str], outcome: str) -> ApiCallRecord:
        return ApiCallRecord(
            operation=self._operation,
            method=self._method,
            path=self._path,
            status=status,
            code=code,
            request_id="fake",
            latency_ms=0,
            outcome=outcome,  # type: ignore[arg-type]
        )


def _paginate(items: list[dict[str, Any]], cursor: Optional[str], limit: int) -> Page:
    limit = max(1, min(int(limit), 100))
    start = 0
    if cursor:
        try:
            pad = "=" * (-len(cursor) % 4)
            start = int(json.loads(base64.urlsafe_b64decode(cursor + pad)).get("offset", 0))
        except Exception:  # noqa: BLE001 — mock cũng bỏ qua cursor hỏng
            start = 0
    page = items[start : start + limit]
    next_offset = start + limit
    has_more = next_offset < len(items)
    next_cursor = (
        base64.urlsafe_b64encode(json.dumps({"offset": next_offset}).encode()).decode().rstrip("=")
        if has_more
        else None
    )
    return {"data": page, "next_cursor": next_cursor, "has_more": has_more}


def _plus_30(start: str) -> str:
    return (datetime.fromisoformat(start) + timedelta(minutes=30)).isoformat()


def _now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()
