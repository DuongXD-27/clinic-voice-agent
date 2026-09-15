"""Kiểu dữ liệu dùng chung của engine — enum theo Appendix A của contract."""

from dataclasses import dataclass
from typing import Literal, Optional

CallState = Literal[
    "AWAITING_IDENTITY",
    "AWAITING_INTENT",
    "AWAITING_CONFIRMATION",
    "OFFERING_SLOTS",
    "CLOSING",
    "ENDED",
]

Outcome = Literal[
    "CONFIRMED",
    "CANCELLED",
    "RESCHEDULED",
    "TRANSFERRED",
    "UNREACHABLE",
    "BOOKED",
    "SCHEDULED",
]

Direction = Literal["inbound", "outbound"]

CancelReason = Literal[
    "PATIENT_UNAVAILABLE", "NO_LONGER_NEEDED", "WENT_ELSEWHERE", "COST", "UNSPECIFIED"
]

TransferReason = Literal[
    "IDENTITY_FAILED",
    "PATIENT_NOT_FOUND",
    "OUT_OF_SCOPE",
    "CLINICAL_QUESTION",
    "NOT_UNDERSTOOD",
    "PATIENT_REQUEST",
    "SYSTEM_ERROR",
]


@dataclass(frozen=True)
class CallStart:
    call_id: str
    direction: Direction
    appointment_id: Optional[str] = None
    caller_number: Optional[str] = None
    locale: str = "vi-VN"
    max_turns: int = 20


@dataclass(frozen=True)
class CallerInput:
    """Đầu vào engine cho một lượt — đã qua STT nên chỉ còn văn bản."""

    turn: int
    text: str = ""
    is_silence: bool = False
    asr_confidence: Optional[float] = None


@dataclass
class BotAction:
    """Kết quả một lượt; tầng transport chuyển thành TurnResponse / audio."""

    utterance: str
    state: CallState
    ended: bool = False
    outcome: Optional[Outcome] = None
    transfer_reason: Optional[TransferReason] = None
