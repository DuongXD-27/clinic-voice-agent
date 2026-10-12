from datetime import datetime

import pytest

from callbot.engine.asr_hints import (
    CANCEL_REASON_PHRASES,
    FORBIDDEN_QUESTIONS,
    INTENT_PHRASES,
    SLOT_REFUSE_PHRASES,
    hints_for,
    spoken_number,
)
from callbot.engine.extraction.schema import QuestionId
from callbot.engine.session.context import CallContext, Question
from callbot.engine.types import CallStart

NOW = datetime.fromisoformat("2026-10-12T09:00:00+07:00")
SLOT_FRI_9 = {"slot_id": "s1", "starts_at": "2026-10-16T09:00:00+07:00"}
SLOT_TUE_1430 = {"slot_id": "s2", "starts_at": "2026-10-20T14:30:00+07:00"}
SLOT_WED_10 = {"slot_id": "s3", "starts_at": "2026-10-21T10:00:00+07:00"}


def _ctx(question: QuestionId, **fields) -> CallContext:
    ctx = CallContext(call=CallStart("c_hints", "inbound"), opened_at=NOW, **fields)
    ctx.question = Question(question, "câu hỏi", 1)
    return ctx


def test_ask_name_hints_profile_names_with_guard() -> None:
    ctx = _ctx(
        QuestionId.ASK_NAME,
        identity_reference=[
            {"full_name": "Nguyễn Văn A", "verifiable": True},
            {"full_name": "Trần Thị Mai", "verifiable": True},
            {"full_name": "Lê Văn Khóa", "verifiable": False},
        ],
    )

    hints = hints_for(ctx)

    assert hints.phrases == ("NGUYỄN VĂN A", "TRẦN THỊ MAI")
    assert hints.guard_one_word


def test_ask_name_without_profile_has_no_hints() -> None:
    assert not hints_for(_ctx(QuestionId.ASK_NAME))


@pytest.mark.parametrize("question", sorted(FORBIDDEN_QUESTIONS, key=lambda q: q.value))
def test_dob_and_write_turns_never_get_hints(question: QuestionId) -> None:
    """SF-03 (ngày sinh) và SF-05 (bias "đồng ý/hủy" ở lượt ghi): luôn rỗng, kể cả khi có dữ liệu."""
    ctx = _ctx(
        question,
        identity_reference=[{"full_name": "Nguyễn Văn A", "verifiable": True}],
        slots=[SLOT_FRI_9],
        presented_slot_ids=["s1"],
    )

    assert hints_for(ctx).phrases == ()


def test_every_question_is_decided() -> None:
    """State mới phải được xếp vào nhóm có hotword hoặc FORBIDDEN_QUESTIONS một cách có chủ đích."""
    hinted = {
        QuestionId.ASK_NAME,
        QuestionId.ASK_INTENT,
        QuestionId.OFFER_SLOTS,
        QuestionId.ASK_SLOT_PREFERENCE,
        QuestionId.SLOT_REFUSE_CHOICE,
        QuestionId.ASK_CANCEL_REASON,
    }
    assert hinted | FORBIDDEN_QUESTIONS == set(QuestionId)
    assert not hinted & FORBIDDEN_QUESTIONS


def test_offer_slots_hints_only_presented_slots() -> None:
    ctx = _ctx(
        QuestionId.OFFER_SLOTS,
        slots=[SLOT_FRI_9, SLOT_TUE_1430, SLOT_WED_10],
        presented_slot_ids=["s1", "s2"],
    )

    phrases = hints_for(ctx).phrases

    for expected in (
        "CHÍN GIỜ SÁNG",
        "THỨ SÁU",
        "NGÀY MƯỜI SÁU",
        "HAI GIỜ BA MƯƠI CHIỀU",
        "HAI GIỜ RƯỠI CHIỀU",
        "THỨ BA",
        "NGÀY HAI MƯƠI",
        "KHUNG ĐẦU",
    ):
        assert expected in phrases
    assert "THỨ TƯ" not in phrases  # khung chưa đọc
    assert not hints_for(ctx).guard_one_word


def test_slot_preference_hints_days_with_slots() -> None:
    ctx = _ctx(QuestionId.ASK_SLOT_PREFERENCE, slots=[SLOT_FRI_9, SLOT_WED_10])

    phrases = hints_for(ctx).phrases

    assert {"THỨ SÁU", "NGÀY MƯỜI SÁU", "THỨ TƯ", "NGÀY HAI MƯƠI MỐT", "BUỔI CHIỀU"} <= set(phrases)
    assert "CHÍN GIỜ SÁNG" not in phrases


@pytest.mark.parametrize(
    ("question", "phrases"),
    [
        (QuestionId.ASK_INTENT, INTENT_PHRASES),
        (QuestionId.SLOT_REFUSE_CHOICE, SLOT_REFUSE_PHRASES),
        (QuestionId.ASK_CANCEL_REASON, CANCEL_REASON_PHRASES),
    ],
)
def test_fixed_phrase_states(question: QuestionId, phrases: tuple[str, ...]) -> None:
    assert hints_for(_ctx(question)).phrases == phrases


def test_ended_call_and_no_question_have_no_hints() -> None:
    ended = _ctx(QuestionId.ASK_INTENT, state="ENDED")
    blank = CallContext(call=CallStart("c_hints", "inbound"), opened_at=NOW)

    assert not hints_for(ended)
    assert not hints_for(blank)


def test_hint_phrases_never_contain_separator() -> None:
    ctx = _ctx(
        QuestionId.ASK_NAME,
        identity_reference=[{"full_name": "Nguyễn/Văn  A", "verifiable": True}],
    )

    assert hints_for(ctx).phrases == ("NGUYỄN VĂN A",)


@pytest.mark.parametrize(
    ("value", "spoken"),
    [
        (0, "KHÔNG"),
        (1, "MỘT"),
        (10, "MƯỜI"),
        (11, "MƯỜI MỘT"),
        (15, "MƯỜI LĂM"),
        (20, "HAI MƯƠI"),
        (21, "HAI MƯƠI MỐT"),
        (24, "HAI MƯƠI TƯ"),
        (25, "HAI MƯƠI LĂM"),
        (30, "BA MƯƠI"),
        (31, "BA MƯƠI MỐT"),
        (45, "BỐN MƯƠI LĂM"),
    ],
)
def test_spoken_number(value: int, spoken: str) -> None:
    assert spoken_number(value) == spoken
