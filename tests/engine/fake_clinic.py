from typing import Any, Optional


class FakeClinicAPI:
    """Clinic mock trong bộ nhớ, chỉ đủ để test engine không cần docker."""

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
        self.writes: list[tuple[str, str, dict[str, Any]]] = []

    def find_patient_by_phone(self, phone: str) -> dict[str, Any]:
        return {"patients": []}

    def get_slots(self, clinic_id: str, from_: str, to: str) -> dict[str, Any]:
        return {"slots": list(self.slots)}

    def get_appointment(self, appointment_id: str) -> dict[str, Any]:
        return dict(self.appointments[appointment_id])

    def create_appointment(self, patient_id: str, slot_id: str, idempotency_key: Optional[str] = None):
        raise NotImplementedError

    def confirm_appointment(self, appointment_id: str, version: int, idempotency_key: Optional[str] = None):
        return self._write(appointment_id, "CONFIRMED", {"idempotency_key": idempotency_key})

    def cancel_appointment(self, appointment_id, cancel_reason, version, idempotency_key=None):
        return self._write(appointment_id, "CANCELLED", {"cancel_reason": cancel_reason})

    def transfer_appointment(self, appointment_id, transfer_reason, version, idempotency_key=None):
        return self._write(appointment_id, "TRANSFERRED", {"transfer_reason": transfer_reason})

    def reschedule_appointment(self, appointment_id, new_slot_id, version, idempotency_key=None):
        return self._write(appointment_id, "RESCHEDULED", {"new_slot_id": new_slot_id})

    def _write(self, appointment_id: str, status: str, extra: dict[str, Any]) -> dict[str, Any]:
        record = self.appointments[appointment_id]
        record.update(status=status, version=record["version"] + 1, **extra)
        self.writes.append((appointment_id, status, extra))
        return dict(record)
