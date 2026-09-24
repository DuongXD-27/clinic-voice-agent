"""A matching behaviour label must not hide a corrupt clinic record or response."""

import csv

import pytest
from scripts.confirm_eval import CASES, _contract_errors, _exit_code, _run_case, _summarise

from callbot.engine import CallerInput, CallStart, create_orchestrator
from callbot.engine.session import CallContext
from clinic_mock_sim import FakeClinicAPI


def _confirmed():
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(
        CallStart(call_id="eval_record", direction="outbound", appointment_id="apt_00417")
    )
    for turn, text in enumerate(["Nguyễn Văn A", "14/03/1978"], 1):
        bot.handle_turn("eval_record", CallerInput(turn=turn, text=text))
    before = CallContext.from_dict(bot.sessions.store.get_session("eval_record").context)
    action = bot.handle_turn("eval_record", CallerInput(turn=3, text="vâng"))
    assert _contract_errors(action, before, clinic, "") == []
    return action, before, clinic


@pytest.mark.parametrize(
    "corruption, expected",
    [
        ("wrong_target", "wrong_appointment"),
        ("duplicate", "multiple_writes"),
        ("metadata", "confirmation_metadata"),
        ("outcome", "outcome_record_mismatch"),
        ("department", "incomplete_readback"),
    ],
)
def test_confirm_label_does_not_hide_contract_errors(corruption, expected):
    action, before, clinic = _confirmed()
    if corruption == "wrong_target":
        clinic.writes[0] = ("apt_other", "CONFIRMED", {})
    elif corruption == "duplicate":
        clinic.writes.append(clinic.writes[0])
    elif corruption == "metadata":
        clinic.appointments["apt_00417"].pop("confirmed_at")
    elif corruption == "outcome":
        action.outcome = "TRANSFERRED"
    else:
        clinic.appointments["apt_00417"]["department"] = "Chuyên khoa chưa được đọc"
    assert expected in _contract_errors(action, before, clinic, "")


def test_transfer_to_wrong_reason_fails_even_when_behaviour_matches():
    with CASES.open(encoding="utf-8", newline="") as source:
        row = next(r for r in csv.DictReader(source) if r["transcript"] == "cho tôi gặp nhân viên")
    row["expect_transfer_reason"] = "OUT_OF_SCOPE"
    result = _run_case(row, "eval_wrong_reason", None, 1)
    assert result["behaviour_ok"] and not result["passed"]
    assert "transfer_reason_mismatch" in result["contract_errors"]
    summary = _summarise([result], None)
    assert summary["failed_cases"] == summary["contract_failures"] == 1
    assert _exit_code([summary]) == _exit_code([summary], safety_only=True) == 1


def test_dialogue_mismatch_fails_default_exit_but_is_reported_separately():
    with CASES.open(encoding="utf-8", newline="") as source:
        row = next(r for r in csv.DictReader(source) if r["transcript"] == "vâng")
    row["transcript"] = "chắc là được"
    result = _run_case(row, "eval_uncertain", None, 1)
    assert not result["passed"] and result["contract_ok"]
    summary = _summarise([result], None)
    assert _exit_code([summary]) == 1
    assert _exit_code([summary], safety_only=True) == 0


def test_valid_confirmation_passes_all_checks():
    with CASES.open(encoding="utf-8", newline="") as source:
        row = next(r for r in csv.DictReader(source) if r["transcript"] == "vâng")
    result = _run_case(row, "eval_confirm", None, 1)
    assert result["passed"] and result["contract_errors"] == ""
    assert _exit_code([_summarise([result], None)]) == 0


def test_missing_required_transfer_is_not_just_a_dialogue_mismatch():
    with CASES.open(encoding="utf-8", newline="") as source:
        row = next(r for r in csv.DictReader(source) if r["transcript"] == "cho tôi gặp nhân viên")
    row["transcript"] = "chắc là được"
    result = _run_case(row, "eval_missing_transfer", None, 1)
    assert not result["passed"] and not result["contract_ok"]
    assert "missing_required_transfer" in result["contract_errors"]


def test_successful_branches_are_not_counted_as_attendance_confirmations():
    with CASES.open(encoding="utf-8", newline="") as source:
        cases = list(csv.DictReader(source))
    rows = []
    for index, text in enumerate(["vâng", "hủy giúp tôi", "vâng nhưng tôi muốn đổi giờ"]):
        case = next(r for r in cases if r["transcript"] == text)
        rows.append(_run_case(case, f"eval_scoring_scope_{index}", None, 1))
    summary = _summarise(rows, None)
    assert summary["holdout_fully_passed"] == 3
    assert summary["attendance_confirmation_cases"] == 1
    assert summary["attendance_confirmation_passed"] == 1
    assert summary["attendance_confirmation_rate"] == 1.0
    assert summary["branch_routing_cases"] == summary["branch_routing_passed"] == 2


def test_wrong_confirmation_on_a_branch_cannot_inflate_completion_score():
    with CASES.open(encoding="utf-8", newline="") as source:
        case = next(r for r in csv.DictReader(source) if r["transcript"] == "hủy giúp tôi")
    case["transcript"] = "vâng"  # mô phỏng bot xác nhận thay vì đi nhánh hủy mong đợi
    result = _run_case(case, "eval_wrong_branch_write", None, 1)
    summary = _summarise([result], None)
    assert result["unsafe_write"] and not result["passed"]
    assert summary["attendance_confirmation_passed"] == 0
    assert summary["attendance_confirmation_rate"] is None
    assert summary["branch_routing_cases"] == 1 and summary["branch_routing_passed"] == 0
