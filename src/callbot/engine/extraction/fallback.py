"""Tuyến sau (NER / LLM tập nhãn đóng) — thiết kế v1.1 §4, §5.1, §5.4.

Chỉ gọi khi tầng luật chưa hiểu hoặc chưa tách chắc ranh giới tên (`Provenance.NONE`),
không dùng để lật kết luận phủ định / phân vân / thông tin người khác. Mọi kết quả
tuyến sau đi qua `guard_fallback` — chốt chặn chống bịa đặt không phụ thuộc điểm tin cậy của mô hình:
`span` phải là chuỗi con của transcript sau chuẩn hoá, không thì coi như NONE.

Prompt của tuyến sau KHÔNG được chứa hồ sơ bệnh nhân hay chi tiết lịch hẹn (nguyên tắc 2).
"""

from typing import Optional, Protocol, TypeVar

from callbot.engine.extraction.schema import Agreement, Field, Intent, Provenance, QuestionId
from callbot.engine.extraction.text import clean

T = TypeVar("T")


class FallbackExtractor(Protocol):
    """Cài đặt có thể không hỗ trợ mọi trường — trả `None` nghĩa là "không xử lý trường này"."""

    def full_name(self, transcript: str) -> Optional[Field[str]]: ...

    def intent(self, transcript: str, allowed: frozenset[Intent]) -> Optional[Field[Intent]]: ...

    def agreement(self, transcript: str, question_id: QuestionId) -> Optional[Field[Agreement]]: ...


def guard_fallback(result: Optional[Field[T]], transcript: str, default: Optional[T]) -> Field[T]:
    """Nhận kết quả tuyến sau chỉ khi có span thật sự nằm trong transcript."""
    if result is None or result.value is None or result.provenance is not Provenance.FALLBACK:
        return Field.nothing(default)
    span = clean(result.span or "")
    if not span or not _contains_words(clean(transcript), span):
        return Field.nothing(default)
    return Field(result.value, Provenance.FALLBACK, span=span)


def _contains_words(text: str, span: str) -> bool:
    return f" {span} " in f" {text} "
