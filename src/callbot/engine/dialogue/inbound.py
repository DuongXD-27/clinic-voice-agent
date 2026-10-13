"""Mở đầu inbound: người gọi đã kết nối, thiếu hồ sơ thì chuyển nhân viên.

Không có `caller_number` (harness mentor gửi null, Listing 1): chưa tra được hồ sơ nhưng vẫn hỏi mở
tên rồi ngày sinh như thường (§1.1.9); sau ngày sinh Dialogue hỏi thêm số điện thoại đã đăng ký và
Verifier tra theo số đó (`IdentityVerifier.lookup_spoken_phone`). Có số gọi đến mà không ra hồ sơ:
chuyển máy ở lượt 1, không hỏi số khác.
"""

from callbot.engine.dialogue import templates as t
from callbot.engine.dialogue.questions import ask
from callbot.engine.extraction.schema import QuestionId
from callbot.engine.session.context import CallContext
from callbot.engine.types import BotAction
from callbot.engine.verification.identity import IdentityVerifier


def opening(ctx: CallContext, verifier: IdentityVerifier) -> BotAction:
    """Tra cứu theo số gọi đến trước khi hỏi mở danh tính."""
    prepare = verifier.prepare(ctx)
    # AWAITING_PHONE (không có caller_number) không có transfer_reason: hỏi tên như khi đã có hồ sơ
    if prepare.transfer_reason is not None:
        # Không hỏi tên khi không có hồ sơ đối chiếu. Contract mở phiên không có outcome;
        # Policy.check_preconditions chuyển máy ở lượt 1 theo identity_lookup đã lưu.
        return BotAction(t.choose_static(ctx, t.GREETING_HANDOFF_INBOUND), "AWAITING_IDENTITY")
    return ask(ctx, QuestionId.ASK_NAME, t.GREETING_INBOUND, "AWAITING_IDENTITY")
