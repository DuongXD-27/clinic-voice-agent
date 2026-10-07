"""PRD R-44: người gọi tự sửa tiêu chí giờ / ngày trong cùng một câu — dùng giá trị nói SAU CÙNG.

"à không" theo sau là một giá trị mới là lời sửa, không phải lời từ chối (R-41). Lời sửa chỉ được
bỏ phần bị sửa khi TRÍCH giá trị; câu xác nhận thật vẫn qua `confirmation_veto` nguyên câu.
"""

from datetime import datetime

import pytest

from callbot.engine.extraction import Agreement, InformationExtractor, QuestionId, TurnContext
from callbot.engine.extraction.agreement import confirmation_veto
from callbot.engine.extraction.schema import VN_TZ
from callbot.engine.extraction.slot_choice import (
    extract_slot_choice,
    parse_slot_criteria,
    without_corrected_part,
)

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=VN_TZ)  # thứ hai


# --- Tiêu chí slot --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "transcript, expected",
    [
        ("9 giờ, à không, 10 giờ", {"hours": frozenset({10, 22}), "minute": 0}),
        ("9 giờ, à 10 giờ", {"hours": frozenset({10, 22}), "minute": 0}),
        ("9 giờ à không 10", {"hours": frozenset({10, 22}), "minute": 0}),
        ("9 gio a khong 10 gio", {"hours": frozenset({10, 22}), "minute": 0}),
        ("2 giờ chiều, à nhầm, 3 giờ", {"hours": frozenset({15}), "period": "AFTERNOON"}),
        ("thứ Sáu ngày 15… à không, 14", {"weekday": 4, "day": 14}),
        ("thứ năm à không thứ sáu", {"weekday": 4}),
        ("ngày 14 à không 15 được không", {"day": 15}),
        ("khung 1 à không khung 2", {"ordinal": 2}),
        ("khung thứ nhất, à không, thứ hai", {"ordinal": 2}),
        ("mùng 15 à không mùng 16 lúc 9 giờ", {"day": 16, "hours": frozenset({9, 21})}),
    ],
)
def test_slot_criteria_self_correction_uses_the_last_value(transcript: str, expected) -> None:
    criteria = parse_slot_criteria(transcript, NOW)
    for key, value in expected.items():
        assert getattr(criteria, key) == value, (key, criteria)
    if "ordinal" not in expected:
        assert criteria.ordinal is None


@pytest.mark.parametrize("transcript", ["thứ sáu à", "à, 10 giờ", "xin lỗi em, cho 10 giờ"])
def test_slot_criteria_without_two_sided_correction_is_unchanged(transcript: str) -> None:
    criteria = parse_slot_criteria(transcript, NOW)
    assert criteria == parse_slot_criteria(transcript.replace("à", "").replace("xin lỗi", ""), NOW)


def test_corrected_time_picks_the_corrected_slot() -> None:
    slots = [
        {"slot_id": "wed_0900", "starts_at": "2026-10-14T09:00:00+07:00"},
        {"slot_id": "wed_1000", "starts_at": "2026-10-14T10:00:00+07:00"},
    ]
    choice = extract_slot_choice(
        "9 giờ, à không, 10 giờ", slots, ("wed_0900", "wed_1000"), NOW
    ).value
    assert (choice.kind, choice.slot_ids) == ("MATCH", ("wed_1000",))


def test_without_corrected_part_keeps_only_the_last_answer() -> None:
    assert without_corrected_part("9 giờ, à không, 10 giờ", NOW) == "10 giờ"
    assert without_corrected_part("vâng, 10 giờ", NOW) == "vâng, 10 giờ"


# --- "à không" của lời sửa không phải lời từ chối; veto vẫn giữ nguyên ----------------------


def test_correction_at_slot_readback_is_not_a_refusal() -> None:
    result = InformationExtractor().extract(
        TurnContext(turn=3, question_id=QuestionId.SLOT_READBACK, direction="outbound", now=NOW),
        "9 giờ, à không, 10 giờ",
    )
    assert result.agreement.value is not Agreement.REFUSE
    assert not result.confirmation_conflict


@pytest.mark.parametrize(
    "transcript", ["9 giờ, à không, 10 giờ, đồng ý", "vâng nhưng không", "không, đồng ý"]
)
def test_confirmation_veto_still_blocks_agree_with_any_negation(transcript: str) -> None:
    assert confirmation_veto(transcript)
    result = InformationExtractor().extract(
        TurnContext(turn=3, question_id=QuestionId.SLOT_READBACK, direction="outbound", now=NOW),
        transcript,
    )
    assert result.agreement.value is not Agreement.AGREE


def test_plain_refusal_at_slot_readback_is_still_refuse() -> None:
    result = InformationExtractor().extract(
        TurnContext(turn=3, question_id=QuestionId.SLOT_READBACK, direction="outbound", now=NOW),
        "không, tôi không lấy giờ đó",
    )
    assert result.agreement.value is Agreement.REFUSE
