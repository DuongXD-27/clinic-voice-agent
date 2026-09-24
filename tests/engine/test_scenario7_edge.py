"""Scenario 7: inbound booking searches bounded, consecutive 14-day slot windows."""

from datetime import datetime, timedelta

from callbot.engine.extraction.intent import extract_intent
from callbot.engine.extraction.schema import VN_TZ, Intent
from clinic_mock_sim import FakeClinicAPI, clinic_error
from tests.engine.test_orchestrator import _context, _inbound, _run, create_orchestrator

NOW = datetime(2026, 9, 22, 10, 0, 0, tzinfo=VN_TZ)
PATIENT_ID = "pt_scenario7"
PHONE = "0912345600"
NAME = "Nguyễn Văn A"
DOB = "14/03/1978"


def _setup():
    clinic = FakeClinicAPI(seed=False, strict_slot_window=True)
    clinic.seed_patient(
        {
            "patient_id": PATIENT_ID,
            "phone": PHONE,
            "verify": {"full_name": NAME, "dob": "1978-03-14"},
        }
    )
    bot = create_orchestrator(clinic)
    bot.sessions._clock = lambda: NOW
    return clinic, bot


def _seed_slot(clinic: FakeClinicAPI, slot_id: str, days: int) -> None:
    start = NOW + timedelta(days=days)
    clinic.seed_slot(
        {
            "slot_id": slot_id,
            "clinic_id": "cl_vinmec",
            "start_time": start.isoformat(),
            "end_time": (start + timedelta(minutes=30)).isoformat(),
            "provider_id": "pr_scenario7",
        }
    )


def _offer(bot, call_id: str):
    bot.start_call(_inbound(call_id, PHONE))
    return _run(bot, call_id, [NAME, DOB, "Tôi muốn đặt lịch khám"])


def test_case_a_slot_plus_7_days_uses_one_window_and_is_offered() -> None:
    clinic, bot = _setup()
    _seed_slot(clinic, "slot_7d", 7)

    action = _offer(bot, "c_s7_a")

    assert action.state == "OFFERING_SLOTS" and action.ended is False
    assert clinic.slot_reads == 1
    assert [slot["slot_id"] for slot in _context(bot, "c_s7_a").slots] == ["slot_7d"]


def test_case_b_boundary_plus_14_days_is_offered_once() -> None:
    clinic, bot = _setup()
    _seed_slot(clinic, "slot_14d", 14)

    action = _offer(bot, "c_s7_b")

    # Fake/official contract uses half-open windows [from, to), so the boundary is in window 2.
    assert action.state == "OFFERING_SLOTS"
    assert clinic.slot_reads == 2
    assert [slot["slot_id"] for slot in _context(bot, "c_s7_b").slots] == ["slot_14d"]


def test_case_c_slot_plus_22_days_regression_reaches_offering_slots() -> None:
    clinic, bot = _setup()
    _seed_slot(clinic, "slot_22d", 22)

    action = _offer(bot, "c_s7_c")

    assert action.state == "OFFERING_SLOTS" and action.ended is False
    assert action.outcome is None and action.transfer_reason is None
    assert clinic.slot_reads == 2
    assert [slot["slot_id"] for slot in _context(bot, "c_s7_c").slots] == ["slot_22d"]


def test_case_d_no_slots_scans_bounded_policy_then_transfers_out_of_scope() -> None:
    clinic, bot = _setup()

    action = _offer(bot, "c_s7_d")

    assert (action.state, action.ended, action.outcome, action.transfer_reason) == (
        "ENDED",
        True,
        "TRANSFERRED",
        "OUT_OF_SCOPE",
    )
    assert clinic.slot_reads == 5


def test_case_e_keeps_all_slots_in_earliest_non_empty_window_and_stops() -> None:
    clinic, bot = _setup()
    _seed_slot(clinic, "slot_22d_a", 22)
    _seed_slot(clinic, "slot_23d_b", 23)

    action = _offer(bot, "c_s7_e")

    assert action.state == "OFFERING_SLOTS"
    assert clinic.slot_reads == 2
    assert [slot["slot_id"] for slot in _context(bot, "c_s7_e").slots] == [
        "slot_22d_a",
        "slot_23d_b",
    ]


def test_case_f_earlier_slot_prevents_later_window_query() -> None:
    clinic, bot = _setup()
    _seed_slot(clinic, "slot_7d", 7)
    _seed_slot(clinic, "slot_22d", 22)

    action = _offer(bot, "c_s7_f")

    assert action.state == "OFFERING_SLOTS"
    assert clinic.slot_reads == 1
    assert [slot["slot_id"] for slot in _context(bot, "c_s7_f").slots] == ["slot_7d"]


def test_case_g_unoffered_slot_choice_never_writes() -> None:
    clinic, bot = _setup()
    _seed_slot(clinic, "slot_only", 7)
    _offer(bot, "c_s7_g")

    action = _run(bot, "c_s7_g", ["khung 2"], start=4)

    assert action.state == "OFFERING_SLOTS"
    assert _context(bot, "c_s7_g").selected_slot_id is None
    assert clinic.writes == [] and clinic.requests == []


def test_case_h_slot_taken_refreshes_without_blind_booking_retry() -> None:
    clinic, bot = _setup()
    _seed_slot(clinic, "slot_taken", 7)
    _seed_slot(clinic, "slot_fallback", 8)
    _offer(bot, "c_s7_h")
    _run(bot, "c_s7_h", ["khung 1"], start=4)
    clinic.taken_slots.add("slot_taken")
    clinic.fail_next("create_appointment", clinic_error(409, "SLOT_TAKEN"))

    action = _run(bot, "c_s7_h", ["Vâng, tôi xác nhận đặt lịch này"], start=5)

    assert action.state == "OFFERING_SLOTS" and action.ended is False
    assert clinic.writes == []
    assert clinic.slot_reads == 2
    context = _context(bot, "c_s7_h")
    assert context.selected_slot_id is None
    assert [slot["slot_id"] for slot in context.slots] == ["slot_fallback"]


def test_case_i_complete_plus_22_day_booking_writes_exactly_once() -> None:
    clinic, bot = _setup()
    _seed_slot(clinic, "slot_book_22d", 22)
    bot.start_call(_inbound("c_s7_i", PHONE))

    action = _run(
        bot,
        "c_s7_i",
        [
            NAME,
            DOB,
            "Tôi muốn đặt lịch khám",
            "khung 1",
            "Vâng, tôi xác nhận đặt lịch này",
        ],
    )

    assert (action.state, action.ended, action.outcome) == ("ENDED", True, "BOOKED")
    assert clinic.slot_reads == 2
    assert clinic.writes == [("apt_new_0", "BOOKED", {"slot_id": "slot_book_22d"})]
    appointment = clinic.appointments["apt_new_0"]
    assert appointment["status"] == "BOOKED"
    assert appointment["patient"]["patient_id"] == PATIENT_ID


def test_case_j_booking_phrases_keep_book_intent() -> None:
    assert extract_intent("Tôi muốn đặt lịch", "inbound").value is Intent.BOOK
    assert extract_intent("Tôi muốn đặt lịch khám", "inbound").value is Intent.BOOK
