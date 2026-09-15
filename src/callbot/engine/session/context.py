from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal, Optional

from callbot.engine.types import CallStart, CallState, Outcome

IdentityStep = Literal["ASK_NAME", "ASK_DOB", "VERIFIED"]
PendingAction = Literal["CONFIRM", "CANCEL", "RESCHEDULE", "BOOK"]


@dataclass
class HistoryItem:
    turn: int
    role: Literal["bot", "caller"]
    text: str


@dataclass
class CallContext:
    """Trạng thái hội thoại của một cuộc gọi.

    §4.2.2: KHÔNG giữ trạng thái lịch hẹn (status, starts_at, version...) ở đây —
    luôn đọc lại từ clinic mock trước khi nói hoặc ghi.
    """

    call: CallStart
    state: CallState = "AWAITING_IDENTITY"
    turn: int = 0

    # Verification
    identity_step: IdentityStep = "ASK_NAME"
    claimed_name: Optional[str] = None
    claimed_dob: Optional[date] = None

    # Inbound: patient tìm qua GET /patients, appointment tạo bằng POST /appointments
    patient_id: Optional[str] = None
    created_appointment_id: Optional[str] = None

    # Dialogue
    pending_action: Optional[PendingAction] = None
    pending_slot_id: Optional[str] = None
    cancel_confirmations: int = 0
    # SF-02: chỉ slot GET /slots trả về trong CUỘC GỌI NÀY mới được đề xuất
    offered_slot_ids: set[str] = field(default_factory=set)
    presented_slots: list[dict[str, Any]] = field(default_factory=list)

    # Policy counters
    failed_understandings: int = 0
    silent_turns: int = 0

    outcome: Optional[Outcome] = None
    history: list[HistoryItem] = field(default_factory=list)

    @property
    def call_id(self) -> str:
        return self.call.call_id

    @property
    def identity_verified(self) -> bool:
        return self.identity_step == "VERIFIED"

    @property
    def ended(self) -> bool:
        return self.state == "ENDED"

    @property
    def target_appointment_id(self) -> Optional[str]:
        """Appointment duy nhất cuộc gọi được phép ghi (SF-01)."""
        if self.call.direction == "outbound":
            return self.call.appointment_id
        return self.created_appointment_id

    def record(self, role: Literal["bot", "caller"], text: str) -> None:
        self.history.append(HistoryItem(turn=self.turn, role=role, text=text))
