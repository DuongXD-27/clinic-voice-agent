"""Tool layer: mọi lệnh đọc/ghi clinic mock đi qua đây để guardrail luôn được áp dụng.

- Mỗi write đọc lại version mới nhất làm If-Match (§4.2.3)
- Idempotency-Key xác định theo call_id + action, retry không tạo bản ghi trùng
- SF-01 / SF-02 / SF-05 được kiểm tra trước khi gửi request
"""

from datetime import datetime, timedelta
from typing import Any

from callbot.engine.policy import guardrails
from callbot.engine.session.context import CallContext
from callbot.engine.tools.ports import ClinicAPI
from callbot.engine.types import CancelReason, TransferReason


class ClinicGateway:
    def __init__(self, api: ClinicAPI, clinic_id: str) -> None:
        self._api = api
        self._clinic_id = clinic_id

    # --- Đọc -----------------------------------------------------------------

    def get_appointment(self, ctx: CallContext) -> dict[str, Any]:
        guardrails.assert_target_appointment(ctx, ctx.target_appointment_id)
        return self._api.get_appointment(ctx.target_appointment_id)

    def find_patients_by_phone(self, phone: str) -> list[dict[str, Any]]:
        # TODO: xác nhận shape response của GET /patients với starter kit
        payload = self._api.find_patient_by_phone(phone)
        if isinstance(payload, list):
            return payload
        return payload.get("patients") or payload.get("items") or []

    def list_open_slots(self, ctx: CallContext, days_ahead: int = 7) -> list[dict[str, Any]]:
        """Chỉ nguồn slot hợp lệ để đề xuất; ghi lại id vào ctx cho SF-02."""
        now = datetime.now()
        payload = self._api.get_slots(
            self._clinic_id, now.isoformat(timespec="minutes"),
            (now + timedelta(days=days_ahead)).isoformat(timespec="minutes"),
        )
        slots = payload if isinstance(payload, list) else payload.get("slots", [])
        ctx.offered_slot_ids.update(slot["slot_id"] for slot in slots)
        return slots

    # --- Ghi -----------------------------------------------------------------

    def confirm(self, ctx: CallContext) -> dict[str, Any]:
        appointment_id, version = self._prepare_write(ctx)
        return self._api.confirm_appointment(appointment_id, version, self._key(ctx, "confirm"))

    def cancel(self, ctx: CallContext, reason: CancelReason) -> dict[str, Any]:
        guardrails.assert_cancel_reconfirmed(ctx)
        appointment_id, version = self._prepare_write(ctx)
        return self._api.cancel_appointment(appointment_id, reason, version, self._key(ctx, "cancel"))

    def reschedule(self, ctx: CallContext, new_slot_id: str) -> dict[str, Any]:
        guardrails.assert_slot_offered(ctx, new_slot_id)
        appointment_id, version = self._prepare_write(ctx)
        # 409 SLOT_TAKEN: đọc lại /slots và đề xuất lại, không retry mù (Listing 4)
        return self._api.reschedule_appointment(
            appointment_id, new_slot_id, version, self._key(ctx, f"resched-{new_slot_id}")
        )

    def transfer(self, ctx: CallContext, reason: TransferReason) -> dict[str, Any]:
        appointment_id, version = self._prepare_write(ctx)
        return self._api.transfer_appointment(appointment_id, reason, version, self._key(ctx, "transfer"))

    def book(self, ctx: CallContext, slot_id: str) -> dict[str, Any]:
        """§1.1.10: inbound, tạo đúng MỘT appointment trên slot đã đề xuất."""
        if ctx.call.direction != "inbound" or ctx.created_appointment_id is not None:
            raise guardrails.SevereFailureBlocked("SF-01", "Chỉ inbound mới được tạo 1 appointment")
        guardrails.assert_can_disclose(ctx)
        guardrails.assert_slot_offered(ctx, slot_id)
        if ctx.patient_id is None:
            raise ValueError("Chưa xác định patient_id")
        created = self._api.create_appointment(ctx.patient_id, slot_id, self._key(ctx, "book"))
        ctx.created_appointment_id = created["appointment_id"]
        return created

    def mark_unreachable(self, ctx: CallContext) -> None:
        # TODO: Table 3 không có endpoint cho UNREACHABLE / attempt_count — hỏi #residency-batch03 (§8.3)
        raise NotImplementedError

    def _prepare_write(self, ctx: CallContext) -> tuple[str, int]:
        appointment_id = ctx.target_appointment_id
        guardrails.assert_target_appointment(ctx, appointment_id)
        current = self._api.get_appointment(appointment_id)
        return appointment_id, int(current["version"])

    @staticmethod
    def _key(ctx: CallContext, action: str) -> str:
        return f"{ctx.call_id}-{action}"
