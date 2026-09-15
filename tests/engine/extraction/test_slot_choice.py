"""Bộ bẫy §5.7 / §9: tỉ lệ MATCH sai slot ≈ 0."""

from datetime import datetime

import pytest

from callbot.engine.extraction.schema import VN_TZ, Provenance
from callbot.engine.extraction.slot_choice import extract_slot_choice, parse_slot_criteria

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=VN_TZ)  # thứ hai
SLOTS = [
    {"slot_id": "tue_0800", "starts_at": "2026-10-13T08:00:00+07:00"},
    {"slot_id": "wed_1000", "starts_at": "2026-10-14T10:00:00+07:00"},
    {"slot_id": "wed_1430", "starts_at": "2026-10-14T14:30:00+07:00"},
    {"slot_id": "thu_1430", "starts_at": "2026-10-15T14:30:00+07:00"},
    {"slot_id": "thu_1600", "starts_at": "2026-10-15T16:00:00+07:00"},
    {"slot_id": "next_thu_0900", "starts_at": "2026-10-22T09:00:00+07:00"},
    {"slot_id": "utc_slot", "starts_at": "2026-10-16T02:00:00+00:00"},  # = 09:00 thứ sáu giờ VN
]
PRESENTED = ("wed_1000", "wed_1430", "thu_1430")


def choose(text: str):
    return extract_slot_choice(text, SLOTS, PRESENTED, NOW).value


@pytest.mark.parametrize(
    "text, slot_id",
    [
        ("khung 1", "wed_1000"),
        ("khung thứ hai", "wed_1430"),
        ("cái đầu tiên", "wed_1000"),
        ("lấy cái cuối", "thu_1430"),
        ("mười giờ", "wed_1000"),
        ("14h30 thứ tư", "wed_1430"),
        ("chiều thứ năm lúc bốn giờ", "thu_1600"),
        ("thứ năm tuần sau", "next_thu_0900"),
        ("ngày mai", "tue_0800"),
        ("sáng mai tám giờ", "tue_0800"),
        ("mùng 14 lúc 10 giờ", "wed_1000"),
        ("20/10", None),
        ("9 giờ sáng thứ sáu", "utc_slot"),  # so theo +07:00, không theo giờ UTC trong chuỗi
    ],
)
def test_match(text: str, slot_id) -> None:
    choice = choose(text)
    if slot_id is None:
        assert choice.kind == "NO_MATCH"
    else:
        assert choice.kind == "MATCH", choice
        assert choice.slot_id == slot_id


@pytest.mark.parametrize(
    "text, slot_ids",
    [
        ("chiều thứ năm", ("thu_1430", "thu_1600")),       # không được tự chọn slot đầu
        ("hai giờ rưỡi", ("wed_1430", "thu_1430")),
        ("thứ năm", ("thu_1430", "thu_1600", "next_thu_0900")),
        ("buổi chiều", ("wed_1430", "thu_1430", "thu_1600")),
    ],
)
def test_ambiguous_returns_all_candidates(text: str, slot_ids: tuple[str, ...]) -> None:
    choice = choose(text)
    assert choice.kind == "AMBIGUOUS"
    assert choice.slot_ids == slot_ids
    assert choice.slot_id is None


def test_half_past_two_without_period_matches_the_only_listed_time() -> None:
    # 02:30 không có trong danh sách -> chỉ còn 14:30 thứ tư
    assert choose("thứ tư hai giờ rưỡi").slot_id == "wed_1430"


@pytest.mark.parametrize(
    "text",
    [
        "tối thứ bảy",       # không có slot
        "khung thứ năm",     # chỉ đọc 3 khung
        "hai giờ",           # 14:00 không có; không lấy 14:30
        "khung 2 lúc 10 giờ",  # tiêu chí mâu thuẫn
    ],
)
def test_no_match(text: str) -> None:
    result = extract_slot_choice(text, SLOTS, PRESENTED, NOW)
    assert result.value.kind == "NO_MATCH"
    assert result.provenance is Provenance.NORMALIZED


def test_no_criteria_is_none() -> None:
    result = extract_slot_choice("vâng ạ", SLOTS, PRESENTED, NOW)
    assert result.value.kind == "NO_MATCH"
    assert result.provenance is Provenance.NONE


def test_criteria_parsing_does_not_double_read_tokens() -> None:
    criteria = parse_slot_criteria("khung thứ hai", NOW)
    assert criteria.ordinal == 2 and criteria.weekday is None

    criteria = parse_slot_criteria("thứ hai hai giờ chiều", NOW)
    assert criteria.weekday == 0 and criteria.hours == frozenset({14}) and criteria.minute == 0

    criteria = parse_slot_criteria("ba giờ kém mười lăm chiều", NOW)
    assert criteria.hours == frozenset({14}) and criteria.minute == 45

    criteria = parse_slot_criteria("khung 2 giờ chiều", NOW)
    assert criteria.ordinal is None and criteria.hours == frozenset({14})
