from typing import Any, Optional

import httpx


def clinic_error(status: int, code: str) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://clinic-mock.test/v1/appointments")
    response = httpx.Response(status, json={"error": {"code": code}}, request=request)
    return httpx.HTTPStatusError(code, request=request, response=response)


class FakeClinicAPI:
    """Clinic mock trong bộ nhớ, chỉ đủ để test engine không cần docker.

    Như mock thật: gửi lại cùng Idempotency-Key trả kết quả cũ, không ghi thêm.
    """

    def __init__(self) -> None:
        self.appointments: dict[str, dict[str, Any]] = {
            "apt_00417": {
                "appointment_id": "apt_00417",
                "status": "SCHEDULED",
                "clinic_id": "cl_vinmec",
                "starts_at": "2026-10-14T09:00:00+07:00",
                "department": "Nội tổng quát",
                "patient": {
                    "patient_id": "pt_3391",
                    "display_name": "N. V. A.",
                    "verify": {"full_name": "Nguyễn Văn A", "dob": "1978-03-14"},
                },
                "attempt_count": 0,
                "version": 3,
            }
        }
        self.slots = [
            {"slot_id": "slot_aa01", "starts_at": "2026-10-14T10:00:00+07:00"},
            {"slot_id": "slot_91d2", "starts_at": "2026-10-14T14:30:00+07:00"},
        ]
        # Test-only lookup fixture mirroring the patient attached to apt_00417.
        # Keeping one source record avoids inventing a second patient model.
        self.patients_by_phone: dict[str, list[dict[str, Any]]] = {
            "0912345600": [dict(self.appointments["apt_00417"]["patient"])]
        }
        self.patient_lookups: list[str] = []
        self.slot_reads = 0
        self.writes: list[tuple[str, str, dict[str, Any]]] = []
        # Mọi lệnh ghi nhận được, kể cả gửi lại (idempotency_key, thao tác)
        self.requests: list[tuple[str, str]] = []
        self.taken_slots: set[str] = set()
        self._replies: dict[str, dict[str, Any]] = {}

    def find_patient_by_phone(self, phone: str) -> dict[str, Any]:
        self.patient_lookups.append(phone)
        return {"patients": [dict(patient) for patient in self.patients_by_phone.get(phone, [])]}

    def get_slots(self, clinic_id: str, from_: str, to: str) -> dict[str, Any]:
        self.slot_reads += 1
        return {
            "slots": [dict(slot) for slot in self.slots if slot["slot_id"] not in self.taken_slots]
        }

    def get_appointment(self, appointment_id: str) -> dict[str, Any]:
        return dict(self.appointments[appointment_id])

    def create_appointment(self, patient_id, slot_id, idempotency_key=None):
        def apply() -> dict[str, Any]:
            if slot_id in self.taken_slots:
                raise clinic_error(409, "SLOT_TAKEN")
            appointment_id = f"apt_new_{len(self.appointments)}"
            slot = next(s for s in self.slots if s["slot_id"] == slot_id)
            self.appointments[appointment_id] = {
                "appointment_id": appointment_id,
                "status": "BOOKED",
                "starts_at": slot["starts_at"],
                "patient": {"patient_id": patient_id},
                "attempt_count": 0,
                "version": 1,
            }
            self.taken_slots.add(slot_id)
            self.writes.append((appointment_id, "BOOKED", {"slot_id": slot_id}))
            return dict(self.appointments[appointment_id])

        return self._idempotent(idempotency_key, "book", apply)

    def confirm_appointment(self, appointment_id, version, idempotency_key=None):
        return self._write(appointment_id, "CONFIRMED", {}, version, idempotency_key)

    def cancel_appointment(
        self, appointment_id, cancel_reason, version, idempotency_key=None, confirmed=False
    ):
        if not confirmed:
            raise clinic_error(409, "CONFIRMATION_REQUIRED")
        return self._write(
            appointment_id, "CANCELLED", {"cancel_reason": cancel_reason}, version, idempotency_key
        )

    def transfer_appointment(self, appointment_id, transfer_reason, version, idempotency_key=None):
        return self._write(
            appointment_id,
            "TRANSFERRED",
            {"transfer_reason": transfer_reason},
            version,
            idempotency_key,
        )

    def reschedule_appointment(self, appointment_id, new_slot_id, version, idempotency_key=None):
        def apply() -> dict[str, Any]:
            if new_slot_id in self.taken_slots:
                raise clinic_error(409, "SLOT_TAKEN")
            self.taken_slots.add(new_slot_id)
            return self._apply(appointment_id, "RESCHEDULED", {"new_slot_id": new_slot_id})

        return self._idempotent(idempotency_key, "reschedule", apply)

    def mark_unreachable(self, appointment_id, unreachable_reason, version, idempotency_key=None):
        def apply() -> dict[str, Any]:
            record = self.appointments[appointment_id]
            record["attempt_count"] += 1
            return self._apply(
                appointment_id, "UNREACHABLE", {"unreachable_reason": unreachable_reason}
            )

        return self._idempotent(idempotency_key, "unreachable", apply)

    def _write(self, appointment_id, status, extra, version, idempotency_key):
        return self._idempotent(
            idempotency_key, status, lambda: self._apply(appointment_id, status, extra)
        )

    def _idempotent(self, key: Optional[str], operation: str, apply) -> dict[str, Any]:
        self.requests.append((key or "", operation))
        if key is not None and key in self._replies:
            return dict(self._replies[key])
        result = apply()
        if key is not None:
            self._replies[key] = dict(result)
        return result

    def _apply(self, appointment_id: str, status: str, extra: dict[str, Any]) -> dict[str, Any]:
        record = self.appointments[appointment_id]
        record.update(status=status, version=record["version"] + 1, **extra)
        self.writes.append((appointment_id, status, extra))
        return dict(record)
