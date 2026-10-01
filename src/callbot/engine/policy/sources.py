"""Dữ liệu gốc Gateway trả về trong lượt — nguồn để Output Guard render lại câu thoại (R-01 §3.3).

Guard không đối chiếu với `ctx.slots` hay dict mà template nhận: cả hai có thể bị sửa tại chỗ
(`list_open_slots` trả shallow copy, `ctx.find_slot` trả thẳng dict trong `ctx.slots`). Registry giữ
bản `deepcopy` chụp ngay khi dữ liệu vào lượt:

- slot: đầu lượt (`ctx.slots` vừa nạp từ store), rồi thay bằng bản chụp sau mỗi lần `list_open_slots`;
- appointment: chụp ngay khi `get_actionable_appointment` trả về, trước khi Dialogue dùng.

Registry gắn với lượt qua ContextVar như `journal.bind_journal`; `SourceRecorder` không bind thì chỉ
chuyển tiếp lời gọi (unit test Dialogue).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import date, datetime
from typing import Any, Optional

from callbot.engine.session.context import CallContext
from callbot.engine.tools.clinic_gateway import ACTIONABLE_APPOINTMENT_STATUSES, ClinicGateway


class SourceRegistry:
    def __init__(self, slots: list[dict[str, Any]]) -> None:
        self._slots = deepcopy(slots)
        self._appointments: dict[str, dict[str, Any]] = {}

    @property
    def slots(self) -> list[dict[str, Any]]:
        """Snapshot slot mới nhất (bản sao — người gọi sửa cũng không đổi registry)."""
        return deepcopy(self._slots)

    @property
    def slot_ids(self) -> list[str]:
        return [slot["slot_id"] for slot in self._slots]

    def slot(self, slot_id: Optional[str]) -> Optional[dict[str, Any]]:
        found = next((slot for slot in self._slots if slot["slot_id"] == slot_id), None)
        return deepcopy(found) if found is not None else None

    def appointment(self, appointment_id: Optional[str]) -> Optional[dict[str, Any]]:
        found = self._appointments.get(appointment_id or "")
        return deepcopy(found) if found is not None else None

    def slots_intact(self, ctx: CallContext) -> bool:
        return ctx.slots == self._slots

    def restore_slots(self, ctx: CallContext) -> None:
        """Fallback không được giữ trạng thái đang vi phạm: đưa `ctx.slots` về dữ liệu Gateway gốc."""
        ctx.slots = deepcopy(self._slots)

    def record_slots(self, slots: list[dict[str, Any]]) -> None:
        self._slots = deepcopy(slots)

    def record_appointment(self, appointment: dict[str, Any]) -> None:
        self._appointments[appointment["appointment_id"]] = deepcopy(appointment)


_current: ContextVar[Optional[SourceRegistry]] = ContextVar("source_registry", default=None)


@contextmanager
def bind_sources(registry: SourceRegistry) -> Iterator[SourceRegistry]:
    token = _current.set(registry)
    try:
        yield registry
    finally:
        _current.reset(token)


class SourceRecorder:
    """Bọc các lệnh đọc Gateway mà Dialogue dùng để NÓI; chụp kết quả ngay khi Gateway trả về."""

    def __init__(self, gateway: ClinicGateway) -> None:
        self._gateway = gateway

    def get_actionable_appointment(
        self,
        ctx: CallContext,
        allowed_statuses: frozenset[str] = ACTIONABLE_APPOINTMENT_STATUSES,
    ) -> dict[str, Any]:
        appointment = self._gateway.get_actionable_appointment(ctx, allowed_statuses)
        registry = _current.get()
        if registry is not None:
            registry.record_appointment(appointment)
        return appointment

    def list_open_slots(
        self,
        ctx: CallContext,
        now: datetime,
        date_from: Optional[date] = None,
        clinic_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        slots = self._gateway.list_open_slots(ctx, now, date_from=date_from, clinic_id=clinic_id)
        registry = _current.get()
        if registry is not None:
            # Gateway thay toàn bộ ctx.slots; chụp đúng tập đó trước khi Dialogue kịp dùng
            registry.record_slots(ctx.slots)
        return slots
