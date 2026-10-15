"""Gợi ý hotword cho ASR ở lượt kế tiếp, theo câu bot vừa hỏi (`ctx.question`).

Kế hoạch: /mnt/project-files/asr-rui-ro/ke-hoach-hotword-theo-state.md. Chỉ lượt hỏi họ tên có gợi ý:
họ tên của mọi hồ sơ đã đọc từ clinic mock, kể cả hồ sơ không xác minh được (ngày sinh sai / thiếu) —
tên được bias vẫn phải khớp cả ngày sinh mới qua Verifier. Mọi câu hỏi khác (ngày sinh, ý định, khung
giờ, lý do hủy, xác nhận) decode không hotword.

Cụm từ viết đúng dạng GipFormer trả ra: chữ HOA. Gợi ý có tên khách là PII: không log, không đưa vào
trace.
"""

from dataclasses import dataclass
from typing import Iterable

from callbot.engine.extraction.schema import QuestionId
from callbot.engine.session.context import CallContext


@dataclass(frozen=True)
class AsrHints:
    phrases: tuple[str, ...] = ()
    # Lượt tên: chỉ nhận bản decode có hotword khi lệch bản không hotword tối đa 1 từ (SF-03).
    guard_one_word: bool = False

    def __bool__(self) -> bool:
        return bool(self.phrases)


NO_HINTS = AsrHints()


def hints_for(ctx: CallContext) -> AsrHints:
    question = ctx.question
    if question is None or ctx.state == "ENDED":
        return NO_HINTS
    if question.question_id is not QuestionId.ASK_NAME:
        return NO_HINTS
    names = [_upper(ref["full_name"]) for ref in ctx.identity_reference if ref.get("full_name")]
    return AsrHints(_unique(names), guard_one_word=True)


def _upper(text: str) -> str:
    return " ".join(text.upper().replace("/", " ").split())


def _unique(phrases: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(p for p in phrases if p))
