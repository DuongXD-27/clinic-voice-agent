from datetime import datetime

import pytest

from callbot.engine.asr_hints import hints_for
from callbot.engine.extraction.schema import QuestionId
from callbot.engine.session.context import CallContext, Question
from callbot.engine.types import CallStart

NOW = datetime.fromisoformat("2026-10-12T09:00:00+07:00")
SLOT_FRI_9 = {"slot_id": "s1", "starts_at": "2026-10-16T09:00:00+07:00"}


def _ctx(question: QuestionId, **fields) -> CallContext:
    ctx = CallContext(call=CallStart("c_hints", "inbound"), opened_at=NOW, **fields)
    ctx.question = Question(question, "câu hỏi", 1)
    return ctx


def test_ask_name_hints_every_profile_name_with_guard() -> None:
    """Hồ sơ không xác minh được (ngày sinh sai / thiếu) vẫn có hotword tên."""
    ctx = _ctx(
        QuestionId.ASK_NAME,
        identity_reference=[
            {"full_name": "Nguyễn Văn A", "verifiable": True},
            {"full_name": "Trần Thị Mai", "verifiable": True},
            {"full_name": "Giàng A Páo", "dob": None, "verifiable": False},
            {"full_name": None, "verifiable": False},
        ],
    )

    hints = hints_for(ctx)

    assert hints.phrases == ("NGUYỄN VĂN A", "TRẦN THỊ MAI", "GIÀNG A PÁO")
    assert hints.guard_one_word


def test_ask_name_without_profile_has_no_hints() -> None:
    assert not hints_for(_ctx(QuestionId.ASK_NAME))


@pytest.mark.parametrize(
    "question",
    sorted(set(QuestionId) - {QuestionId.ASK_NAME}, key=lambda q: q.value),
)
def test_only_name_turn_gets_hints(question: QuestionId) -> None:
    """Ngày sinh, ý định, khung giờ, lý do hủy, xác nhận: luôn rỗng, kể cả khi có dữ liệu."""
    ctx = _ctx(
        question,
        identity_reference=[{"full_name": "Nguyễn Văn A", "verifiable": True}],
        slots=[SLOT_FRI_9],
        presented_slot_ids=["s1"],
    )

    assert hints_for(ctx).phrases == ()


def test_ended_call_and_no_question_have_no_hints() -> None:
    ended = _ctx(
        QuestionId.ASK_NAME,
        identity_reference=[{"full_name": "Nguyễn Văn A", "verifiable": True}],
        state="ENDED",
    )
    blank = CallContext(call=CallStart("c_hints", "inbound"), opened_at=NOW)

    assert not hints_for(ended)
    assert not hints_for(blank)


def test_hint_phrases_never_contain_separator() -> None:
    ctx = _ctx(
        QuestionId.ASK_NAME,
        identity_reference=[{"full_name": "Nguyễn/Văn  A", "verifiable": True}],
    )

    assert hints_for(ctx).phrases == ("NGUYỄN VĂN A",)
