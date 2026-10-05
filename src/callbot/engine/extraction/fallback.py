"""Tuyến sau (slot filling họ tên / LLM tập nhãn đóng) — thiết kế v1.1 §4, §5.1, §5.4.

Chỉ gọi khi tầng luật chưa hiểu hoặc chưa tách chắc ranh giới tên (`Provenance.NONE`),
không dùng để lật kết luận phủ định / phân vân / thông tin người khác. Mọi kết quả
tuyến sau đi qua `guard_fallback` — chốt chặn chống bịa đặt không phụ thuộc điểm tin cậy của mô hình:
`span` phải là chuỗi con của transcript sau chuẩn hoá, không thì coi như NONE.

Prompt của tuyến sau KHÔNG được chứa hồ sơ bệnh nhân hay chi tiết lịch hẹn (nguyên tắc 2).
Slot filling họ tên nhận thêm câu hỏi bot đang chờ làm ngữ cảnh; span vẫn phải nằm trong
câu trả lời của khách, không bao giờ lấy từ câu hỏi của bot.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Protocol, TypeVar

from callbot.engine.extraction.model_budget import report_model_status
from callbot.engine.extraction.schema import Agreement, Field, Intent, Provenance, QuestionId
from callbot.engine.extraction.text import clean

T = TypeVar("T")


class SlotFillingStatus(str, Enum):
    """Kết cục slot filling họ tên, gộp từ trạng thái chi tiết trong log cho người gọi."""

    ACCEPTED = "accepted"  # mô hình trả tên, qua được guard
    NO_NAME = "no_name"  # mô hình khẳng định không có tên (`full_name: null`)
    REJECTED = "rejected"  # mô hình trả tên nhưng không qua guard
    # timeout, lỗi transport, refusal, incomplete, invalid_response, hoặc không gọi được mô hình
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class SlotFillingResult:
    status: SlotFillingStatus
    field: Field[str]
    elapsed_ms: Optional[float] = None


class FallbackExtractor(Protocol):
    """Cài đặt có thể không hỗ trợ mọi trường — trả `None` nghĩa là "không xử lý trường này"."""

    def full_name(
        self,
        transcript: str,
        *,
        question_id: QuestionId = QuestionId.ASK_NAME,
        bot_question: Optional[str] = None,
    ) -> Optional[SlotFillingResult]:
        """`bot_question`: nội dung câu hỏi nghiệp vụ đang chờ; `None` khi phiên không có nội dung."""
        ...

    def intent(self, transcript: str, allowed: frozenset[Intent]) -> Optional[Field[Intent]]: ...

    def agreement(self, transcript: str, question_id: QuestionId) -> Optional[Field[Agreement]]: ...


def guard_fallback(result: Optional[Field[T]], transcript: str, default: Optional[T]) -> Field[T]:
    """Nhận kết quả tuyến sau chỉ khi có span thật sự nằm trong transcript."""
    if result is None or result.value is None or result.provenance is not Provenance.FALLBACK:
        if result is not None:
            report_model_status("invalid_response")
        return Field.nothing(default)
    if isinstance(default, Enum) and not isinstance(result.value, type(default)):
        report_model_status("invalid_response")
        return Field.nothing(default)
    span = clean(result.span or "")
    if not span or not _contains_words(clean(transcript), span):
        report_model_status("invalid_response")
        return Field.nothing(default)
    return Field(result.value, Provenance.FALLBACK, span=span)


def _contains_words(text: str, span: str) -> bool:
    return f" {span} " in f" {text} "
