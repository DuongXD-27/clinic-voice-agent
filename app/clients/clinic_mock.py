import uuid
from typing import Any, Optional

import httpx


class ClinicMockClient:
    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout)

    def find_patient_by_phone(self, phone: str) -> dict[str, Any]:
        response = self._client.get("/patients", params={"phone": phone})
        response.raise_for_status()
        return response.json()

    def get_slots(self, clinic_id: str, from_: str, to: str) -> dict[str, Any]:
        response = self._client.get(
            "/slots", params={"clinic_id": clinic_id, "from": from_, "to": to}
        )
        response.raise_for_status()
        return response.json()

    def get_appointment(self, appointment_id: str) -> dict[str, Any]:
        response = self._client.get(f"/appointments/{appointment_id}")
        response.raise_for_status()
        return response.json()

    def create_appointment(
        self, patient_id: str, slot_id: str, idempotency_key: Optional[str] = None
    ) -> dict[str, Any]:
        response = self._client.post(
            "/appointments",
            json={"patient_id": patient_id, "slot_id": slot_id},
            headers=self._write_headers(idempotency_key),
        )
        response.raise_for_status()
        return response.json()

    def confirm_appointment(
        self, appointment_id: str, version: int, idempotency_key: Optional[str] = None
    ) -> dict[str, Any]:
        response = self._client.post(
            f"/appointments/{appointment_id}/confirm",
            headers=self._write_headers(idempotency_key, version),
        )
        response.raise_for_status()
        return response.json()

    def cancel_appointment(
        self,
        appointment_id: str,
        cancel_reason: str,
        version: int,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        response = self._client.post(
            f"/appointments/{appointment_id}/cancel",
            json={"cancel_reason": cancel_reason},
            headers=self._write_headers(idempotency_key, version),
        )
        response.raise_for_status()
        return response.json()

    def transfer_appointment(
        self,
        appointment_id: str,
        transfer_reason: str,
        version: int,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        response = self._client.post(
            f"/appointments/{appointment_id}/transfer",
            json={"transfer_reason": transfer_reason},
            headers=self._write_headers(idempotency_key, version),
        )
        response.raise_for_status()
        return response.json()

    def reschedule_appointment(
        self,
        appointment_id: str,
        new_slot_id: str,
        version: int,
        idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        response = self._client.post(
            f"/appointments/{appointment_id}/reschedule",
            json={"new_slot_id": new_slot_id, "requested_by": "PATIENT"},
            headers=self._write_headers(idempotency_key, version),
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _write_headers(
        idempotency_key: Optional[str], version: Optional[int] = None
    ) -> dict[str, str]:
        headers = {"Idempotency-Key": idempotency_key or str(uuid.uuid4())}
        if version is not None:
            headers["If-Match"] = str(version)
        return headers
