"""Các ý review PR đổi lịch (06-10-2026), chạy đúng lời người gọi trên sim `mentor_mock()`.

Xem `docs/evidence/reschedule-mentor-eval-2026-10-06.md` §10. Dữ liệu và đồng hồ như eval mentor: apt_00417 lúc
15:30 thứ Tư 14/10; trang khung đầu là 14/10 15:00 (`slot_91d2`), 15/10 10:30; trang sau là 15/10 15:30,
16/10 9:00. Mỗi ca chạy khi chỉ có luật và khi model timeout.
"""

import pytest

from tests.engine.test_mentor_eval_reschedule import IDENTITY, _outbound_call
from tests.engine.test_orchestrator import _run

MODES = ["rule", "timeout"]


def _rescheduled(clinic) -> list:
    return [w for w in clinic.writes if w[1] == "RESCHEDULED"]


# --- Ý 1: đồng ý kèm giờ của khung khác không phải đồng ý khung đang chốt ---------------------------

# Câu chốt khung 14/10 15:00 ("Đổi sang 15h ngày 14/10")
SLOT_READBACK = [*IDENTITY, "Đổi sang 15h ngày 14/10"]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    ("line", "said"),
    [
        # Không khớp khung nào: tra theo giờ khách vừa nêu
        ("vâng, 9 giờ sáng ngày 20", "em chưa thấy khung giờ đó"),
        ("vâng thì 5 giờ", "em chưa thấy khung giờ đó"),
        # Khớp các khung chưa đọc
        ("vâng, ngày 20", "8 giờ sáng thứ Ba ngày 20 tháng 10"),
        ("vâng, 8 giờ sáng ngày 20", "sáng thứ Ba ngày 20 tháng 10 còn khung 8 giờ sáng"),
    ],
)
def test_agreeing_with_another_time_does_not_write_the_slot_read_back(
    mode: str, line: str, said: str
) -> None:
    clinic, bot = _outbound_call(f"r1-{mode}-{line}", mode)
    action = _run(bot, f"r1-{mode}-{line}", [*SLOT_READBACK, line])
    assert said in action.utterance
    assert not action.ended and _rescheduled(clinic) == []


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("line", ["Đúng rồi, 15 giờ", "Vâng, 3 giờ được", "vâng, chiều thứ Tư"])
def test_agreeing_with_the_slot_read_back_still_writes_it(mode: str, line: str) -> None:
    clinic, bot = _outbound_call(f"r1-ok-{mode}-{line}", mode)
    action = _run(bot, f"r1-ok-{mode}-{line}", [*SLOT_READBACK, line])
    assert action.outcome == "RESCHEDULED"
    assert _rescheduled(clinic) == [("apt_00417", "RESCHEDULED", {"new_slot_id": "slot_91d2"})]


# --- Ý 2: khung của trang trước qua câu chốt, không thành SYSTEM_ERROR ------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_a_slot_from_the_previous_page_is_read_back_then_written(mode: str) -> None:
    clinic, bot = _outbound_call(f"r2-{mode}", mode)
    lines = [*IDENTITY, "Tôi muốn đổi lịch", "khung khác", "3 giờ chiều ngày 14"]
    action = _run(bot, f"r2-{mode}", lines)
    assert action.state == "AWAITING_CONFIRMATION" and not action.ended
    assert "3 giờ chiều thứ Tư ngày 14 tháng 10" in action.utterance
    assert _rescheduled(clinic) == []

    action = _run(bot, f"r2-{mode}", ["đồng ý"], start=len(lines) + 1)
    assert action.outcome == "RESCHEDULED"
    assert _rescheduled(clinic) == [("apt_00417", "RESCHEDULED", {"new_slot_id": "slot_91d2"})]


@pytest.mark.parametrize("mode", MODES)
def test_a_slot_on_the_page_just_read_is_still_written_directly(mode: str) -> None:
    clinic, bot = _outbound_call(f"r2-page-{mode}", mode)
    lines = [*IDENTITY, "Tôi muốn đổi lịch", "khung khác", "9 giờ sáng thứ Sáu"]
    action = _run(bot, f"r2-page-{mode}", lines)
    assert action.outcome == "RESCHEDULED"
    assert _rescheduled(clinic) == [("apt_00417", "RESCHEDULED", {"new_slot_id": "slot_b503"})]


# --- Ý 4: câu hỏi thường có ngày giờ ở câu đọc lịch không phải xin đổi giờ ---------------------------


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "line",
    [
        "ngày mai tôi có phải nhịn ăn không",
        "mai tôi có cần mang theo giấy tờ gì không",
        "thứ Năm tôi có phải mang theo kết quả cũ không",
        "tôi muốn hỏi ngày mai phòng khám mở cửa lúc mấy giờ",
        "hôm nay tôi muốn hỏi chút",
        "sáng mai tôi muốn gọi lại hỏi thêm được không",
    ],
)
def test_a_question_mentioning_a_day_is_not_a_reschedule_request(mode: str, line: str) -> None:
    clinic, bot = _outbound_call(f"r4-{mode}-{line}", mode)
    action = _run(bot, f"r4-{mode}-{line}", [*IDENTITY, line])
    assert action.state != "OFFERING_SLOTS" and "khung" not in action.utterance
    assert clinic.slot_reads == 0 and clinic.writes == []


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "line",
    [
        "Sáng mai khoảng 9 giờ có được không?",
        "5 giờ chiều ngày 14 đi em",
        "Có giờ nào sáng thứ Năm không em?",
        "Để sang thứ Năm được không em",
        "Muộn hơn chút được không",
    ],
)
def test_asking_for_another_time_still_starts_the_reschedule(mode: str, line: str) -> None:
    clinic, bot = _outbound_call(f"r4-ok-{mode}-{line}", mode)
    action = _run(bot, f"r4-ok-{mode}-{line}", [*IDENTITY, line])
    assert "khung" in action.utterance and clinic.slot_reads > 0 and clinic.writes == []


# --- Ý 5: lời bỏ chỉ kết thúc việc đổi lịch khi là vế cuối ---------------------------------------

OFFER = [*IDENTITY, "Tôi muốn đổi lịch"]  # khung 1 = 14/10 15:00, khung 2 = 15/10 10:30


@pytest.mark.parametrize("mode", MODES)
def test_a_pick_after_giving_up_one_time_is_the_answer(mode: str) -> None:
    clinic, bot = _outbound_call(f"r5-{mode}", mode)
    lines = [*OFFER, "3 giờ chiều thì thôi, lấy khung 2"]
    action = _run(bot, f"r5-{mode}", lines)
    # Câu vừa có lời bỏ vừa có lời chọn: đọc câu chốt một lần, không ghi ngay, không chuyển máy
    assert action.state == "AWAITING_CONFIRMATION" and "10 giờ 30 sáng" in action.utterance
    assert clinic.writes == []

    action = _run(bot, f"r5-{mode}", ["đồng ý"], start=len(lines) + 1)
    assert _rescheduled(clinic) == [("apt_00417", "RESCHEDULED", {"new_slot_id": "slot_b501"})]


@pytest.mark.parametrize("mode", MODES)
def test_a_new_day_after_giving_up_is_searched(mode: str) -> None:
    clinic, bot = _outbound_call(f"r5-day-{mode}", mode)
    action = _run(bot, f"r5-day-{mode}", [*OFFER, "vậy thì thôi, cho tôi ngày 16"])
    assert not action.ended and "ngày 16 tháng 10" in action.utterance and clinic.writes == []


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "line", ["Không có 5 giờ thì thôi", "thế thì thôi vậy em", "thôi khỏi, tôi đi khám chỗ khác"]
)
def test_giving_up_at_the_end_keeps_the_old_appointment(mode: str, line: str) -> None:
    clinic, bot = _outbound_call(f"r5-end-{mode}-{line}", mode)
    action = _run(bot, f"r5-end-{mode}-{line}", [*OFFER, line])
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "PATIENT_REQUEST")
    assert _rescheduled(clinic) == []


# --- Ý 6: mọi cách gọi thứ tự khung cho cùng một kết quả -----------------------------------------


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    ("line", "slot"),
    [
        ("khung 1", "slot_91d2"),
        ("khung một", "slot_91d2"),
        ("lấy khung 2", "slot_b501"),
        ("lấy khung hai", "slot_b501"),
        ("khung thứ hai", "slot_b501"),
        ("chọn khung số 2", "slot_b501"),
        ("cái thứ hai", "slot_b501"),
    ],
)
def test_every_way_of_naming_a_slot_on_the_page_writes_it(mode: str, line: str, slot: str) -> None:
    clinic, bot = _outbound_call(f"r6-{mode}-{line}", mode)
    action = _run(bot, f"r6-{mode}-{line}", [*OFFER, line])
    assert action.outcome == "RESCHEDULED"
    assert _rescheduled(clinic) == [("apt_00417", "RESCHEDULED", {"new_slot_id": slot})]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "line", ["khung 1 à?", "khung một hay khung hai nhỉ", "khung 2 được không"]
)
def test_a_slot_named_as_a_question_is_not_written(mode: str, line: str) -> None:
    clinic, bot = _outbound_call(f"r6-no-{mode}-{line}", mode)
    action = _run(bot, f"r6-no-{mode}-{line}", [*OFFER, line])
    assert not action.ended and clinic.writes == []


# --- Ý 3: ngày / giờ dạng số trong lượt danh tính được giữ (R-43) ---------------------------------


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    ("line", "said"),
    [
        (
            "Tôi là Nguyễn Văn A, sinh ngày 14 tháng 3 năm 1978, muốn đổi lịch sang 14:00 ngày 16",
            "chiều thứ Sáu ngày 16 tháng 10 còn khung 2 giờ chiều",
        ),
        (
            "Tôi là Nguyễn Văn A, sinh ngày 14 tháng 3 năm 1978, muốn đổi lịch sang 15:30 ngày 15",
            "chiều thứ Năm ngày 15 tháng 10 còn khung 3 giờ 30 chiều",
        ),
    ],
)
def test_a_numeric_time_said_with_the_identity_is_kept(mode: str, line: str, said: str) -> None:
    clinic, bot = _outbound_call(f"r3-{mode}-{line}", mode)
    action = _run(bot, f"r3-{mode}-{line}", [line])
    assert said in action.utterance and clinic.writes == []


# --- Ý 7: luồng R-43 qua cùng cổng trạng thái lịch với luồng thường -------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_a_request_with_the_identity_on_a_cancelled_appointment_offers_nothing(mode: str) -> None:
    clinic, bot = _outbound_call(f"r7-{mode}", mode)
    clinic.set_status("apt_00417", "CANCELLED")  # lịch đổi trạng thái sau lượt 0
    line = "Alo, tôi là Nguyễn Văn A, sinh 14/3/78, tôi muốn đổi lịch sang chiều ngày 14"
    action = _run(bot, f"r7-{mode}", [line])
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "SYSTEM_ERROR")
    assert clinic.slot_reads == 0 and "khung" not in action.utterance


# --- Ý 8: Dialogue đọc lịch tối đa một lần mỗi lượt -----------------------------------------------


def _appointment_reads(clinic, start: int) -> int:
    return sum(1 for call in clinic.calls[start:] if call.operation == "get_appointment")


@pytest.mark.parametrize(
    ("mode", "lines"),
    [
        ("rule", [*IDENTITY, "Đổi sớm hơn được không em"]),
        ("timeout", [*IDENTITY, "Sáng mai khoảng 9 giờ có được không?"]),
        (
            "rule",
            [
                "Alo, tôi là Nguyễn Văn A, sinh 14/3/78, "
                "tôi muốn đổi lịch sang sớm hơn trong chiều ngày 14"
            ],
        ),
    ],
)
def test_a_reschedule_turn_reads_the_appointment_once(mode: str, lines: list[str]) -> None:
    call_id = f"r8-{mode}-{lines[-1]}"
    clinic, bot = _outbound_call(call_id, mode)
    _run(bot, call_id, lines[:-1])
    before = len(clinic.calls)
    action = _run(bot, call_id, lines[-1:], start=len(lines))
    assert "khung" in action.utterance
    assert _appointment_reads(clinic, before) == 1


# --- Merge main 07/10 (evidence §11): khoảng giờ của main và "sớm hơn" của nhánh cùng chạy; tự sửa ------


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    ("line", "said"),
    [
        # "trước 12 giờ" (khoảng giờ, main) và "sớm hơn" (mốc lịch đang đổi, nhánh): hai tiêu chí khác nhau
        ("ngày 15 trước 12 giờ", "10 giờ 30 sáng thứ Năm ngày 15 tháng 10"),
        ("ngày 14 sớm hơn", "ngày 14 tháng 10 còn khung 3 giờ chiều"),
        # R-44: "à không phải" là lời tự sửa, không phải loại trừ giờ nói sau; buổi "chiều" của giờ cũ
        # không áp vào 10 giờ 30
        ("3 giờ chiều à không phải 10 giờ 30", "10 giờ 30 sáng thứ Năm ngày 15 tháng 10"),
        ("3 giờ chiều, à không phải, 10 giờ 30", "10 giờ 30 sáng thứ Năm ngày 15 tháng 10"),
        # "không phải X mà là Y" giữ "15/10", cả khi Dialogue đọc lại câu làm yêu cầu mới
        ("không phải 14/10 mà là 15/10", "ngày 15 tháng 10"),
        ("ngày 15/10 chứ không phải 14/10", "ngày 15 tháng 10"),
    ],
)
def test_ranges_relative_times_and_corrections_after_the_merge(
    mode: str, line: str, said: str
) -> None:
    call_id = f"m11-{mode}-{line}"
    clinic, bot = _outbound_call(call_id, mode)
    action = _run(bot, call_id, [*IDENTITY, "Tôi muốn đổi lịch", line])
    assert not action.ended and said in action.utterance
    assert "14 tháng 10" not in action.utterance or "ngày 14" in line
    assert clinic.writes == []


@pytest.mark.parametrize("mode", MODES)
def test_corrected_date_keeps_the_reschedule_intent(mode: str) -> None:
    """`corrected_tail` (main) đọc lại nhu cầu sau "à không"; lời sửa NGÀY không bỏ nhu cầu đổi lịch."""
    call_id = f"m11-intent-{mode}"
    clinic, bot = _outbound_call(call_id, mode)
    action = _run(
        bot, call_id, [*IDENTITY, "Đổi sang ngày 15... à không, vẫn ngày 14 nhưng sớm hơn"]
    )
    assert "ngày 14 tháng 10 còn khung 3 giờ chiều" in action.utterance and clinic.writes == []
