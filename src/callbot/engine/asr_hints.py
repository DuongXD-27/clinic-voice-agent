"""Gợi ý hotword cho ASR ở lượt kế tiếp, theo câu bot vừa hỏi (`ctx.question`).

Kế hoạch: /mnt/project-files/asr-rui-ro/ke-hoach-hotword-theo-state.md. Chỉ 6 câu hỏi có gợi ý;
giá trị được bias đều còn bị engine kiểm lại sau đó (tên phải khớp cả ngày sinh, giờ phải nằm trong
GET /slots và được đọc lại). KHÔNG BAO GIỜ gợi ý ở ngày sinh (lớp chặn người lạ, SF-03) và ở các
câu xác nhận / lượt ghi (bias "đồng ý/hủy" là kéo "chưa đồng ý" thành "đồng ý", SF-05).

Cụm từ viết đúng dạng GipFormer trả ra: chữ HOA, số đọc thành chữ. Gợi ý có tên khách là PII:
không log, không đưa vào trace.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Optional

from callbot.engine.extraction.schema import CONFIRMATION_QUESTIONS, QuestionId, to_local
from callbot.engine.session.context import CallContext


@dataclass(frozen=True)
class AsrHints:
    phrases: tuple[str, ...] = ()
    # Lượt tên: chỉ nhận bản decode có hotword khi lệch bản không hotword tối đa 1 từ (SF-03).
    guard_one_word: bool = False

    def __bool__(self) -> bool:
        return bool(self.phrases)


NO_HINTS = AsrHints()

# Không có gợi ý, kể cả khi sau này ai đó thêm nhánh cho chúng (test chặn).
FORBIDDEN_QUESTIONS = frozenset({QuestionId.ASK_DOB}) | CONFIRMATION_QUESTIONS

INTENT_PHRASES = (
    "ĐẶT LỊCH",
    "ĐỔI LỊCH",
    "DỜI LỊCH",
    "HỦY LỊCH",
    "XÁC NHẬN LỊCH",
    "GẶP NHÂN VIÊN",
)
SLOT_REFUSE_PHRASES = ("GIỜ KHÁC", "GIỮ LỊCH CŨ", "DỪNG")
SLOT_PICK_PHRASES = ("KHUNG ĐẦU", "KHUNG SAU")
PERIOD_PHRASES = ("BUỔI SÁNG", "BUỔI CHIỀU", "TUẦN SAU")
# Cùng các cụm `extraction/cancel_reason.py` nhận được.
CANCEL_REASON_PHRASES = (
    "BẬN",
    "CÓ VIỆC",
    "ĐI CÔNG TÁC",
    "VỀ QUÊ",
    "KHÔNG ĐẾN ĐƯỢC",
    "KHỎI RỒI",
    "ĐỠ RỒI",
    "KHÔNG CẦN KHÁM NỮA",
    "KHÁM CHỖ KHÁC",
    "BỆNH VIỆN KHÁC",
    "PHÒNG KHÁM KHÁC",
    "ĐẮT QUÁ",
    "KHÔNG ĐỦ TIỀN",
)

_WEEKDAYS = ("THỨ HAI", "THỨ BA", "THỨ TƯ", "THỨ NĂM", "THỨ SÁU", "THỨ BẢY", "CHỦ NHẬT")
_DIGITS = ("KHÔNG", "MỘT", "HAI", "BA", "BỐN", "NĂM", "SÁU", "BẢY", "TÁM", "CHÍN")
_PERIODS = ((12, "SÁNG"), (18, "CHIỀU"), (24, "TỐI"))


def hints_for(ctx: CallContext) -> AsrHints:
    question = ctx.question
    if question is None or ctx.state == "ENDED":
        return NO_HINTS
    qid = question.question_id
    if qid in FORBIDDEN_QUESTIONS:
        return NO_HINTS
    if qid is QuestionId.ASK_NAME:
        names = [
            _upper(ref["full_name"])
            for ref in ctx.identity_reference
            if ref.get("verifiable") and ref.get("full_name")
        ]
        return AsrHints(_unique(names), guard_one_word=True)
    if qid is QuestionId.ASK_INTENT:
        return AsrHints(INTENT_PHRASES)
    if qid is QuestionId.OFFER_SLOTS:
        presented = [s for s in ctx.slots if s.get("slot_id") in ctx.presented_slot_ids]
        return AsrHints(_unique([*_slot_phrases(presented), *SLOT_PICK_PHRASES]))
    if qid is QuestionId.ASK_SLOT_PREFERENCE:
        days = [p for s in ctx.slots for p in _day_phrases(s)]
        return AsrHints(_unique([*days, *PERIOD_PHRASES]))
    if qid is QuestionId.SLOT_REFUSE_CHOICE:
        return AsrHints(SLOT_REFUSE_PHRASES)
    if qid is QuestionId.ASK_CANCEL_REASON:
        return AsrHints(CANCEL_REASON_PHRASES)
    return NO_HINTS


def spoken_number(value: int) -> str:
    """0–99 thành chữ như ASR trả ra: 21 -> "HAI MƯƠI MỐT", 15 -> "MƯỜI LĂM"."""
    if not 0 <= value < 100:
        raise ValueError(value)
    if value < 10:
        return _DIGITS[value]
    tens, unit = divmod(value, 10)
    head = "MƯỜI" if tens == 1 else f"{_DIGITS[tens]} MƯƠI"
    if unit == 0:
        return head
    if unit == 1:
        return f"{head} {'MỘT' if tens == 1 else 'MỐT'}"
    if unit == 5:
        return f"{head} LĂM"
    if unit == 4 and tens > 1:
        return f"{head} TƯ"
    return f"{head} {_DIGITS[unit]}"


def _slot_phrases(slots: Iterable[dict[str, Any]]) -> list[str]:
    phrases: list[str] = []
    for slot in slots:
        moment = _moment(slot)
        if moment is None:
            continue
        hour = moment.hour if moment.hour <= 12 else moment.hour - 12
        period = next(word for limit, word in _PERIODS if moment.hour < limit)
        clock = f"{spoken_number(hour)} GIỜ"
        if moment.minute:
            phrases.append(f"{clock} {spoken_number(moment.minute)} {period}")
            if moment.minute == 30:
                phrases.append(f"{clock} RƯỠI {period}")
        else:
            phrases.append(f"{clock} {period}")
        phrases.extend(_day_phrases(slot))
    return phrases


def _day_phrases(slot: dict[str, Any]) -> list[str]:
    moment = _moment(slot)
    if moment is None:
        return []
    return [_WEEKDAYS[moment.weekday()], f"NGÀY {spoken_number(moment.day)}"]


def _moment(slot: dict[str, Any]) -> Optional[datetime]:
    try:
        return to_local(datetime.fromisoformat(slot["starts_at"]))
    except (KeyError, TypeError, ValueError):
        return None


def _upper(text: str) -> str:
    return " ".join(text.upper().replace("/", " ").split())


def _unique(phrases: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(p for p in phrases if p))
