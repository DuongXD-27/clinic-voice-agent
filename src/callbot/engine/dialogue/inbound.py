"""Mở đầu inbound: người gọi đã kết nối, thiếu hồ sơ thì chuyển nhân viên."""

from callbot.engine.dialogue import templates as t
from callbot.engine.dialogue.questions import ask
from callbot.engine.extraction.schema import QuestionId
from callbot.engine.session.context import CallContext
from callbot.engine.types import BotAction
from callbot.engine.verification.identity import IdentityVerifier


def opening(ctx: CallContext, verifier: IdentityVerifier) -> BotAction:
    """Tra cứu theo số gọi đến trước khi hỏi mở danh tính."""
    prepare = verifier.prepare(ctx)
    if prepare.transfer_reason is not None:
        # Không hỏi tên khi không có hồ sơ đối chiếu. Contract mở phiên không có outcome;
        # Policy.check_preconditions chuyển máy ở lượt 1 theo identity_lookup đã lưu.
        return BotAction(t.choose_static(ctx, t.GREETING_HANDOFF_INBOUND), "AWAITING_IDENTITY")
    return ask(ctx, QuestionId.ASK_NAME, t.GREETING_INBOUND, "AWAITING_IDENTITY")
