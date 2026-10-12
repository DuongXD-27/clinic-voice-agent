"""Review luồng đổi lịch 12-10-2026 (`docs/plans/t10-reschedule-review-2026-10-12.md`), PR 1.

Chạy đúng lời người gọi trên sim `mentor_mock()`, đồng hồ thứ Hai 12-10-2026 10:00. Lịch apt_00417 lúc
15:30 thứ Tư 14/10. Khung trống: slot_91d2 14/10 15:00 · b501 15/10 10:30 · b502 15/10 15:30 · b503
16/10 9:00 · b504 16/10 14:00 · b505 19/10 10:00 · b506 19/10 15:30 · b507 20/10 8:00 · b508 20/10 14:00
· b509 21/10 9:00 · b510 21/10 15:00. Trang đầu ("Đổi lịch cho tôi") là 91d2 + b501, trang sau
("khung khác") là b502 + b503.
"""

import random
from datetime import datetime

import pytest

from callbot.engine import CallStart
from callbot.engine.extraction.clinical import extract_clinical
from callbot.engine.extraction.schema import VN_TZ, ClinicalLevel, QuestionId
from clinic_mock_sim import FakeClinicAPI
from tests.engine.test_orchestrator import _context, _run, create_orchestrator

NOW = datetime(2026, 10, 12, 10, 0, tzinfo=VN_TZ)
IDENTITY = ["Nguyễn Văn A", "14 tháng 3 năm 1978"]
FIRST_PAGE = [*IDENTITY, "Đổi lịch cho tôi"]
SECOND_PAGE = [*FIRST_PAGE, "khung khác"]
BOOK_IDENTITY = ["Trần Thị Bình", "21 tháng 6 năm 1990"]


class _ModelDown:
    def analyze(self, context):  # noqa: ANN001, ANN201
        raise TimeoutError("model slow")


MODES = ["rule", "timeout"]


def _call(call_id: str, mode: str = "rule", direction: str = "outbound"):
    clinic = FakeClinicAPI.mentor_mock()
    bot = create_orchestrator(clinic)
    bot.sessions._clock = lambda: NOW
    if mode == "timeout":
        bot._extractor._semantic = _ModelDown()
    if direction == "outbound":
        start = CallStart(call_id=call_id, direction="outbound", appointment_id="apt_00417")
    else:
        start = CallStart(call_id=call_id, direction="inbound", caller_number="0901234501")
    bot.start_call(start)
    return clinic, bot


def _slot_writes(clinic) -> list:
    return [w for w in clinic.writes if w[1] in ("RESCHEDULED", "BOOKED")]


def _say(bot, call_id: str, lines: list[str], done: list[str]):
    """Nói tiếp `lines` sau các lượt `done` đã nói."""
    return _run(bot, call_id, lines, start=len(done) + 1)


# --- B7: câu chọn khớp đúng một khung trên trang vừa đọc -----------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_user_report_picks_the_only_wednesday_afternoon_on_the_page(mode: str) -> None:
    """Ca user báo: STT rớt "3" — "giờ chiều thứ 4" chỉ khớp một khung trên trang (owner: chọn luôn)."""
    clinic, bot = _call(f"b7-user-{mode}", mode)
    action = _run(bot, f"b7-user-{mode}", [*FIRST_PAGE, "giờ chiều thứ 4"])
    assert action.outcome == "RESCHEDULED"
    assert _slot_writes(clinic) == [("apt_00417", "RESCHEDULED", {"new_slot_id": "slot_91d2"})]


@pytest.mark.parametrize("mode", MODES)
def test_a_weekday_matching_one_slot_on_the_page_is_picked(mode: str) -> None:
    clinic, bot = _call(f"b7-thu5-{mode}", mode)
    action = _run(bot, f"b7-thu5-{mode}", [*FIRST_PAGE, "thứ năm"])
    assert action.outcome == "RESCHEDULED"
    assert _slot_writes(clinic) == [("apt_00417", "RESCHEDULED", {"new_slot_id": "slot_b501"})]


@pytest.mark.parametrize("mode", MODES)
def test_a_part_of_day_matching_one_slot_on_the_page_is_read_back(mode: str) -> None:
    """Chỉ có buổi: đọc câu chốt, không ghi ngay."""
    clinic, bot = _call(f"b7-chieu-{mode}", mode)
    action = _run(bot, f"b7-chieu-{mode}", [*FIRST_PAGE, "chiều"])
    ctx = _context(bot, f"b7-chieu-{mode}")
    assert ctx.question.question_id is QuestionId.SLOT_READBACK
    assert ctx.selected_slot_id == "slot_91d2"
    assert "3 giờ chiều, thứ Tư ngày 14 tháng 10" in action.utterance
    assert _slot_writes(clinic) == []


def test_booking_reads_back_the_only_matching_slot_on_the_page() -> None:
    """Đặt lịch luôn đọc lại khung đã chọn (contract §1.1.10)."""
    clinic, bot = _call("b7-book", direction="inbound")
    lines = [*BOOK_IDENTITY, "Tôi muốn đặt lịch", "giờ chiều thứ 4"]
    _run(bot, "b7-book", lines)
    ctx = _context(bot, "b7-book")
    assert ctx.question.question_id is QuestionId.SLOT_READBACK
    assert ctx.selected_slot_id == "slot_91d2"
    assert _slot_writes(clinic) == []


# --- B1 / B2 / B9: trang mơ hồ có đường thoát ----------------------------------------------------

AMBIGUOUS_3PM = [*SECOND_PAGE, "3 giờ chiều"]  # -> trang 91d2 (14/10) + b510 (21/10)


@pytest.mark.parametrize("mode", MODES)
def test_an_ambiguous_page_names_what_differs(mode: str) -> None:
    clinic, bot = _call(f"b9-{mode}", mode)
    action = _run(bot, f"b9-{mode}", AMBIGUOUS_3PM)
    ctx = _context(bot, f"b9-{mode}")
    assert ctx.presented_slot_ids == ["slot_91d2", "slot_b510"]
    assert "ngày 14 và ngày 21 tháng 10" in action.utterance
    assert "chọn ngày nào" in action.utterance
    assert "Còn" not in action.utterance  # không còn khung 3 giờ chiều nào khác (B3)
    assert ctx.failed_understandings == 0 and ctx.unclear_streak == 0
    assert _slot_writes(clinic) == []


@pytest.mark.parametrize("mode", MODES)
def test_repeating_the_ambiguous_answer_asks_which_one_then_transfers(mode: str) -> None:
    """Ca user báo (dạng còn lại sau B7): nói lại câu không thu hẹp được thì hỏi lại chọn khung nào
    (owner 12-10), không đọc lại nguyên trang mãi; lặp tiếp thì chuyển máy NOT_UNDERSTOOD (§1.1.5)."""
    clinic, bot = _call(f"b1-{mode}", mode)
    first = _run(bot, f"b1-{mode}", AMBIGUOUS_3PM)
    done = list(AMBIGUOUS_3PM)

    reask = _say(bot, f"b1-{mode}", ["3 giờ chiều đi"], done)
    done.append("3 giờ chiều đi")
    ctx = _context(bot, f"b1-{mode}")
    assert ctx.question.question_id is QuestionId.OFFER_SLOTS
    assert ctx.presented_slot_ids == ["slot_91d2", "slot_b510"]
    assert reask.utterance != first.utterance
    assert "ngày 14 hay ngày 21 tháng 10" in reask.utterance
    assert ctx.unclear_streak == 1 and ctx.failed_understandings == 0

    action = reask
    for _ in range(3):
        action = _say(bot, f"b1-{mode}", ["3 giờ chiều đi"], done)
        done.append("3 giờ chiều đi")
        if action.ended:
            break
    assert action.outcome == "TRANSFERRED" and action.transfer_reason == "NOT_UNDERSTOOD"
    assert _slot_writes(clinic) == []


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(("line", "slot_id"), [("ngày 14", "slot_91d2"), ("ngày 21", "slot_b510")])
def test_naming_the_date_after_the_ambiguous_page_picks_that_slot(
    mode: str, line: str, slot_id: str
) -> None:
    """ "ngày 21" khớp 9:00 và 15:00 nhưng chỉ 15:00 nằm trên trang vừa đọc (B7)."""
    clinic, bot = _call(f"b1-date-{mode}-{line}", mode)
    action = _run(bot, f"b1-date-{mode}-{line}", [*AMBIGUOUS_3PM, "3 giờ chiều đi", line])
    assert action.outcome == "RESCHEDULED"
    assert _slot_writes(clinic) == [("apt_00417", "RESCHEDULED", {"new_slot_id": slot_id})]


@pytest.mark.parametrize("mode", MODES)
def test_an_hour_matching_two_slots_off_the_page_names_both_days(mode: str) -> None:
    clinic, bot = _call(f"b9-9h-{mode}", mode)
    action = _run(bot, f"b9-9h-{mode}", [*FIRST_PAGE, "9 giờ"])
    ctx = _context(bot, f"b9-9h-{mode}")
    assert ctx.presented_slot_ids == ["slot_b503", "slot_b509"]
    assert "thứ Sáu ngày 16" in action.utterance and "thứ Tư ngày 21 tháng 10" in action.utterance
    assert "chọn ngày nào" in action.utterance

    action = _say(bot, f"b9-9h-{mode}", ["9 giờ sáng đi"], [*FIRST_PAGE, "9 giờ"])
    ctx = _context(bot, f"b9-9h-{mode}")
    assert ctx.question.question_id is QuestionId.OFFER_SLOTS and ctx.unclear_streak == 1
    assert _slot_writes(clinic) == []


@pytest.mark.parametrize("mode", MODES)
def test_alternating_between_pages_already_read_counts_as_not_understood(mode: str) -> None:
    """Luân phiên hai câu mơ hồ: mỗi lượt một trang khác nhưng không có khung mới -> UNCLEAR."""
    clinic, bot = _call(f"b2-alt-{mode}", mode)
    _run(bot, f"b2-alt-{mode}", AMBIGUOUS_3PM)  # trang 91d2 + b510
    done = list(AMBIGUOUS_3PM)
    action = _say(bot, f"b2-alt-{mode}", ["9 giờ"], done)  # trang b503 + b509: có khung mới b509
    done.append("9 giờ")
    assert _context(bot, f"b2-alt-{mode}").unclear_streak == 0
    for line in ["3 giờ chiều", "9 giờ", "3 giờ chiều", "9 giờ"]:
        action = _say(bot, f"b2-alt-{mode}", [line], done)
        done.append(line)
        if action.ended:
            break
    assert action.outcome == "TRANSFERRED" and action.transfer_reason == "NOT_UNDERSTOOD"
    assert _slot_writes(clinic) == []


@pytest.mark.parametrize("seed", range(12))
def test_non_narrowing_answers_always_end_the_call(seed: int) -> None:
    """Thuộc tính kết thúc (§6.1): chuỗi câu mơ hồ bất kỳ không được lặp tới hết max_turns."""
    pool = [
        "3 giờ chiều",
        "3 giờ chiều đi",
        "9 giờ",
        "9 giờ sáng đi",
        "ba giờ chiều nhé",
        "chín giờ",
    ]
    rng = random.Random(seed)
    clinic, bot = _call(f"prop-{seed}")
    # Bắt đầu ở trang 91d2 + b510: mỗi câu trong kho khớp đúng hai khung, cả hai trên trang hoặc cả hai
    # ngoài trang, nên không câu nào chọn được khung
    _run(bot, f"prop-{seed}", AMBIGUOUS_3PM)
    done = list(AMBIGUOUS_3PM)
    action = None
    for _ in range(10):
        line = rng.choice(pool)
        action = _say(bot, f"prop-{seed}", [line], done)
        done.append(line)
        if action.ended:
            break
    assert action is not None and action.ended, done
    assert action.outcome == "TRANSFERRED" and _slot_writes(clinic) == []


# --- B3 / B4: trang mơ hồ là yêu cầu hiện hành --------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_more_after_an_ambiguous_page_stays_within_the_matching_slots(mode: str) -> None:
    clinic, bot = _call(f"b4-{mode}", mode)
    lines = [*AMBIGUOUS_3PM, "sáng"]  # sáng: b501, b503 đã đọc; còn b505, b507, b509
    action = _run(bot, f"b4-{mode}", lines)
    ctx = _context(bot, f"b4-{mode}")
    assert ctx.presented_slot_ids == ["slot_b505", "slot_b507"]
    assert "Còn 1 khung khác" in action.utterance

    action = _say(bot, f"b4-{mode}", ["khung khác"], lines)
    ctx = _context(bot, f"b4-{mode}")
    assert ctx.selected_slot_id == "slot_b509"  # khung sáng còn lại, không đọc lại khung đã đọc
    assert "9 giờ sáng, thứ Tư ngày 21 tháng 10" in action.utterance
    assert _slot_writes(clinic) == []


def test_candidate_slots_survive_the_session_round_trip() -> None:
    clinic, bot = _call("b4-roundtrip")
    _run(bot, "b4-roundtrip", [*AMBIGUOUS_3PM, "sáng"])
    ctx = _context(bot, "b4-roundtrip")
    assert ctx.slot_candidate_ids == [
        "slot_b501",
        "slot_b503",
        "slot_b505",
        "slot_b507",
        "slot_b509",
    ]
    data = ctx.to_dict()
    assert type(ctx).from_dict(data).slot_candidate_ids == ctx.slot_candidate_ids
    del data["slot_candidate_ids"]  # phiên lưu trước khi có khóa này
    assert type(ctx).from_dict(data).slot_candidate_ids == []


# --- B13: phần khách loại trừ không bị mời lại ----------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_excluding_a_day_reads_back_the_other_day(mode: str) -> None:
    """Trang có một khung ngày 15 (10:30): chọn khung đó (B7), đọc câu chốt vì câu có "không"."""
    clinic, bot = _call(f"b13-day-{mode}", mode)
    action = _run(bot, f"b13-day-{mode}", [*FIRST_PAGE, "không lấy ngày 14, ngày 15 đi"])
    ctx = _context(bot, f"b13-day-{mode}")
    assert ctx.selected_slot_id == "slot_b501"
    assert "10 giờ 30 sáng, thứ Năm ngày 15 tháng 10" in action.utterance
    assert "slot_91d2" in ctx.refused_slot_ids
    assert _slot_writes(clinic) == []


@pytest.mark.parametrize("mode", MODES)
def test_excluding_a_day_off_the_page_offers_the_other_day(mode: str) -> None:
    """Trang thứ hai không có ngày 15 sáng: yêu cầu mới theo phần khách muốn, không theo nguyên câu."""
    clinic, bot = _call(f"b13-day2-{mode}", mode)
    lines = [*AMBIGUOUS_3PM, "không lấy ngày 21, ngày 20 đi"]
    _run(bot, f"b13-day2-{mode}", lines)
    ctx = _context(bot, f"b13-day2-{mode}")
    assert ctx.presented_slot_ids == ["slot_b507", "slot_b508"]
    assert {"slot_b509", "slot_b510"} <= set(ctx.refused_slot_ids)
    assert _slot_writes(clinic) == []


@pytest.mark.parametrize("mode", MODES)
def test_excluding_an_hour_never_offers_that_slot_again(mode: str) -> None:
    clinic, bot = _call(f"b13-hour-{mode}", mode)
    lines = [*FIRST_PAGE, "không lấy 3 giờ chiều, thứ 4 đi"]
    action = _run(bot, f"b13-hour-{mode}", lines)
    ctx = _context(bot, f"b13-hour-{mode}")
    assert "slot_91d2" in ctx.refused_slot_ids
    assert ctx.selected_slot_id != "slot_91d2" and "slot_91d2" not in ctx.presented_slot_ids
    assert "3 giờ chiều, thứ Tư ngày 14" not in action.utterance

    for line in ["khung khác", "khung khác", "khung khác"]:
        action = _say(bot, f"b13-hour-{mode}", [line], lines)
        lines.append(line)
        if action.ended:
            break
        ctx = _context(bot, f"b13-hour-{mode}")
        assert "slot_91d2" not in ctx.presented_slot_ids and ctx.selected_slot_id != "slot_91d2"
    assert _slot_writes(clinic) == []


# --- B14: xin tư vấn bác sĩ / hỏi về bệnh luôn chuyển máy, không phụ thuộc model -----------------


@pytest.mark.parametrize(
    "line",
    [
        "tôi cần tư vấn bác sĩ",
        "tôi có câu hỏi về bệnh",
        "cho tôi hỏi bác sĩ một chút",
        "tôi muốn hỏi bác sĩ về thuốc",
        "toi can tu van bac si",
    ],
)
def test_asking_for_clinical_advice_is_an_advice_request(line: str) -> None:
    assert extract_clinical(line).value is ClinicalLevel.ADVICE_REQUEST


@pytest.mark.parametrize(
    "line",
    [
        "tôi muốn hỏi bác sĩ khám giờ nào",
        "cho tôi hỏi lịch khám bác sĩ nào",
        "tôi muốn đổi lịch khám bệnh",
    ],
)
def test_asking_about_the_booking_is_not_an_advice_request(line: str) -> None:
    assert extract_clinical(line).value is not ClinicalLevel.ADVICE_REQUEST


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("line", ["tôi cần tư vấn bác sĩ", "tôi có câu hỏi về bệnh"])
def test_clinical_advice_at_the_slot_offer_transfers(mode: str, line: str) -> None:
    clinic, bot = _call(f"b14-{mode}-{line}", mode)
    action = _run(bot, f"b14-{mode}-{line}", [*FIRST_PAGE, line])
    assert action.outcome == "TRANSFERRED" and action.transfer_reason == "CLINICAL_QUESTION"
    assert _slot_writes(clinic) == []


def test_clinical_advice_before_inbound_verification_transfers() -> None:
    clinic, bot = _call("b14-inbound", direction="inbound")
    action = _run(bot, "b14-inbound", ["tôi cần tư vấn bác sĩ"])
    assert action.outcome == "TRANSFERRED"
    assert clinic.writes == []


# --- B15: "tôi đổi ý" là đổi ý định, bỏ việc đổi / đặt lịch --------------------------------------


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("line", ["tôi đổi ý", "thôi tôi đổi ý rồi", "em ơi tôi đổi ý"])
def test_changing_ones_mind_at_the_offer_goes_back_to_the_appointment(mode: str, line: str) -> None:
    clinic, bot = _call(f"b15-{mode}-{line}", mode)
    action = _run(bot, f"b15-{mode}-{line}", [*FIRST_PAGE, line])
    ctx = _context(bot, f"b15-{mode}-{line}")
    assert not action.ended and ctx.pending_action is None
    assert ctx.question.question_id is QuestionId.CONFIRM_READBACK
    assert "Lịch cũ của anh chị vẫn giữ nguyên" in action.utterance
    assert clinic.writes == []


@pytest.mark.parametrize("mode", MODES)
def test_changing_ones_mind_at_the_slot_read_back_goes_back_to_the_appointment(mode: str) -> None:
    clinic, bot = _call(f"b15-rb-{mode}", mode)
    lines = [*FIRST_PAGE, "chiều", "tôi đổi ý"]
    action = _run(bot, f"b15-rb-{mode}", lines)
    ctx = _context(bot, f"b15-rb-{mode}")
    assert ctx.pending_action is None and ctx.question.question_id is QuestionId.CONFIRM_READBACK
    assert "Lịch cũ của anh chị vẫn giữ nguyên" in action.utterance
    assert clinic.writes == []


@pytest.mark.parametrize("mode", MODES)
def test_changing_ones_mind_then_picking_a_slot_reads_that_slot_back(mode: str) -> None:
    """Vế sau quyết định: chọn khung 2. Câu có "đổi ý" nên đọc câu chốt, không ghi ngay (R-41)."""
    clinic, bot = _call(f"b15-pick-{mode}", mode)
    _run(bot, f"b15-pick-{mode}", [*FIRST_PAGE, "tôi đổi ý, lấy khung 2"])
    ctx = _context(bot, f"b15-pick-{mode}")
    assert ctx.pending_action == "RESCHEDULE" and ctx.selected_slot_id == "slot_b501"
    assert ctx.question.question_id is QuestionId.SLOT_READBACK
    assert _slot_writes(clinic) == []


def test_changing_ones_mind_then_cancelling_asks_the_cancel_question() -> None:
    clinic, bot = _call("b15-cancel")
    _run(bot, "b15-cancel", [*FIRST_PAGE, "tôi đổi ý, hủy lịch luôn"])
    ctx = _context(bot, "b15-cancel")
    assert ctx.pending_action == "CANCEL"
    assert ctx.question.question_id is QuestionId.CANCEL_RECONFIRM
    assert clinic.writes == []


def test_changing_ones_mind_while_booking_drops_the_booking() -> None:
    clinic, bot = _call("b15-book", direction="inbound")
    _run(bot, "b15-book", [*BOOK_IDENTITY, "Tôi muốn đặt lịch", "tôi đổi ý"])
    ctx = _context(bot, "b15-book")
    assert ctx.pending_action is None and ctx.question.question_id is QuestionId.ASK_INTENT
    assert clinic.writes == []


# --- "cái sớm hơn" / "cái muộn hơn" chỉ một trong hai khung vừa đọc ------------------------------


@pytest.mark.parametrize(
    ("line", "slot_id"),
    [("lấy cái sớm hơn đi em", "slot_91d2"), ("cái muộn hơn ấy", "slot_b501")],
)
def test_pointing_at_the_earlier_or_later_slot_picks_it(line: str, slot_id: str) -> None:
    """Chọn đúng khung: ghi ngay khi câu gọn ("lấy cái sớm hơn đi em"), đọc câu chốt khi còn từ khác
    ("ấy") — cả hai đều là khung đó, không phải xin khung khác."""
    clinic, bot = _call(f"order-{line}")
    action = _run(bot, f"order-{line}", [*FIRST_PAGE, line])
    if action.ended:
        assert _slot_writes(clinic) == [("apt_00417", "RESCHEDULED", {"new_slot_id": slot_id})]
    else:
        assert _context(bot, f"order-{line}").selected_slot_id == slot_id
        assert _slot_writes(clinic) == []


def test_bare_earlier_still_asks_for_other_slots() -> None:
    """R033: "sớm hơn" trần là xin khung khác, không phải chọn khung 1."""
    clinic, bot = _call("order-bare")
    _run(bot, "order-bare", [*FIRST_PAGE, "sớm hơn"])
    assert _slot_writes(clinic) == []
