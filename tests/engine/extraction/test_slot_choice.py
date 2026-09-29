"""Bộ bẫy §5.7 / §9: tỉ lệ MATCH sai slot ≈ 0."""

from datetime import date, datetime

import pytest

from callbot.engine.extraction.schema import VN_TZ, Provenance
from callbot.engine.extraction.slot_choice import (
    asks_back,
    extract_slot_choice,
    parse_slot_criteria,
    requested_slot_count,
    resolve_request,
)

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
        # T-10 §3.8.1: trang đọc theo giờ, "gần nhất / sớm nhất / trước" là khung 1
        ("cái gần nhất ấy", "wed_1000"),
        ("lấy cái sớm nhất", "wed_1000"),
        ("cái trước đi", "wed_1000"),
        ("lấy cái sau đi", "thu_1430"),
        ("cái kia", "thu_1430"),
        ("cai gan nhat", "wed_1000"),
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
        ("chiều thứ năm", ("thu_1430", "thu_1600")),  # không được tự chọn slot đầu
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
        "tối thứ bảy",  # không có slot
        "khung thứ năm",  # chỉ đọc 3 khung
        "hai giờ",  # 14:00 không có; không lấy 14:30
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


def test_day_with_month_wins_and_ngay_n_gio_is_an_hour() -> None:
    """Test tay T-10: "sang ngày 2 giờ chiều ... ngày 16 tháng 10" từng ra mùng 2, mất giờ."""
    criteria = parse_slot_criteria("đổi sang ngày 2 giờ chiều thứ Sáu ngày 16 tháng 10 đi", NOW)
    assert (criteria.day, criteria.month) == (16, 10)
    assert criteria.hours == frozenset({14}) and criteria.weekday == 4

    criteria = parse_slot_criteria("ngày 16 thì 2 giờ chiều", NOW)
    assert criteria.day == 16 and criteria.month is None and criteria.hours == frozenset({14})


@pytest.mark.parametrize(
    "text",
    [
        "khung khác",
        "còn khung nào khác không",
        "nghe tiếp",
        "giờ khác được không",
        "ngày khác đi",
        "sớm hơn được không",
        "khung khac",
        "con khung nao khac khong",
        "thế còn gì nữa không em",
        "còn nữa không",
        "còn cái nào không",
        "cho tôi xem 4 khung khác",
        "xem nốt 2 khung cuối",
        "hai khung còn lại thì sao",
        "mấy khung còn lại",
        "xem not 2 khung cuoi",
    ],
)
def test_asking_for_other_slots_is_more(text: str) -> None:
    """T-10: xin nghe khung khác không phải "không hiểu" — Dialogue đọc trang tiếp."""
    result = extract_slot_choice(text, SLOTS, PRESENTED, NOW)
    assert result.value.kind == "MORE" and result.found


def test_criteria_wins_over_more() -> None:
    result = extract_slot_choice("khung khác, buổi sáng ấy", SLOTS, PRESENTED, NOW)
    assert result.value.kind != "MORE" and result.value.criteria.period == "MORNING"


def test_slot_count_is_not_an_ordinal_hour_or_weekday() -> None:
    """Test tay T-10: "xem nốt 2 khung cuối" từng chọn khung cuối của trang và đi thẳng vào câu chốt."""
    assert parse_slot_criteria("xem nốt 2 khung cuối", NOW).empty
    assert requested_slot_count("cho tôi xem 4 khung khác") == 4
    assert requested_slot_count("xem nốt hai khung cuối") == 2
    assert requested_slot_count("khung khác") is None
    # "khung cuối" không kèm số lượng vẫn là chọn khung cuối của trang
    assert parse_slot_criteria("lấy khung cuối", NOW).ordinal == -1


@pytest.mark.parametrize(
    "text",
    ["ngày nào cũng được", "tùy em", "càng sớm càng tốt", "sớm nhất", "khi nao cung duoc"],
)
def test_any_time_is_any(text: str) -> None:
    """T-10 D-1: không nêu tiêu chí, để bot chọn khung sớm nhất."""
    result = extract_slot_choice(text, SLOTS, PRESENTED, NOW)
    assert result.value.kind == "ANY" and result.found


def test_criteria_wins_over_any() -> None:
    result = extract_slot_choice("sáng nào cũng được", SLOTS, PRESENTED, NOW)
    assert result.value.kind != "ANY" and result.value.criteria.period == "MORNING"


# --- R-30: ngày tương đối, hôm nay thứ Ba 29/09/2026 (plan T-10 §3.5.2) ------------------

TUESDAY = datetime(2026, 9, 29, 10, 0, tzinfo=VN_TZ)
D = date


@pytest.mark.parametrize(
    ("text", "issue", "date_from", "date_to"),
    [
        ("mốt", None, D(2026, 10, 1), D(2026, 10, 1)),
        ("ngày mốt", None, D(2026, 10, 1), D(2026, 10, 1)),
        ("thứ 7 này", None, D(2026, 10, 3), D(2026, 10, 3)),
        ("thứ sáu", None, D(2026, 10, 2), D(2026, 10, 2)),
        ("chủ nhật", None, D(2026, 10, 4), D(2026, 10, 4)),
        ("thứ hai", "PAST", D(2026, 9, 28), D(2026, 9, 28)),
        ("thứ ba", "TODAY", D(2026, 9, 29), D(2026, 9, 29)),
        ("thứ sáu tuần sau", None, D(2026, 10, 5), D(2026, 10, 11)),
        ("cuối tuần", None, D(2026, 10, 3), D(2026, 10, 4)),
        ("cuối tuần sau", None, D(2026, 10, 10), D(2026, 10, 11)),
        ("đầu tuần sau", None, D(2026, 10, 5), D(2026, 10, 7)),
        ("tuần sau nữa", None, D(2026, 10, 12), D(2026, 10, 18)),
        ("tuan sau nua", None, D(2026, 10, 12), D(2026, 10, 18)),
        ("hôm qua", "PAST", D(2026, 9, 28), D(2026, 9, 28)),
        ("ngày 20 tháng 9", "PAST", D(2026, 9, 20), D(2026, 9, 20)),
        ("ngày 31 tháng 9", "INVALID", None, None),
        ("29 tháng 2", "INVALID", None, None),
        ("tháng sau", "TOO_BROAD", None, None),
        ("thang sau", "TOO_BROAD", None, None),
        ("cuối tháng", "TOO_BROAD", None, None),
        ("đầu tháng sau", "TOO_BROAD", None, None),
        ("tháng 11", "TOO_BROAD", None, None),
    ],
)
def test_relative_dates_follow_r30(text: str, issue, date_from, date_to) -> None:
    criteria = resolve_request(parse_slot_criteria(text, TUESDAY), TUESDAY)
    assert (criteria.date_issue, criteria.date_from, criteria.date_to) == (
        issue,
        date_from,
        date_to,
    )


def test_day_and_month_without_ngay_and_next_month_day() -> None:
    criteria = parse_slot_criteria("3 giờ chiều 16 tháng 10", TUESDAY)
    assert (criteria.day, criteria.month, criteria.hours) == (16, 10, frozenset({15}))
    criteria = parse_slot_criteria("mùng 5 tháng sau", TUESDAY)
    assert (criteria.day, criteria.month, criteria.date_issue) == (5, 10, None)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("sao lại là thứ Sáu", True),
        ("thứ Sáu à", True),
        ("3 giờ hả", True),
        ("thu sau a", True),
        ("thứ Sáu", False),
        ("ngày 20 thì sao", False),  # hỏi ngày mới, không phải hỏi lại
        ("được không", False),
    ],
)
def test_asking_back_is_not_choosing(text: str, expected: bool) -> None:
    """T-10 §3.8.1: ở câu chốt, câu hỏi lại không được đổi sang khung khác."""
    assert asks_back(text) is expected


def test_bare_weekday_still_matches_listed_slots_when_choosing() -> None:
    """R-30 chỉ quy đổi thứ trần cho yêu cầu mới; chọn trong danh sách vẫn khớp thứ đó."""
    criteria = parse_slot_criteria("thứ hai", TUESDAY)
    assert criteria.weekday == 0 and criteria.date_issue is None and criteria.date_from is None
