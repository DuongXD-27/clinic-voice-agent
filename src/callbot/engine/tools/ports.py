"""Cổng tới clinic mock (§4.2). clinic_mock_client.ClinicMockClient thoả mãn Protocol này."""

from typing import Any, Optional, Protocol


class ClinicAPI(Protocol):
    def find_patient_by_phone(self, phone: str) -> dict[str, Any]: ...

    def get_slots(self, clinic_id: str, from_: str, to: str) -> dict[str, Any]: ...

    def get_appointment(self, appointment_id: str) -> dict[str, Any]: ...

    def create_appointment(
        self, patient_id: str, slot_id: str, idempotency_key: Optional[str] = None
    ) -> dict[str, Any]: ...

    def confirm_appointment(
        self, appointment_id: str, version: int, idempotency_key: Optional[str] = None
    ) -> dict[str, Any]: ...

    def cancel_appointment(
        self,
        appointment_id: str,
        cancel_reason: str,
        version: int,
        idempotency_key: Optional[str] = None,
        confirmed: bool = False,
    ) -> dict[str, Any]: ...

    def transfer_appointment(
        self,
        appointment_id: str,
        transfer_reason: str,
        version: int,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]: ...

    def reschedule_appointment(
        self,
        appointment_id: str,
        new_slot_id: str,
        version: int,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]: ...

    def mark_unreachable(
        self,
        appointment_id: str,
        unreachable_reason: str,
        version: int,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]: ...
