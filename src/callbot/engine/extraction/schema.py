"""Interface dữ liệu của Information Extraction — thiết kế v1.1 §4.

Quy ước "không biết" (nguyên tắc 4, 5):
- `Field.skipped()`  — trường không áp dụng cho lượt này (vd. không trích tên khi bot đang hỏi ngày sinh).
- `Provenance.NONE`  — bộ trích xuất đã chạy nhưng không luật nào khớp; `value` là nhãn mặc định
  của trường (`Intent.NONE`, `Agreement.UNCLEAR`, ...) hoặc `None` với trường không có nhãn mặc định.
- `"INVALID"`         — có dữ liệu nhưng không hợp lệ (chỉ ở `dob`).
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Any, Generic, Literal, Optional, TypeVar, Union

from callbot.engine.types import CancelReason, Direction, PendingAction

T = TypeVar("T")

INVALID: Literal["INVALID"] = "INVALID"
# Contract: mọi mốc giờ tính theo +07:00
VN_TZ = timezone(timedelta(hours=7))


class Provenance(str, Enum):
    EXACT = "EXACT"  # luật khớp nguyên văn
    NORMALIZED = "NORMALIZED"  # khớp sau chuẩn hoá (Unicode, tiền tố lễ phép, số đọc)
    FALLBACK = "FALLBACK"  # Slot filling tên / LLM tuyến sau — bắt buộc có span
    NONE = "NONE"  # không trích được


class QuestionId(str, Enum):
    """Câu bot vừa hỏi. Session Manager lưu, Dialogue Manager đặt mỗi khi hỏi."""

    ASK_NAME = "ASK_NAME"
    ASK_DOB = "ASK_DOB"
    ASK_INTENT = "ASK_INTENT"
    # Outbound: "Anh chị có đến khám được theo lịch này không?" — câu trả lời có/không
    # chỉ dẫn tới CONFIRM_READBACK, không mở khóa lệnh ghi nào.
    ASK_ATTENDANCE = "ASK_ATTENDANCE"
    CONFIRM_READBACK = "CONFIRM_READBACK"  # §1.1.3
    OFFER_SLOTS = "OFFER_SLOTS"
    SLOT_READBACK = "SLOT_READBACK"  # §1.1.6, §1.1.10
    # "không" trần ở bước chọn slot: hỏi A/B nghe khung khác hay giữ lịch, không đoán (T-10 Q-4)
    SLOT_REFUSE_CHOICE = "SLOT_REFUSE_CHOICE"
    # Đã đọc / từ chối hết khung của yêu cầu hiện tại: hỏi ngày khác hay giữ lịch (T-10 §3.2)
    ASK_SLOT_PREFERENCE = "ASK_SLOT_PREFERENCE"
    CANCEL_RECONFIRM = "CANCEL_RECONFIRM"  # §1.1.4
    ASK_CANCEL_REASON = "ASK_CANCEL_REASON"


IDENTITY_QUESTIONS = frozenset({QuestionId.ASK_NAME, QuestionId.ASK_DOB})
CONFIRMATION_QUESTIONS = frozenset(
    {
        QuestionId.ASK_ATTENDANCE,
        QuestionId.CONFIRM_READBACK,
        QuestionId.SLOT_READBACK,
        QuestionId.CANCEL_RECONFIRM,
    }
)


class Intent(str, Enum):
    CONFIRM = "CONFIRM"  # chỉ outbound
    CANCEL = "CANCEL"
    RESCHEDULE = "RESCHEDULE"
    BOOK = "BOOK"  # chỉ inbound
    REQUEST_HUMAN = "REQUEST_HUMAN"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    REPEAT_REQUEST = "REPEAT_REQUEST"  # không tính vào §1.1.5
    NOT_PATIENT = "NOT_PATIENT"
    # Chỉ ở bước danh tính: người gọi nói rõ không nhớ / không muốn cung cấp tên, ngày sinh.
    # Bot hiểu câu này — không phải failed understanding §1.1.5 mà là xác minh không thực hiện được (§1.1.1).
    CANNOT_PROVIDE = "CANNOT_PROVIDE"
    NONE = "NONE"  # tính vào §1.1.5


class ClinicalLevel(str, Enum):
    EMERGENCY = "EMERGENCY"
    ADVICE_REQUEST = "ADVICE_REQUEST"
    MENTION = "MENTION"
    NONE = "NONE"


class Agreement(str, Enum):
    AGREE = "AGREE"
    REFUSE = "REFUSE"
    UNCLEAR = "UNCLEAR"


class LineSignal(str, Enum):
    """Trùng tên với `unreachable_reason` ở Phụ lục A (rev 1.1). `SILENCE` không có ở đây:
    im lặng đến từ `silence_ms` của harness, không phải từ lời nói (xem `ExtractionResult.silent`)."""

    VOICEMAIL = "VOICEMAIL"  # lời chào hộp thư thoại
    LINE_BUSY = "LINE_BUSY"  # thông báo tổng đài: thuê bao đang bận
    NO_ANSWER = "NO_ANSWER"  # thông báo tổng đài: không liên lạc được, ngoài vùng phủ sóng, số không có thực
    NONE = "NONE"


# MORE: xin nghe khung khác ("khung khác", "còn khung nào") — không có tiêu chí lọc (T-10)
SlotChoiceKind = Literal["MATCH", "AMBIGUOUS", "NO_MATCH", "MORE", "ANY"]
DayPeriod = Literal["MORNING", "NOON", "AFTERNOON", "EVENING"]
# Ngày người gọi nói nhưng không dùng được để tra (PRD R-30): đã qua, không tồn tại, quá rộng
# ("tháng sau"), hoặc thứ trần trùng hôm nay (hôm nay hay tuần sau?) -> hỏi lại, không đoán
DateIssue = Literal["PAST", "INVALID", "TOO_BROAD", "TODAY"]


@dataclass(frozen=True)
class SlotCriteria:
    """Tiêu chí lọc rút ra từ lời người gọi. Không bao giờ dựng thành mốc thời gian mới (SF-02)."""

    ordinal: Optional[int] = None  # 1-based trên danh sách đã đọc; -1 = "cuối"
    hours: Optional[frozenset[int]] = None  # giờ 24h ứng viên: "hai giờ rưỡi" -> {2, 14}
    minute: Optional[int] = None
    period: Optional[DayPeriod] = None
    weekday: Optional[int] = None  # 0 = thứ hai
    day: Optional[int] = None
    month: Optional[int] = None
    date_from: Optional[date] = None  # khoảng ngày, bao gồm hai đầu
    date_to: Optional[date] = None
    # Có giá trị thì không khung nào khớp; PAST / TODAY kèm ngày đó ở date_from = date_to
    date_issue: Optional[DateIssue] = None

    @property
    def empty(self) -> bool:
        return self == SlotCriteria()


@dataclass(frozen=True)
class SlotChoice:
    kind: SlotChoiceKind
    slot_ids: tuple[str, ...] = ()
    criteria: SlotCriteria = field(default_factory=SlotCriteria)

    @property
    def slot_id(self) -> Optional[str]:
        return self.slot_ids[0] if self.kind == "MATCH" else None


@dataclass(frozen=True)
class Field(Generic[T]):
    value: Optional[T]
    provenance: Provenance
    span: Optional[str] = (
        None  # đoạn transcript (đã chuẩn hoá) sinh ra giá trị — bắt buộc với FALLBACK
    )

    @classmethod
    def skipped(cls) -> "Field[Any]":
        return cls(None, Provenance.NONE)

    @classmethod
    def nothing(cls, default: Optional[T] = None) -> "Field[T]":
        return cls(default, Provenance.NONE)

    @property
    def found(self) -> bool:
        return self.provenance is not Provenance.NONE


DobValue = Union[date, Literal["INVALID"]]


@dataclass(frozen=True)
class TurnContext:
    """Những gì bộ trích xuất được biết về cuộc gọi.

    Nguyên tắc 2: KHÔNG có hồ sơ bệnh nhân (`verify.*`) hay chi tiết lịch hẹn ở đây.
    Slot từ `GET /slots` được phép — đó là tập ứng viên để lọc, không phải dữ liệu danh tính.
    """

    turn: int
    question_id: Optional[QuestionId]
    direction: Direction
    now: datetime  # thời điểm cuộc gọi, có múi giờ; dùng cho năm 2 chữ số và ngày tương đối
    slots: tuple[dict[str, Any], ...] = ()  # toàn bộ GET /slots của cuộc gọi
    presented_slot_ids: tuple[str, ...] = ()  # thứ tự bot đã đọc, cho "khung thứ hai"
    # Hai trường dưới thêm ở tầng ngữ nghĩa (T-05 §8.3.2), có mặc định để mọi bộ dựng
    # TurnContext cũ vẫn chạy. Đều là dữ liệu hội thoại, KHÔNG phải hồ sơ hay trạng thái lịch hẹn.
    pending_action: Optional[PendingAction] = None
    question_turn: Optional[int] = None  # lượt bot hỏi câu đang chờ; None nếu chưa hỏi câu nào
    # Nội dung câu hỏi đang chờ, chỉ có ở ASK_NAME: ngữ cảnh cho slot filling họ tên, không phải
    # nguồn chữ để lấy tên. None khi không ở ASK_NAME hoặc phiên không lưu nội dung câu hỏi.
    question_text: Optional[str] = None

    @property
    def today(self) -> date:
        return to_local(self.now).date()


@dataclass(frozen=True)
class ExtractionResult:
    turn: int
    question_id: Optional[QuestionId]
    transcript: str
    full_name: Field[str]
    dob: Field[DobValue]
    intent: Field[Intent]
    clinical: Field[ClinicalLevel]
    agreement: Field[Agreement]
    slot_choice: Field[SlotChoice]
    cancel_reason: Field[CancelReason]
    line_signal: Field[LineSignal]
    # Hợp đồng rev 1.1 §1.1.7: lượt im lặng (silence_ms > 0) KHÔNG phải failed understanding (§1.1.5).
    # Khi silent, mọi trường là skipped — Policy đếm vào bộ đếm im lặng, không đếm vào bộ đếm không hiểu.
    silent: bool = False

    @classmethod
    def only(
        cls,
        turn: int,
        question_id: Optional[QuestionId],
        transcript: str,
        *,
        line_signal: Optional[Field[LineSignal]] = None,
        silent: bool = False,
    ) -> "ExtractionResult":
        """Kết quả mà mọi trường đều skipped, trừ `line_signal` nếu có."""
        skipped = Field.skipped()
        return cls(
            turn,
            question_id,
            transcript,
            skipped,
            skipped,
            skipped,
            skipped,
            skipped,
            skipped,
            skipped,
            line_signal or skipped,
            silent,
        )

    def to_trace(self) -> dict[str, Any]:
        """Dạng JSON cho trace JSONL (§9): value, provenance, span của từng trường."""
        fields = (
            "full_name",
            "dob",
            "intent",
            "clinical",
            "agreement",
            "slot_choice",
            "cancel_reason",
            "line_signal",
        )
        return {
            "turn": self.turn,
            "question_id": self.question_id.value if self.question_id else None,
            "transcript": self.transcript,
            "silent": self.silent,
            **{name: _field_to_trace(getattr(self, name)) for name in fields},
        }


def to_local(moment: datetime) -> datetime:
    """Datetime không múi giờ được coi là giờ Việt Nam."""
    return moment.replace(tzinfo=VN_TZ) if moment.tzinfo is None else moment.astimezone(VN_TZ)


def _field_to_trace(item: Field[Any]) -> dict[str, Any]:
    return {"value": _jsonable(item.value), "provenance": item.provenance.value, "span": item.span}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, SlotChoice):
        criteria = {k: _jsonable(v) for k, v in vars(value.criteria).items() if v is not None}
        return {"kind": value.kind, "slot_ids": list(value.slot_ids), "criteria": criteria}
    if isinstance(value, frozenset):
        return sorted(value)
    return value
