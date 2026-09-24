"""Lưu câu hỏi đang chờ và tạo phản hồi dùng chung cho mọi luồng hội thoại."""

from typing import Optional

from callbot.engine.extraction.schema import QuestionId
from callbot.engine.session.context import CallContext, PendingAction, Question
from callbot.engine.types import BotAction, CallState


def ask(
    ctx: CallContext,
    question_id: QuestionId,
    text: str,
    state: CallState,
    action: Optional[PendingAction] = None,
    slot_id: Optional[str] = None,
) -> BotAction:
    """Ghi nội dung và lượt hỏi; SessionManager áp dụng state khi lưu phản hồi."""
    ctx.question = Question(question_id, text, ctx.turn, action=action, slot_id=slot_id)
    return BotAction(text, state)
