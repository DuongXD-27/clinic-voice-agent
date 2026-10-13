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


class SlotAct(str, Enum):
    """Model đọc câu trả lời ở 4 câu hỏi chọn khung (plan `t10-slot-semantic-jev-2026-10-12.md` §4.6).

    Chỉ là chỉ dẫn hỏi lại / đọc câu chốt / tra khung — không nhãn nào mở khóa lệnh ghi.
    """

    PICK = "PICK"  # chọn khung thứ n của trang vừa đọc -> câu chốt, không ghi thẳng
    TIME = "TIME"  # nêu thời gian muốn (đoạn trong `slot_request`) -> luật tra / chọn
    MORE = "MORE"  # nghe khung khác
    ANY = "ANY"  # để bot chọn
    REFUSE = "REFUSE"  # không nhận khung vừa đọc
    KEEP_OLD_UNSURE = "KEEP_OLD_UNSURE"  # có thể muốn giữ lịch cũ -> câu A/B, không đoán
    CONFIRM = "CONFIRM"  # đồng ý ở câu chốt -> chỉ nhắc nói "đồng ý" (model không mở khóa ghi)
    CANCEL = "CANCEL"  # chuyển sang hủy, vẫn cần xác nhận lần hai
    OUT_OF_SCOPE = "OUT_OF_SCOPE"  # Policy chuyển máy
    UNCLEAR = "UNCLEAR"  # câu hỏi / mơ hồ / chưa quyết -> hỏi lại đúng câu đang chờ


class Agreement(str, Enum):
    AGREE = "AGREE"
    REFUSE = "REFUSE"
    UNCLEAR = "UNCLEAR"


class LineSignal(str, Enum):
    """Speech can identify voicemail only. Silence uses silence_ms; dial results use PhoneStatus."""

    VOICEMAIL = "VOICEMAIL"  # lời chào hộp thư thoại
    NONE = "NONE"


class IdentityStatus(str, Enum):
    PRESENT = "PRESENT"  # CÓ: value and verbatim span
    ABSENT = "ABSENT"  # KHÔNG CÓ
    MULTIPLE = "MULTIPLE"  # NHIỀU GIÁ TRỊ
    UNCERTAIN = "UNCERTAIN"  # KHÔNG CHẮC


@dataclass(frozen=True)
class IdentityValue(Generic[T]):
    status: IdentityStatus
    value: Optional[T] = None
    span: Optional[str] = None

    def __post_init__(self) -> None:
        if self.status is IdentityStatus.PRESENT and (self.value is None or not self.span):
            raise ValueError("PRESENT identity requires a value and a verbatim span")
        if self.status is not IdentityStatus.PRESENT and (self.value is not None or self.span):
            raise ValueError("Only PRESENT identity can carry a value or span")


# MORE: xin nghe khung khác ("khung khác", "còn khung nào") — không có tiêu chí lọc (T-10)
SlotChoiceKind = Literal["MATCH", "AMBIGUOUS", "NO_MATCH", "MORE", "ANY"]
DayPeriod = Literal["MORNING", "NOON", "AFTERNOON", "EVENING"]
# Ngày người gọi nói nhưng không dùng được để tra (PRD R-30): đã qua, không tồn tại, quá rộng
# ("tháng sau"), hoặc thứ trần trùng hôm nay (hôm nay hay tuần sau?) -> hỏi lại, không đoán
DateIssue = Literal["PAST", "INVALID", "TOO_BROAD", "TODAY"]
# "sớm hơn" / "muộn hơn" so với lịch đang đổi
Relative = Literal["EARLIER", "LATER"]


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
    # Khoảng giờ trong ngày, tính bằng phút từ 0h: "từ 10 giờ 30" -> not_before = 630 ("sau" thì
    # 631), "trước 10 giờ 30" -> before = 630. Không phải giờ chính xác.
    not_before: Optional[int] = None
    before: Optional[int] = None
    # "sớm hơn / muộn hơn" so với lịch đang đổi. IE không biết giờ lịch hẹn (nguyên tắc 2): Dialogue gắn
    # mốc vào `earlier_than` / `later_than` (`anchor_relative`). Chưa có mốc thì không khung nào khớp —
    # là yêu cầu mới, không phải chọn khung.
    relative: Optional[Relative] = None
    earlier_than: Optional[datetime] = None  # khung phải bắt đầu trước mốc này
    later_than: Optional[datetime] = None  # khung phải bắt đầu sau mốc này

    @property
    def empty(self) -> bool:
        return self == SlotCriteria()


@dataclass(frozen=True)
class SlotChoice:
    kind: SlotChoiceKind
    slot_ids: tuple[str, ...] = ()
    criteria: SlotCriteria = field(default_factory=SlotCriteria)
    # Câu có loại trừ ("không lấy ngày 14, ngày 15 đi"): khung bị loại (id luật dò trên GET /slots) và đoạn
    # câu nêu phần khách muốn. Dialogue bỏ các khung bị loại (V-9) và tạo yêu cầu mới từ đoạn muốn, không
    # đọc lại nguyên câu — nếu không thì mời đúng ngày khách vừa loại (review 12-10 B13).
    excluded_ids: tuple[str, ...] = ()
    request: Optional[str] = None

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
    asr_confidence: Optional[float] = None

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
    name_identity: Optional[IdentityValue[str]] = None
    dob_identity: Optional[IdentityValue[date]] = None
    model_status: Optional[str] = None
    # Model đã đọc lượt này (None: chỉ luật). `model_backup_for`: provider chính đã lỗi dịch vụ, provider
    # dự phòng `model_provider` trả lời thay (semantic_failover).
    model_provider: Optional[str] = None
    model_name: Optional[str] = None
    model_backup_for: Optional[str] = None
    confirmation_conflict: bool = False
    # Câu đọc lịch mâu thuẫn mà model đọc là nhu cầu đổi / hủy (route NEED_CONFLICT): Dialogue đi nhánh
    # nhu cầu thay vì hỏi lại có/không.
    need_over_conflict: bool = False
    # Bước danh tính, lượt không có tên / ngày sinh: model đọc là người gọi HỎI (route IDENTITY_TURN) —
    # "lịch khám của tôi mấy giờ?", "bên nào gọi?". Dialogue trả lời cần xác minh trước.
    caller_question: bool = False
    # Outbound, bước danh tính: ý định hủy (và lý do) hoặc đổi lịch nói gộp với tên / ngày sinh — "tôi là
    # Nguyễn Văn A, sinh ..., gọi để hủy lịch vì đi công tác" (QC qc-cn-08), "..., tôi muốn đổi sang chiều
    # ngày 14" (PRD R-43). Không phải `intent`: Policy và Dialogue không dùng trước khi xác minh xong;
    # Dialogue chỉ giữ lại để đi thẳng vào luồng đó sau VERIFIED.
    # NONE có span: lượt định danh còn nội dung khác ngoài tên / ngày sinh (đổi ý, chưa quyết...): bỏ
    # yêu cầu đã giữ.
    deferred_intent: Field[Intent] = field(default_factory=Field.skipped)
    deferred_cancel_reason: Field[CancelReason] = field(default_factory=Field.skipped)
    # Đổi lịch: lời yêu cầu đã bỏ tên và ngày sinh (tiêu chí thời gian), giữ dấu câu ("20/10", "15:30")
    deferred_request: Optional[str] = None
    # Câu hỏi chọn khung: đoạn câu là câu trả lời về thời gian (vế sau lời bỏ, bỏ vế điều kiện ở đầu), giữ
    # dấu câu. IE tìm khung trên đoạn này và Dialogue tạo yêu cầu mới từ chính đoạn này — một nguồn cho cả
    # hai tầng ("9 giờ thì thôi, cho tôi ngày 16" -> "cho tôi ngày 16"). None ở các câu hỏi khác.
    slot_request: Optional[str] = None
    # Tầng model của câu chọn khung (plan Jev §4): nhãn model đã qua kiểm, và route đã gọi model ở lượt
    # này (`RouteReason` / `SlotRouteReason`) để `extract()` / `respond()` phân biệt đường lỗi (§4.7).
    slot_act: Optional[SlotAct] = None
    model_route: Optional[str] = None

    @property
    def model_failed(self) -> bool:
        return self.model_status in {"TIMEOUT", "ERROR", "INVALID"}

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
            "deferred_intent",
            "deferred_cancel_reason",
        )
        return {
            "turn": self.turn,
            "question_id": self.question_id.value if self.question_id else None,
            "transcript": self.transcript,
            "silent": self.silent,
            **{name: _field_to_trace(getattr(self, name)) for name in fields},
            "name_identity": _identity_to_trace(self.name_identity),
            "dob_identity": _identity_to_trace(self.dob_identity),
            "model_status": self.model_status,
            "model_provider": self.model_provider,
            "model_name": self.model_name,
            "model_backup_for": self.model_backup_for,
            "slot_act": self.slot_act.value if self.slot_act else None,
            "model_route": self.model_route,
        }


def to_local(moment: datetime) -> datetime:
    """Datetime không múi giờ được coi là giờ Việt Nam."""
    return moment.replace(tzinfo=VN_TZ) if moment.tzinfo is None else moment.astimezone(VN_TZ)


def _field_to_trace(item: Field[Any]) -> dict[str, Any]:
    return {"value": _jsonable(item.value), "provenance": item.provenance.value, "span": item.span}


def _identity_to_trace(item: Optional[IdentityValue[Any]]) -> Optional[dict[str, Any]]:
    if item is None:
        return None
    return {"status": item.status.value, "value": _jsonable(item.value), "span": item.span}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, SlotChoice):
        criteria = {k: _jsonable(v) for k, v in vars(value.criteria).items() if v is not None}
        traced = {"kind": value.kind, "slot_ids": list(value.slot_ids), "criteria": criteria}
        if value.excluded_ids:
            traced["excluded_ids"] = list(value.excluded_ids)
        return traced
    if isinstance(value, frozenset):
        return sorted(value)
    return value


def compact_json_schema(schema: dict[str, Any], model: type) -> None:
    """`json_schema_extra` cho model gửi Structured Outputs: bỏ docstring và `title` tự sinh.

    Chúng không thêm ràng buộc (strict đã có `additionalProperties` / `required`) nhưng tốn token
    mỗi request và đưa ghi chú nội bộ của class vào prompt."""
    schema.pop("description", None)
    schema.pop("title", None)
    for prop in schema.get("properties", {}).values():
        prop.pop("title", None)
