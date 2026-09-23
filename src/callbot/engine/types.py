"""Kiểu dữ liệu dùng chung của engine — enum theo Appendix A của contract."""

from dataclasses import asdict, dataclass
from typing import Any, Literal, Optional

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

# Hành động đang chờ xác nhận. Ở đây thay vì `session/context.py` để `extraction/` dùng được mà
# không tạo import vòng (session -> extraction.schema).
PendingAction = Literal["CONFIRM", "CANCEL", "RESCHEDULE", "BOOK"]

TransferReason = Literal[
    "IDENTITY_FAILED",
    "PATIENT_NOT_FOUND",
    "OUT_OF_SCOPE",
    "CLINICAL_QUESTION",
    "NOT_UNDERSTOOD",
    "PATIENT_REQUEST",
    "SYSTEM_ERROR",
]

UnreachableReason = Literal["SILENCE", "VOICEMAIL", "NO_ANSWER", "LINE_BUSY"]


@dataclass(frozen=True)
class CallStart:
    call_id: str
    direction: Direction
    appointment_id: Optional[str] = None
    caller_number: Optional[str] = None
    locale: str = "vi-VN"
    max_turns: int = 20

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CallStart":
        return cls(**data)


@dataclass(frozen=True)
class CallerInput:
    """Đầu vào engine cho một lượt, giữ nguyên như transport nhận được.

    Im lặng xác định bằng `silence_ms > 0` (Phụ lục A), không bằng text rỗng.
    """

    turn: int
    text: Optional[str] = None
    silence_ms: int = 0
    audio_url: Optional[str] = None
    # Metadata ASR khi đầu vào đến từ audio; text mode để None
    asr_confidence: Optional[float] = None

    @property
    def is_silence(self) -> bool:
        return self.silence_ms > 0

    @property
    def transcript(self) -> str:
        return "" if self.is_silence else (self.text or "")

    def fingerprint(self) -> dict[str, Any]:
        """Đầu vào đã qua validation, trước chuẩn hoá ngôn ngữ — so khớp khi gửi lại lượt.

        Không chuẩn hoá text: hai câu gần nghĩa vẫn là hai request khác nhau.
        """
        return {"text": self.text, "silence_ms": self.silence_ms, "audio_url": self.audio_url}


@dataclass
class BotAction:
    """Kết quả một lượt; tầng transport chuyển thành TurnResponse / audio."""

    utterance: str
    state: CallState
    ended: bool = False
    outcome: Optional[Outcome] = None
    transfer_reason: Optional[TransferReason] = None
    unreachable_reason: Optional[UnreachableReason] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BotAction":
        return cls(**data)
