"""Mở đầu outbound: phải đọc được lịch hợp lệ trước khi bắt đầu cuộc gọi đi."""

from callbot.engine.dialogue import templates as t
from callbot.engine.dialogue.questions import ask
from callbot.engine.errors import OutboundStartFailed
from callbot.engine.extraction.schema import QuestionId
from callbot.engine.session.context import CallContext
from callbot.engine.types import BotAction
from callbot.engine.verification.identity import IdentityVerifier


def opening(ctx: CallContext, verifier: IdentityVerifier) -> BotAction:
    """Đọc lịch theo appointment_id; lỗi thì dừng trước khi lưu phiên hoặc phát lời bot."""
    prepare = verifier.prepare(ctx)
    if prepare.transfer_reason is not None:
        # Chưa có cuộc gọi để chuyển máy. HTTP chuyển lỗi này thành OUTBOUND_START_FAILED.
        raise OutboundStartFailed(prepare.error_code)
    return ask(ctx, QuestionId.ASK_NAME, t.GREETING_OUTBOUND, "AWAITING_IDENTITY")
