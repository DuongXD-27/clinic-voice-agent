"""`FakeClinicAPI` — tương ứng `clinic-mock/src/clinic_mock/routes.py`, cài `ports.ClinicAPI` trong bộ nhớ.

Hành vi mô phỏng (đối chiếu routes.py, schemas.py, lifecycle.py của mock, CHANGELOG 2.0.0):
- Danh sách phân trang {"data", "next_cursor", "has_more"}, limit kẹp [1, 100], cursor = offset base64.
- /patients: phone phải khớp ^(02|03|05|07|08|09)\\d{8}$ → 400 INVALID_REQUEST.
- /slots: from/to RFC 3339 đủ giây + offset, to > from, ≤ 14 ngày → 400; slot shape mock (start_time).
- Body sai enum (cancel/transfer/unreachable reason) → 400, kiểm TRƯỚC idempotency như FastAPI.
- Idempotency-Key kiểm TRƯỚC If-Match; cùng key khác payload → 422 IDEMPOTENCY_CONFLICT;
  payload của confirm/cancel/transfer/reschedule gồm cả if_match, của unreachable/create chỉ body.
- If-Match lệch → 409 VERSION_CONFLICT; sai lifecycle → 409 INVALID_STATE_TRANSITION;
  cancel thiếu confirmed → 409 CONFIRMATION_REQUIRED; reschedule slot không còn → 409 SLOT_TAKEN.
- create: 201 appointment BOOKED version 1; patient không có verify → 500 (PatientRef.verify bắt buộc).
- reschedule trả slot cũ về danh sách trống với provider của lịch cũ; unreachable tăng attempt_count.

Khác mock có chủ đích: id lịch mới `apt_new_<n>` (test ghi cứng), request_id "fake", không có
auth/tenant, không có /_harness và GET /appointments?date= (bot không gọi).
"""

import base64
import copy
import json
from collections.abc import Callable
from datetime import datetime
from typing import Any, Optional

from callbot.engine.tools.ports import PAGE_LIMIT, Page
from clinic_mock_sim import store
from clinic_mock_sim.errors import (
    confirmation_required,
    conflict,
    internal_error,
    not_found,
    unprocessable,
    validation_error,
    version_conflict,
)
from clinic_mock_sim.faults import FaultInjector
from clinic_mock_sim.lifecycle import assert_appointment_transition, assert_unreachable_transition
from clinic_mock_sim.recorder import CallRecorder
from clinic_mock_sim.schemas import (
    APPOINTMENT_STATUSES,
    CANCEL_REASONS,
    ISO_RE,
    PAGE_LIMIT_MAX,
    PAGE_LIMIT_MIN,
    PHONE_RE,
    SLOT_WINDOW_MAX,
    TRANSFER_REASONS,
    UNREACHABLE_REASONS,
)


class FakeClinicAPI(FaultInjector):
    def __init__(self, *, seed: bool = True, strict_slot_window: bool = False) -> None:
        self.patients: dict[str, dict[str, Any]] = {}
        # Slot đã seed (shape mock). Slot trống = có ở đây và không nằm trong `taken_slots`.
        self.slots: list[dict[str, Any]] = []
        self.appointments: dict[str, dict[str, Any]] = {}
        # slot_id đang bị chiếm (mock: pop khỏi db.slots). Thêm vào để giả "người khác vừa lấy".
        self.taken_slots: set[str] = set()
        # Mock luôn lọc slot theo cửa sổ from/to. Test engine hiện có dùng đồng hồ thật nên slot
        # 14-10-2026 nằm ngoài now+14d — mặc định không lọc; `mentor_mock()` bật. Xem T-09.
        self.strict_slot_window = strict_slot_window

        # Quan sát
        self.writes: list[tuple[str, str, dict[str, Any]]] = []  # lệnh ghi đã áp dụng
        # (idempotency_key, op) mọi lệnh ghi đã gửi, kể cả replay và lần bị lỗi
        self.requests: list[tuple[str, str]] = []
        self.patient_lookups: list[str] = []
        self.slot_reads = 0
        self.calls: list = []  # ApiCallRecord
        self.closed = False

        self._idempotency: dict[str, tuple[str, dict[str, Any]]] = {}
        # Mock giữ slot_id/provider_id của lịch server-side để reschedule giải phóng; Listing 3 không trả
        self._slot_of: dict[str, str] = {}
        self._provider_of: dict[str, str] = {}
        self._init_faults()
        if seed:
            store.seed_listing3(self)

    @classmethod
    def listing3(cls) -> "FakeClinicAPI":
        """Mặc định: giá trị Listing 3 (apt_00417 lúc 09:00, slot_aa01 + slot_91d2), không lọc cửa sổ."""
        return cls()

    @classmethod
    def mentor_mock(cls) -> "FakeClinicAPI":
        """Y như mock mentor sau /_harness/reset; `/slots` lọc cửa sổ như mock. Xem `store.py`."""
        sim = cls(seed=False, strict_slot_window=True)
        store.seed_mentor_mock(sim)
        return sim

    # Tên cũ — giữ cho test/tài liệu F-05
    with_mock_fixtures = mentor_mock

    def close(self) -> None:
        self.closed = True

    # --- Seed ------------------------------------------------------------------

    def seed_patient(self, patient: dict[str, Any]) -> dict[str, Any]:
        record = copy.deepcopy(patient)
        record.setdefault("display_name", record["patient_id"])
        record.setdefault("verify", None)
        self.patients[record["patient_id"]] = record
        return record

    def seed_slot(self, slot: dict[str, Any]) -> dict[str, Any]:
        """Thêm slot trống; trùng slot_id thì thay (mock lưu slot theo dict)."""
        record = store.normalize_slot(slot)
        self.slots = [s for s in self.slots if s.get("slot_id") != record["slot_id"]]
        self.slots.append(record)
        self.taken_slots.discard(record["slot_id"])
        return record

    def seed_appointment(
        self,
        appointment: dict[str, Any],
        slot_id: Optional[str] = None,
        provider_id: str = store.DEFAULT_PROVIDER,
    ) -> dict[str, Any]:
        record = copy.deepcopy(appointment)
        record.setdefault("attempt_count", 0)
        record.setdefault("version", 1)
        if slot_id is not None:
            self._slot_of[record["appointment_id"]] = slot_id
        self._provider_of[record["appointment_id"]] = provider_id
        self.appointments[record["appointment_id"]] = record
        return record

    # --- Helper dựng tình huống ------------------------------------------------------

    def set_status(self, appointment_id: str, status: str) -> None:
        """Đặt trạng thái trước cuộc gọi (không tăng version, không ghi `writes`)."""
        if status not in APPOINTMENT_STATUSES:
            raise ValueError(f"Trạng thái không tồn tại: {status!r}")
        self._appointment(appointment_id)["status"] = status

    def bump_version(self, appointment_id: str, by: int = 1) -> int:
        """Giả người khác vừa sửa lịch: lệnh ghi kế tiếp với version cũ sẽ VERSION_CONFLICT."""
        appt = self._appointment(appointment_id)
        appt["version"] += by
        return appt["version"]

    def take_slot(self, slot_id: str) -> None:
        """Giả người khác vừa đặt slot: không còn trong /slots, ghi vào slot đó → lỗi."""
        self.taken_slots.add(slot_id)

    # --- Đọc -----------------------------------------------------------------

    def find_patient_by_phone(
        self, phone: str, cursor: Optional[str] = None, limit: int = PAGE_LIMIT
    ) -> Page:
        with self._call("find_patient_by_phone", "GET", "/patients"):
            self._raise_fault("find_patient_by_phone")
            if not PHONE_RE.match(phone or ""):
                raise validation_error()
            self.patient_lookups.append(phone)
            matched = [copy.deepcopy(p) for p in self.patients.values() if p.get("phone") == phone]
            page = _paginate(matched, cursor, limit)
        self._run_after("find_patient_by_phone", page)
        return page

    def get_slots(
        self,
        clinic_id: str,
        from_: str,
        to: str,
        cursor: Optional[str] = None,
        limit: int = PAGE_LIMIT,
    ) -> Page:
        with self._call("get_slots", "GET", "/slots"):
            self._raise_fault("get_slots")
            if not ISO_RE.match(from_ or "") or not ISO_RE.match(to or ""):
                raise validation_error()
            if to <= from_:
                raise validation_error("'to' must be greater than 'from'.")
            start, end = datetime.fromisoformat(from_), datetime.fromisoformat(to)
            if end - start > SLOT_WINDOW_MAX:
                raise validation_error("'from'..'to' window must be <= 14 days.")
            self.slot_reads += 1
            matched = []
            for slot in self.slots:
                out = store.normalize_slot(slot)
                if out["slot_id"] in self.taken_slots or out["clinic_id"] != clinic_id:
                    continue
                if self.strict_slot_window:
                    starts = datetime.fromisoformat(out["start_time"])
                    if not (start <= starts < end):
                        continue
                matched.append(out)
            page = _paginate(matched, cursor, limit)
        self._run_after("get_slots", page)
        return page

    def get_appointment(self, appointment_id: str) -> dict[str, Any]:
        with self._call("get_appointment", "GET", f"/appointments/{appointment_id}"):
            self._raise_fault("get_appointment")
            appointment = copy.deepcopy(self._appointment(appointment_id))
        self._run_after("get_appointment", appointment)
        return appointment

    # --- Ghi -----------------------------------------------------------------

    def create_appointment(
        self, patient_id: str, slot_id: str, idempotency_key: Optional[str] = None
    ) -> dict[str, Any]:
        def apply() -> dict[str, Any]:
            patient = self.patients.get(patient_id)
            if patient is None:
                raise not_found(f"patient {patient_id}")
            slot = self._open_slot(slot_id)
            if slot is None:
                raise not_found(f"slot {slot_id}")
            if not patient.get("verify"):
                # Mock dựng PatientRef(verify=None) → pydantic lỗi → 500, chưa ghi gì
                raise internal_error()
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
                    "verify": copy.deepcopy(patient["verify"]),
                },
                "attempt_count": 0,
                "version": 1,
            }
            self.appointments[new_id] = record
            self._slot_of[new_id] = slot_id
            self._provider_of[new_id] = slot["provider_id"]
            self.taken_slots.add(slot_id)
            self.writes.append((new_id, "BOOKED", {"slot_id": slot_id}))
            return copy.deepcopy(record)

        return self._write(
            "create_appointment",
            "book",
            "POST /v1/appointments",
            idempotency_key,
            {"patient_id": patient_id, "slot_id": slot_id},
            apply,
        )

    def confirm_appointment(
        self, appointment_id: str, version: int, idempotency_key: Optional[str] = None
    ) -> dict[str, Any]:
        def apply() -> dict[str, Any]:
            appt = self._appointment(appointment_id)
            _check_version(appt, version)
            assert_appointment_transition(appt["status"], "confirm")
            appt.update(
                status="CONFIRMED",
                confirmed_at=store.now_iso(),
                confirmed_via="callbot",
                version=appt["version"] + 1,
            )
            self.writes.append((appointment_id, "CONFIRMED", {}))
            return copy.deepcopy(appt)

        return self._write(
            "confirm_appointment",
            "CONFIRMED",
            f"POST /v1/appointments/{appointment_id}/confirm",
            idempotency_key,
            {"if_match": version},
            apply,
            if_match_used=version is not None,
        )

    def cancel_appointment(
        self,
        appointment_id: str,
        cancel_reason: str,
        version: int,
        idempotency_key: Optional[str] = None,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        def apply() -> dict[str, Any]:
            appt = self._appointment(appointment_id)
            _check_version(appt, version)
            if not confirmed:
                raise confirmation_required()
            assert_appointment_transition(appt["status"], "cancel")
            appt.update(
                status="CANCELLED", cancel_reason=cancel_reason, version=appt["version"] + 1
            )
            self.writes.append((appointment_id, "CANCELLED", {"cancel_reason": cancel_reason}))
            return copy.deepcopy(appt)

        return self._write(
            "cancel_appointment",
            "CANCELLED",
            f"POST /v1/appointments/{appointment_id}/cancel",
            idempotency_key,
            {"if_match": version, "cancel_reason": cancel_reason, "confirmed": confirmed},
            apply,
            validate=lambda: _check_enum(cancel_reason, CANCEL_REASONS, "cancel_reason"),
            if_match_used=version is not None,
        )

    def transfer_appointment(
        self,
        appointment_id: str,
        transfer_reason: str,
        version: int,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        def apply() -> dict[str, Any]:
            appt = self._appointment(appointment_id)
            _check_version(appt, version)
            assert_appointment_transition(appt["status"], "transfer")
            appt.update(
                status="TRANSFERRED", transfer_reason=transfer_reason, version=appt["version"] + 1
            )
            self.writes.append(
                (appointment_id, "TRANSFERRED", {"transfer_reason": transfer_reason})
            )
            return copy.deepcopy(appt)

        return self._write(
            "transfer_appointment",
            "TRANSFERRED",
            f"POST /v1/appointments/{appointment_id}/transfer",
            idempotency_key,
            {"if_match": version, "transfer_reason": transfer_reason},
            apply,
            validate=lambda: _check_enum(transfer_reason, TRANSFER_REASONS, "transfer_reason"),
            if_match_used=version is not None,
        )

    def reschedule_appointment(
        self,
        appointment_id: str,
        new_slot_id: str,
        version: int,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        def apply() -> dict[str, Any]:
            appt = self._appointment(appointment_id)
            _check_version(appt, version)
            assert_appointment_transition(appt["status"], "reschedule")
            new_slot = self._open_slot(new_slot_id)
            if new_slot is None:
                raise conflict("SLOT_TAKEN", f"{new_slot_id} is no longer open")
            # Trả slot cũ về danh sách trống (mock: db.slots[released] = Slot(..., appt.provider_id))
            released = self._slot_of.get(appointment_id, "")
            if released:
                self.seed_slot(
                    {
                        "slot_id": released,
                        "clinic_id": appt["clinic_id"],
                        "start_time": appt["starts_at"],
                        "end_time": appt.get("ends_at") or store.plus_30(appt["starts_at"]),
                        "provider_id": self._provider_of.get(
                            appointment_id, store.DEFAULT_PROVIDER
                        ),
                    }
                )
            self.taken_slots.add(new_slot_id)
            self._slot_of[appointment_id] = new_slot_id
            self._provider_of[appointment_id] = new_slot["provider_id"]
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
            return {
                "status": "RESCHEDULED",
                "new_slot_id": new_slot_id,
                "released_slot_id": released,
                "version": appt["version"],
            }

        return self._write(
            "reschedule_appointment",
            "reschedule",
            f"POST /v1/appointments/{appointment_id}/reschedule",
            idempotency_key,
            {"if_match": version, "new_slot_id": new_slot_id, "requested_by": "PATIENT"},
            apply,
            if_match_used=version is not None,
        )

    def mark_unreachable(
        self,
        appointment_id: str,
        unreachable_reason: str,
        version: int,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        def apply() -> dict[str, Any]:
            appt = self._appointment(appointment_id)
            _check_version(appt, version)
            assert_unreachable_transition(appt["status"])
            appt.update(
                status="UNREACHABLE",
                unreachable_reason=unreachable_reason,
                attempt_count=appt["attempt_count"] + 1,
                version=appt["version"] + 1,
            )
            self.writes.append(
                (appointment_id, "UNREACHABLE", {"unreachable_reason": unreachable_reason})
            )
            return copy.deepcopy(appt)

        # §4.2.5: payload idempotency chỉ có body — replay với If-Match cũ vẫn trả 200 cũ
        return self._write(
            "mark_unreachable",
            "unreachable",
            f"POST /v1/appointments/{appointment_id}/unreachable",
            idempotency_key,
            {"unreachable_reason": unreachable_reason},
            apply,
            validate=lambda: _check_enum(
                unreachable_reason, UNREACHABLE_REASONS, "unreachable_reason"
            ),
            if_match_used=version is not None,
        )

    # --- Bên trong -----------------------------------------------------------------

    def _write(
        self,
        operation: str,
        op_label: str,
        endpoint: str,
        key: Optional[str],
        payload: dict[str, Any],
        apply: Callable[[], dict[str, Any]],
        validate: Optional[Callable[[], None]] = None,
        *,
        if_match_used: bool = False,
    ) -> dict[str, Any]:
        method, _, path = endpoint.partition(" ")
        with self._call(operation, method, path.removeprefix("/v1"), if_match_used=if_match_used):
            self.requests.append((key or "", op_label))
            fault = self._take_fault(operation)
            if fault is not None and not fault[1]:
                raise fault[0]
            # FastAPI validate body trước khi vào route → trước idempotency
            if validate is not None:
                validate()
            # Idempotency trước If-Match (mock: _idempotent_check chạy trước _get_appt/_check_version)
            fingerprint = json.dumps(payload, sort_keys=True)
            cache_key = f"{endpoint}:{key}"
            if key and cache_key in self._idempotency:
                cached_fingerprint, cached_body = self._idempotency[cache_key]
                if cached_fingerprint != fingerprint:
                    raise unprocessable(
                        "IDEMPOTENCY_CONFLICT", "Idempotency-Key reused with a different payload."
                    )
                body = copy.deepcopy(cached_body)
            else:
                body = apply()
                if key:
                    self._idempotency[cache_key] = (fingerprint, copy.deepcopy(body))
                if fault is not None:
                    # apply_first: mock đã ghi nhưng bot không nhận được phản hồi
                    raise fault[0]
        self._run_after(operation, body)
        return body

    def _appointment(self, appointment_id: str) -> dict[str, Any]:
        appt = self.appointments.get(appointment_id)
        if appt is None:
            raise not_found(f"appointment {appointment_id}")
        return appt

    def _open_slot(self, slot_id: str) -> Optional[dict[str, Any]]:
        if slot_id in self.taken_slots:
            return None
        for slot in self.slots:
            if slot.get("slot_id") == slot_id:
                return store.normalize_slot(slot)
        return None

    def _call(
        self, operation: str, method: str, path: str, *, if_match_used: bool = False
    ) -> CallRecorder:
        return CallRecorder(self, operation, method, path, if_match_used=if_match_used)


def _check_version(appt: dict[str, Any], if_match: Optional[int]) -> None:
    if if_match is not None and int(if_match) != int(appt["version"]):
        raise version_conflict()


def _check_enum(value: str, allowed: frozenset[str], field: str) -> None:
    if value not in allowed:
        raise validation_error(f"Request validation failed: {field}.")


def _paginate(items: list[dict[str, Any]], cursor: Optional[str], limit: int) -> Page:
    limit = max(PAGE_LIMIT_MIN, min(int(limit), PAGE_LIMIT_MAX))
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
