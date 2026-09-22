"""Ngữ cảnh hội thoại của một cuộc gọi — lưu bền qua restart và nhiều worker (F-03).

Mọi trường phải tuần tự hoá được bằng `to_dict` / `from_dict`. Đổi cấu trúc -> tăng `SCHEMA_VERSION`.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal, Optional

from callbot.engine.extraction.schema import QuestionId
from callbot.engine.types import (
    CallStart,
    CallState,
    CancelReason,
    Outcome,
    PendingAction,
    TransferReason,
    UnreachableReason,
)

SCHEMA_VERSION = 1

IdentityStep = Literal["ASK_NAME", "ASK_DOB", "VERIFIED"]
# Kết quả tra cứu hồ sơ ở lượt 0 (T-01): LOADED = có dữ liệu chuẩn để đối chiếu
IdentityLookup = Literal["PENDING", "LOADED", "NO_PHONE", "NO_CANDIDATES", "UNAVAILABLE"]
# REQUEST: người gọi yêu cầu hành động (chỉ dùng cho hủy lịch, SF-05)
# CONFIRMATION: người gọi đồng ý câu hỏi xác nhận của hành động đang chờ
EvidenceKind = Literal["REQUEST", "CONFIRMATION"]


@dataclass
class HistoryItem:
    turn: int
    role: Literal["bot", "caller"]
    text: str


@dataclass(frozen=True)
class Question:
    """Câu hỏi nghiệp vụ gần nhất bot đã hỏi — IE diễn giải lượt sau theo `question_id`.

    Câu "em chưa hiểu" không thay câu hỏi này. Nhắc im lặng / xin nhắc lại hỏi lại nguyên văn câu này
    và đổi `turn` sang lượt nhắc (T-08).
    """

    question_id: QuestionId
    text: str
    turn: int
    action: Optional[PendingAction] = None
    slot_id: Optional[str] = None


@dataclass(frozen=True)
class ActionEvidence:
    """Bằng chứng cho một lệnh ghi; chỉ hợp lệ với đúng `action` + `slot_id` đang chờ."""

    kind: EvidenceKind
    action: PendingAction
    slot_id: Optional[str]
    turn: int
    question_id: Optional[QuestionId]
    question_turn: Optional[int]
    transcript: str
    label: str  # intent (REQUEST) hoặc agreement (CONFIRMATION)
    provenance: str
    span: Optional[str]


@dataclass
class CallContext:
    """Trạng thái hội thoại của một cuộc gọi.

    §4.2.2: KHÔNG giữ trạng thái lịch hẹn (status, starts_at, version...) ở đây —
    luôn đọc lại từ clinic mock trước khi nói hoặc ghi. Slot là kết quả GET /slots của cuộc gọi,
    dùng làm tập ứng viên (SF-02), không phải nguồn sự thật về lịch.
    """

    call: CallStart
    opened_at: datetime
    state: CallState = "AWAITING_IDENTITY"
    turn: int = 0

    # Verification
    identity_step: IdentityStep = "ASK_NAME"
    claimed_name: Optional[str] = None
    claimed_dob: Optional[date] = None
    # "Dữ liệu chuẩn nội bộ" đọc ở lượt 0 (§4.2.2 bản sao chỉ đọc): mỗi phần tử
    # {patient_id, full_name, dob, verifiable}. Outbound đúng 1; inbound mọi ứng viên GET /patients.
    # SF-03/§1.1.2: KHÔNG đưa vào build_turn_context (IE), trace hay lời thoại — Verifier đọc riêng.
    identity_lookup: IdentityLookup = "PENDING"
    identity_reference: list[dict[str, Any]] = field(default_factory=list)

    # Inbound: patient tìm qua GET /patients, appointment tạo bằng POST /appointments
    patient_id: Optional[str] = None
    created_appointment_id: Optional[str] = None

    # Dialogue
    question: Optional[Question] = None
    pending_action: Optional[PendingAction] = None
    selected_slot_id: Optional[str] = None
    evidence: list[ActionEvidence] = field(default_factory=list)
    cancel_reason: Optional[CancelReason] = None
    # SF-02: toàn bộ slot GET /slots trả về ở lần đọc gần nhất trong cuộc gọi này
    slots: list[dict[str, Any]] = field(default_factory=list)
    presented_slot_ids: list[str] = field(default_factory=list)

    # Policy counters
    failed_understandings: int = 0
    unclear_streak: int = 0
    silent_turns: int = 0

    outcome: Optional[Outcome] = None
    transfer_reason: Optional[TransferReason] = None
    unreachable_reason: Optional[UnreachableReason] = None
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

    @property
    def slot_ids(self) -> list[str]:
        return [slot["slot_id"] for slot in self.slots]

    def find_slot(self, slot_id: Optional[str]) -> Optional[dict[str, Any]]:
        return next((slot for slot in self.slots if slot["slot_id"] == slot_id), None)

    def record(self, role: Literal["bot", "caller"], text: str) -> None:
        self.history.append(HistoryItem(turn=self.turn, role=role, text=text))

    # --- Hành động chờ và bằng chứng --------------------------------------------

    def set_pending(self, action: PendingAction, slot_id: Optional[str] = None) -> None:
        """Đổi hành động hoặc slot làm mất hiệu lực mọi bằng chứng cũ.

        Đổi hành động còn xoá `cancel_reason`: lý do chỉ thuộc yêu cầu hủy đang chờ, không được
        đi theo người gọi sang nhánh khác rồi quay lại nhánh hủy (T-05 §3.2.5).
        """
        if action != self.pending_action or slot_id != self.selected_slot_id:
            self.evidence = []
        if action != self.pending_action:
            self.cancel_reason = None
        self.pending_action = action
        self.selected_slot_id = slot_id

    def select_slot(self, slot_id: Optional[str]) -> None:
        if self.pending_action not in ("RESCHEDULE", "BOOK"):
            raise ValueError(f"Không chọn slot khi hành động chờ là {self.pending_action}")
        self.set_pending(self.pending_action, slot_id)

    def clear_pending(self) -> None:
        """Người gọi từ chối / bỏ hành động: không còn gì được phép ghi."""
        self.pending_action = None
        self.selected_slot_id = None
        self.evidence = []
        self.cancel_reason = None
        self.presented_slot_ids = []

    def add_evidence(self, evidence: ActionEvidence) -> None:
        if evidence.action != self.pending_action or evidence.slot_id != self.selected_slot_id:
            raise ValueError("Bằng chứng không khớp hành động / slot đang chờ")
        self.evidence.append(evidence)

    def evidence_for(
        self, kind: EvidenceKind, action: PendingAction, slot_id: Optional[str] = None
    ) -> list[ActionEvidence]:
        if action != self.pending_action or slot_id != self.selected_slot_id:
            return []
        return [
            item
            for item in self.evidence
            if item.kind == kind and item.action == action and item.slot_id == slot_id
        ]

    # --- Tuần tự hoá ---------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "call": self.call.to_dict(),
            "opened_at": self.opened_at.isoformat(),
            "state": self.state,
            "turn": self.turn,
            "identity_step": self.identity_step,
            "claimed_name": self.claimed_name,
            "claimed_dob": self.claimed_dob.isoformat() if self.claimed_dob else None,
            "identity_lookup": self.identity_lookup,
            "identity_reference": [dict(item) for item in self.identity_reference],
            "patient_id": self.patient_id,
            "created_appointment_id": self.created_appointment_id,
            "question": _question_to_dict(self.question),
            "pending_action": self.pending_action,
            "selected_slot_id": self.selected_slot_id,
            "evidence": [_evidence_to_dict(item) for item in self.evidence],
            "cancel_reason": self.cancel_reason,
            "slots": [dict(slot) for slot in self.slots],
            "presented_slot_ids": list(self.presented_slot_ids),
            "failed_understandings": self.failed_understandings,
            "unclear_streak": self.unclear_streak,
            "silent_turns": self.silent_turns,
            "outcome": self.outcome,
            "transfer_reason": self.transfer_reason,
            "unreachable_reason": self.unreachable_reason,
            "history": [
                {"turn": item.turn, "role": item.role, "text": item.text} for item in self.history
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CallContext":
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ValueError(f"Context schema {version} không được hỗ trợ (cần {SCHEMA_VERSION})")
        return cls(
            call=CallStart.from_dict(data["call"]),
            opened_at=datetime.fromisoformat(data["opened_at"]),
            state=data["state"],
            turn=data["turn"],
            identity_step=data["identity_step"],
            claimed_name=data["claimed_name"],
            claimed_dob=date.fromisoformat(data["claimed_dob"]) if data["claimed_dob"] else None,
            # Hai khóa thêm ở T-01, đọc bằng .get để phiên lưu trước đó (schema 1 cũ) vẫn mở được
            identity_lookup=data.get("identity_lookup", "PENDING"),
            identity_reference=[dict(item) for item in data.get("identity_reference", [])],
            patient_id=data["patient_id"],
            created_appointment_id=data["created_appointment_id"],
            question=_question_from_dict(data["question"]),
            pending_action=data["pending_action"],
            selected_slot_id=data["selected_slot_id"],
            evidence=[_evidence_from_dict(item) for item in data["evidence"]],
            cancel_reason=data["cancel_reason"],
            slots=[dict(slot) for slot in data["slots"]],
            presented_slot_ids=list(data["presented_slot_ids"]),
            failed_understandings=data["failed_understandings"],
            unclear_streak=data["unclear_streak"],
            silent_turns=data["silent_turns"],
            outcome=data["outcome"],
            transfer_reason=data["transfer_reason"],
            unreachable_reason=data["unreachable_reason"],
            history=[HistoryItem(**item) for item in data["history"]],
        )


def _question_to_dict(question: Optional[Question]) -> Optional[dict[str, Any]]:
    if question is None:
        return None
    return {
        "question_id": question.question_id.value,
        "text": question.text,
        "turn": question.turn,
        "action": question.action,
        "slot_id": question.slot_id,
    }


def _question_from_dict(data: Optional[dict[str, Any]]) -> Optional[Question]:
    if data is None:
        return None
    return Question(**{**data, "question_id": QuestionId(data["question_id"])})


def _evidence_to_dict(item: ActionEvidence) -> dict[str, Any]:
    return {
        "kind": item.kind,
        "action": item.action,
        "slot_id": item.slot_id,
        "turn": item.turn,
        "question_id": item.question_id.value if item.question_id else None,
        "question_turn": item.question_turn,
        "transcript": item.transcript,
        "label": item.label,
        "provenance": item.provenance,
        "span": item.span,
    }


def _evidence_from_dict(data: dict[str, Any]) -> ActionEvidence:
    question_id = QuestionId(data["question_id"]) if data["question_id"] else None
    return ActionEvidence(**{**data, "question_id": question_id})
