"""No answer eval: nhãn khớp không được che record sai, và bộ case khớp contract rev 1.1."""

import csv

import pytest
from scripts.no_answer_eval import (
    CASES,
    SETUP,
    NullSemantic,
    _caller,
    _contract_errors,
    _exit_code,
    _reconciliation_errors,
    _run_case,
    _start,
    _summarise,
    parse_turns,
)

UNREACHABLE_REASONS = {"NO_ANSWER", "VOICEMAIL", "LINE_BUSY", "SILENCE"}
TRANSFER_REASONS = {
    "IDENTITY_FAILED",
    "PATIENT_NOT_FOUND",
    "OUT_OF_SCOPE",
    "CLINICAL_QUESTION",
    "NOT_UNDERSTOOD",
    "PATIENT_REQUEST",
    "SYSTEM_ERROR",
}


def _row(**overrides):
    row = {
        "id": "NA_TEST",
        "scope": "http",
        "label_status": "CONFIRMED",
        "split": "holdout",
        "group": "test",
        "direction": "outbound",
        "question_id": "ASK_NAME",
        "turns": "<silence> | <silence> | <silence>",
        "expect_outcome": "UNREACHABLE",
        "expect_reason": "SILENCE",
        "end_turn": "",
        "fault": "",
        "note": "",
    }
    return {**row, **overrides}


def _silent_call(call_id):
    row = _row()
    bot, clinic, opening, done = _start(row, call_id, None)
    for index, line in enumerate(parse_turns(row["turns"]), start=1):
        action = bot.handle_turn(call_id, _caller(done + index, line))
    spoken = [(opening.utterance, False), (action.utterance, False)]
    assert _contract_errors(row, action, False, clinic, 0, spoken) == []
    return row, action, clinic, spoken


def test_parse_turns_marks_silence():
    assert parse_turns("<silence> | Nguyễn Văn A|  <silence>") == [None, "Nguyễn Văn A", None]


def test_cases_match_contract_enums_and_setup():
    with CASES.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    assert rows
    assert len({r["id"] for r in rows}) == len(rows)
    for row in rows:
        assert row["split"] in {"dev", "holdout", "regression"}, row
        assert row["label_status"] in {"CONFIRMED", "REVIEW"}, row
        assert row["scope"] in {"http", "telephony", "recovery"}, row
        if row["fault"]:
            assert row["scope"] == "recovery", row
        if row["group"] == "operator_live":
            assert row["scope"] == "telephony", row
        assert row["question_id"] in SETUP[row["direction"]], row
        assert all(line is None or line for line in parse_turns(row["turns"])), row
        if row["expect_outcome"] == "UNREACHABLE":
            assert row["direction"] == "outbound", row  # §1.1.7: inbound không bao giờ UNREACHABLE
            assert row["expect_reason"] in UNREACHABLE_REASONS, row
        elif row["expect_outcome"] == "TRANSFERRED":
            assert row["expect_reason"] in TRANSFER_REASONS, row
        if row["end_turn"]:
            assert 1 <= int(row["end_turn"]) <= len(parse_turns(row["turns"])), row


@pytest.mark.parametrize(
    "corruption, expected",
    [
        ("double_increment", "attempt_count"),
        ("reason", "reason_record_mismatch"),
        ("duplicate", "multiple_writes"),
        ("wrong_target", "wrong_appointment"),
        ("outcome", "outcome_record_mismatch"),
        ("disclosure", "disclosure_unverified"),
        ("new_key", "unreachable_key_changed"),
    ],
)
def test_unreachable_label_does_not_hide_contract_errors(corruption, expected):
    row, action, clinic, spoken = _silent_call(f"na_{corruption}")
    record = clinic.appointments["apt_00417"]
    if corruption == "double_increment":
        record["attempt_count"] += 1
    elif corruption == "reason":
        record["unreachable_reason"] = "VOICEMAIL"
    elif corruption == "duplicate":
        clinic.writes.append(clinic.writes[0])
    elif corruption == "wrong_target":
        clinic.writes[0] = ("apt_00418", *clinic.writes[0][1:])
    elif corruption == "outcome":
        action.outcome = "TRANSFERRED"
    elif corruption == "disclosure":
        spoken.append(("Anh chị có lịch khám Nội tổng quát 9 giờ", False))
    else:
        clinic.requests.append(("other-key", "unreachable"))
    assert expected in _contract_errors(row, action, False, clinic, 0, spoken)


def test_voicemail_ends_on_the_greeting_turn():
    result = _run_case(
        _row(
            turns="Xin vui lòng để lại lời nhắn sau tiếng bíp | <silence> | <silence> | <silence>",
            expect_reason="VOICEMAIL",
            end_turn="1",
        ),
        "na_voicemail",
        None,
        1,
    )
    assert result["passed"] and result["turns_played"] == 1
    assert result["attempt_count"] == 1 and result["record_status"] == "UNREACHABLE"


def test_ending_on_the_wrong_turn_fails_with_the_right_status():
    # Chỉ 2 lượt im lặng không được kết thúc; kỳ vọng lượt 2 là sai nên case phải fail
    result = _run_case(_row(end_turn="2"), "na_wrong_turn", None, 1)
    assert result["status_ok"] and not result["behaviour_ok"] and not result["passed"]


def test_speech_between_silences_must_not_end_the_call():
    result = _run_case(
        _row(
            turns="<silence> | <silence> | Nguyễn Văn A | <silence> | <silence>",
            expect_outcome="CONTINUE",
            expect_reason="",
        ),
        "na_reset",
        None,
        1,
    )
    assert result["passed"] and result["record_status"] == "SCHEDULED"


def test_false_unreachable_fails_even_in_safety_mode():
    result = _run_case(
        _row(
            turns="để lại lời nhắn sau tiếng bíp",
            expect_outcome="NOT_UNREACHABLE",
            expect_reason="",
        ),
        "na_false",
        None,
        1,
    )
    assert result["false_unreachable"] and result["contract_ok"]
    summary = _summarise([result], None)
    assert _exit_code([summary]) == _exit_code([summary], safety_only=True) == 1


def test_inbound_silence_transfers_without_write():
    result = _run_case(
        _row(direction="inbound", expect_outcome="TRANSFERRED", expect_reason="NOT_UNDERSTOOD"),
        "na_inbound",
        None,
        1,
    )
    assert result["passed"] and result["writes"] == "[]"


@pytest.mark.parametrize(
    "fault, outcome, reason, attempts",
    [
        ("conflict_once", "UNREACHABLE", "SILENCE", 1),
        ("conflict_twice", "TRANSFERRED", "SYSTEM_ERROR", 0),
        ("outcome_unknown", "RECONCILE", "", None),
    ],
)
def test_write_faults(fault, outcome, reason, attempts):
    result = _run_case(
        _row(fault=fault, expect_outcome=outcome, expect_reason=reason), f"na_{fault}", None, 1
    )
    assert result["passed"], result
    if attempts is not None:
        assert result["attempt_count"] == attempts
    assert result["recovery_errors"] == ""


@pytest.mark.parametrize("semantic", [None, NullSemantic()])
def test_no_implicit_model_gateway_with_enabled_environment(monkeypatch, semantic):
    import callbot.engine as engine

    monkeypatch.setenv("NAME_FALLBACK_PROVIDER", "openai")
    monkeypatch.setenv("SEMANTIC_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-offline-never-sent")

    def forbidden(*args, **kwargs):
        pytest.fail("Baseline/route-only must not construct a model gateway")

    monkeypatch.setattr(engine, "create_gateway", forbidden)
    bot, _, _, done = _start(_row(), "na_no_gateway", semantic)
    # Cấu trúc tên chưa rõ có thể kích hoạt slot filling tên nếu còn bật ngầm.
    bot.handle_turn("na_no_gateway", _caller(done + 1, "à thì để tôi nhớ lại đã"))
    assert bot._extractor._semantic is semantic


def test_review_is_observed_but_not_scored_or_counted_as_holdout():
    result = _run_case(
        _row(
            label_status="REVIEW",
            turns="Xin chào, tôi là Lan, hiện không nghe máy được",
            expect_reason="VOICEMAIL",
        ),
        "na_review",
        None,
        1,
    )
    assert result["status"] == "REVIEW" and result["passed"] is None
    summary = _summarise([result], None)
    assert summary["review_cases"] == 1
    assert summary["passed_cases"] == summary["failed_cases"] == summary["scored_cases"] == 0
    assert summary["holdout"]["total"] == 0
    assert _exit_code([summary]) == 0
    # REVIEW must not hide a real disclosure or record corruption.
    result.update(contract_ok=False, contract_errors="disclosure_unverified")
    assert _exit_code([_summarise([result], None)]) == 1


def test_reporting_separates_http_telephony_recovery_and_regression():
    base = _run_case(_row(), "na_buckets", None, 1)
    rows = [
        {**base, "scope": scope, "split": "regression"}
        for scope in ("http", "telephony", "recovery")
    ]
    summary = _summarise(rows, None)
    assert summary["scored_path"]["total"] == 1
    assert summary["operator_live"]["total"] == 1
    assert summary["recovery"]["total"] == 1
    assert summary["regression"]["total"] == 3


def test_reconciliation_probe_rejects_exception_without_persistent_lock(monkeypatch):
    bot, clinic, _, _ = _start(_row(), "na_unlocked", None)

    def accepts_followup(*args, **kwargs):
        clinic.requests.append(("unexpected", "unreachable"))

    monkeypatch.setattr(bot, "handle_turn", accepts_followup)
    assert set(_reconciliation_errors(bot, clinic, "na_unlocked", 3)) == {
        "reconciliation_not_locked",
        "reconciliation_next_turn_allowed",
        "reconciliation_followup_changed_clinic",
    }


def test_confirmed_corpus_behaviour_and_record_checks():
    with CASES.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    for row in rows:
        result = _run_case(row, f"corpus_{row['id']}", None, 1)
        assert result["contract_ok"] and not result["recovery_errors"], result
        if row["label_status"] != "REVIEW":
            assert result["passed"], result
