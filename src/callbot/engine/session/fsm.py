"""State machine hội thoại (Phụ lục A) và kiểm tra đồng nhất trước khi đổi state / ghi Clinic.

State ở đây chỉ là state HỘI THOẠI. Trạng thái xử lý kỹ thuật của lượt (đang xử lý, cần đối soát)
nằm ở bản ghi lượt trong session store, không thêm vào enum HTTP.
"""

from typing import Optional

from callbot.engine.extraction.schema import CONFIRMATION_QUESTIONS, QuestionId
from callbot.engine.session.context import CallContext, PendingAction
from callbot.engine.types import CallState

TRANSITIONS: dict[CallState, set[CallState]] = {
    "AWAITING_IDENTITY": {
        "AWAITING_IDENTITY",
        "AWAITING_INTENT",
        # Yêu cầu hủy nói cùng lượt danh tính: xác minh xong hỏi thẳng câu xác nhận hủy (QC qc-cn-08).
        # Vẫn chịu kiểm tra "state khác AWAITING_IDENTITY cần xác minh xong" bên dưới.
        "AWAITING_CONFIRMATION",
        "OFFERING_SLOTS",
        "CLOSING",
        "ENDED",
    },
    "AWAITING_INTENT": {
        "AWAITING_INTENT",
        "AWAITING_CONFIRMATION",
        "OFFERING_SLOTS",
        "CLOSING",
        "ENDED",
    },
    "AWAITING_CONFIRMATION": {
        "AWAITING_CONFIRMATION",
        "AWAITING_INTENT",
        "OFFERING_SLOTS",
        "CLOSING",
        "ENDED",
    },
    "OFFERING_SLOTS": {
        "OFFERING_SLOTS",
        "AWAITING_CONFIRMATION",
        "AWAITING_INTENT",
        "CLOSING",
        "ENDED",
    },
    "CLOSING": {"ENDED"},
    # Trạng thái cuối: không mở lại, kể cả khi harness gửi lại call_id
    "ENDED": set(),
}

_SLOT_ACTIONS = frozenset({"RESCHEDULE", "BOOK"})

# Câu hỏi mà câu trả lời AGREE mở khóa lệnh ghi của từng hành động
CONFIRMATION_QUESTION_FOR: dict[PendingAction, QuestionId] = {
    "CONFIRM": QuestionId.CONFIRM_READBACK,
    "CANCEL": QuestionId.CANCEL_RECONFIRM,
    "RESCHEDULE": QuestionId.SLOT_READBACK,
    "BOOK": QuestionId.SLOT_READBACK,
}

# Outbound gộp tóm tắt lịch + đọc lại + hỏi đến được không vào một lượt (Figure 0 rev 1.1),
# nên xác nhận đến khám được ghi cả từ AWAITING_INTENT.
_WRITE_STATES: dict[PendingAction, frozenset[CallState]] = {
    "CONFIRM": frozenset({"AWAITING_INTENT", "AWAITING_CONFIRMATION"}),
    "CANCEL": frozenset({"AWAITING_CONFIRMATION"}),
    "RESCHEDULE": frozenset({"AWAITING_CONFIRMATION"}),
    "BOOK": frozenset({"AWAITING_CONFIRMATION"}),
}


class IllegalTransition(Exception):
    pass


class InconsistentSession(IllegalTransition):
    pass


def ensure_transition(current: CallState, target: CallState) -> None:
    if target not in TRANSITIONS[current]:
        raise IllegalTransition(f"{current} -> {target}")


def check_invariants(ctx: CallContext, state: Optional[CallState] = None) -> None:
    """Ràng buộc giữa state, bước xác minh, hành động chờ, slot và outcome."""
    state = state or ctx.state
    problems: list[str] = []

    if state == "ENDED":
        if ctx.outcome is None:
            problems.append("ENDED cần outcome")
    else:
        if ctx.outcome is not None:
            problems.append(f"{state} không được có outcome")
        if state != "AWAITING_IDENTITY" and not ctx.identity_verified:
            problems.append(f"{state} cần xác minh danh tính xong")

    if ctx.identity_verified:
        # T-02: xác minh chỉ có nghĩa khi đã đối chiếu với hồ sơ đọc ở lượt 0 và biết đúng bệnh nhân
        if ctx.identity_lookup != "LOADED":
            problems.append(f"đã xác minh nhưng tra cứu hồ sơ là {ctx.identity_lookup}")
        if not ctx.patient_id:
            problems.append("đã xác minh nhưng chưa có patient_id")

    if state == "AWAITING_IDENTITY":
        if ctx.identity_verified:
            problems.append("AWAITING_IDENTITY nhưng đã xác minh")
        if ctx.pending_action is not None:
            problems.append("chưa xác minh không được có hành động chờ")

    if state == "AWAITING_INTENT" and ctx.pending_action is not None:
        # Ngoại lệ 1: đồng ý câu tóm tắt gộp đọc lại (Figure 0) -> ghi CONFIRMED ngay lượt này.
        # Ngoại lệ 2: đã đọc hết khung của yêu cầu -> hỏi ngày khác, vẫn giữ việc đổi / đặt lịch (T-10).
        question = ctx.question.question_id if ctx.question else None
        readback = ctx.pending_action == "CONFIRM" and question is QuestionId.CONFIRM_READBACK
        new_request = (
            ctx.pending_action in _SLOT_ACTIONS and question is QuestionId.ASK_SLOT_PREFERENCE
        )
        if not (readback or new_request):
            problems.append("AWAITING_INTENT không được có hành động chờ")

    if state == "OFFERING_SLOTS":
        if ctx.pending_action not in _SLOT_ACTIONS:
            problems.append("OFFERING_SLOTS cần hành động đổi / đặt lịch")
        if not ctx.presented_slot_ids or not set(ctx.presented_slot_ids) <= set(ctx.slot_ids):
            problems.append("OFFERING_SLOTS cần slot đã đọc nằm trong GET /slots")

    if state == "AWAITING_CONFIRMATION":
        if ctx.pending_action is None:
            problems.append("AWAITING_CONFIRMATION cần hành động chờ")
        if ctx.question is None or ctx.question.question_id not in CONFIRMATION_QUESTIONS:
            problems.append("AWAITING_CONFIRMATION cần câu hỏi xác nhận")
        if ctx.pending_action in _SLOT_ACTIONS and ctx.find_slot(ctx.selected_slot_id) is None:
            problems.append("xác nhận slot cần slot nằm trong GET /slots")

    if ctx.selected_slot_id is not None and ctx.pending_action not in _SLOT_ACTIONS:
        problems.append("chỉ đổi / đặt lịch mới có slot đang chọn")

    if problems:
        raise InconsistentSession(f"{ctx.call_id} ({state}): " + "; ".join(problems))


def check_write(ctx: CallContext, action: PendingAction, slot_id: Optional[str] = None) -> None:
    """Chạy ngay trước lệnh ghi nghiệp vụ; bằng chứng xác nhận do guardrails kiểm tra riêng."""
    check_invariants(ctx)
    if ctx.business_write_blocked:
        raise InconsistentSession(f"{ctx.call_id}: model failure blocks business writes this turn")
    if ctx.ended:
        raise InconsistentSession(f"{ctx.call_id}: phiên đã kết thúc")
    if not ctx.identity_verified:
        raise InconsistentSession(f"{ctx.call_id}: chưa xác minh danh tính")
    if ctx.pending_action != action:
        raise InconsistentSession(
            f"{ctx.call_id}: ghi {action}, hành động chờ {ctx.pending_action}"
        )
    if ctx.state not in _WRITE_STATES[action]:
        raise InconsistentSession(f"{ctx.call_id}: không ghi {action} ở {ctx.state}")
    if ctx.selected_slot_id != slot_id:
        raise InconsistentSession(
            f"{ctx.call_id}: ghi slot {slot_id}, slot đang chọn {ctx.selected_slot_id}"
        )
    if ctx.question is None or ctx.question.question_id != CONFIRMATION_QUESTION_FOR[action]:
        raise InconsistentSession(f"{ctx.call_id}: câu hỏi đang chờ không xác nhận {action}")


def check_closing_write(ctx: CallContext) -> None:
    """Lệnh ghi kết thúc cuộc gọi (transfer / unreachable)."""
    if ctx.ended or ctx.outcome is not None:
        raise InconsistentSession(f"{ctx.call_id}: phiên đã kết thúc")
