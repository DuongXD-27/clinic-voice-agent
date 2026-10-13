"""Kiểu dữ liệu dùng chung của engine — enum theo Appendix A của contract."""

from dataclasses import asdict, dataclass
from enum import Enum
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


# Lỗi kỹ thuật phía transport (R-39): lượt điều khiển, không có lời khách, luôn chuyển máy SYSTEM_ERROR.
ControlEvent = Literal["TTS_ERROR", "ASR_ERROR"]


class PhoneStatus(str, Enum):
    """Dial results supplied by a phone adapter, never inferred from speech."""

    NO_ANSWER = "NO_ANSWER"
    LINE_BUSY = "LINE_BUSY"


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
    phone_status: Optional[PhoneStatus] = None
    control_event: Optional[ControlEvent] = None

    def __post_init__(self) -> None:
        if self.control_event is not None:
            if type(self.turn) is not int or self.turn < 1:
                raise ValueError("control event requires a positive integer turn")
            if self.control_event not in ("TTS_ERROR", "ASR_ERROR"):
                raise ValueError("unknown control event")
            if (
                self.text is not None
                or self.audio_url is not None
                or self.silence_ms != 0
                or self.asr_confidence is not None
                or self.phone_status is not None
            ):
                raise ValueError("control event cannot be combined with caller input")
        if self.phone_status is not None:
            if type(self.turn) is not int or self.turn < 1:
                raise ValueError("phone status requires a positive integer turn")
            if not isinstance(self.phone_status, PhoneStatus):
                raise ValueError("phone_status must be a PhoneStatus")
            if (
                self.text is not None
                or self.audio_url is not None
                or self.silence_ms != 0
                or self.asr_confidence is not None
            ):
                raise ValueError("phone status cannot be combined with caller speech or silence")

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
        result = {"text": self.text, "silence_ms": self.silence_ms, "audio_url": self.audio_url}
        # Keep existing speech fingerprints compatible with stored turns.
        if self.phone_status is not None:
            result["phone_status"] = self.phone_status.value
        if self.control_event is not None:
            result["control_event"] = self.control_event
        return result


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


@dataclass(frozen=True)
class TTSRecovery:
    """Kết quả xử lý lỗi kỹ thuật giữa cuộc gọi (R-39, bảng 2.2 của plan 11/10).

    Phía khách luôn như nhau: phát `utterance` (luôn là câu TRANSFER cố định) rồi chuyển nhân viên.
    `action` là lượt điều khiển đã chạy; None khi không chạy lượt nào (phiên đã kết thúc, hoặc còn
    lệnh chờ đối soát). `preserve_business_outcome`: Clinic đã có kết quả của cuộc gọi, nhân viên
    không được làm lại. `reconciliation_required`: còn lệnh ghi chưa rõ kết quả.
    """

    utterance: str
    action: Optional[BotAction] = None
    preserve_business_outcome: bool = False
    reconciliation_required: bool = False
