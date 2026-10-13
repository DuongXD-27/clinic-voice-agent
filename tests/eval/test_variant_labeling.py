"""Eval labels follow the selected dialogue variant for each call ID."""

import csv

import pytest
from scripts.confirm_eval import CASES as CONFIRM_CASES
from scripts.confirm_eval import _exit_code as confirm_exit_code
from scripts.confirm_eval import _run_case as run_confirm_case
from scripts.confirm_eval import _summarise as summarise_confirm
from scripts.reschedule_eval import CASES as RESCHEDULE_CASES
from scripts.reschedule_eval import _run_case as run_reschedule_case
from scripts.reschedule_eval import _summarise as summarise_reschedule

from callbot.engine.dialogue import templates as t
from callbot.engine.dialogue.variants import VARIANT_IDS, choose_variant


@pytest.fixture(autouse=True)
def fixed_dialogue_variant(monkeypatch):
    """Use the production selector instead of the business test fixture's v0 selector."""
    monkeypatch.setattr(t, "choose_variant", choose_variant)


def _case(path, predicate):
    with path.open(encoding="utf-8", newline="") as source:
        return next(row for row in csv.DictReader(source) if predicate(row))


@pytest.mark.parametrize(
    "transcript, label",
    [
        ("khong", "ASK_CHANGE_OR_CANCEL"),
        ("xyz xyz", "NOT_UNDERSTOOD"),
    ],
)
def test_confirm_labels_every_selected_static_variant(transcript, label, monkeypatch):
    selected = set()

    def capture_variant(ctx, group, *, variants=VARIANT_IDS):
        variant = choose_variant(ctx, group, variants=variants)
        if group == label:
            selected.add(variant)
        return variant

    monkeypatch.setattr(t, "choose_variant", capture_variant)
    case = _case(
        CONFIRM_CASES,
        lambda row: row["question_id"] == "CONFIRM_READBACK" and row["transcript"] == "khong",
    )
    case.update(transcript=transcript, expect_behaviour=label)
    results = []
    for index in range(32):
        result = run_confirm_case(case, f"variant_confirm_eval_{label}_{index}", None, 1)
        results.append(result)
        assert result["observed_behaviour"] == label
        assert result["passed"]
        if selected == set(VARIANT_IDS[:3]):
            break
    assert selected == set(VARIANT_IDS[:3])
    assert confirm_exit_code([summarise_confirm(results, None)]) == 0


def test_reschedule_labels_every_not_understood_variant():
    case = _case(RESCHEDULE_CASES, lambda row: row["id"] == "R001")
    case.update(transcript="xyz xyz", expect="NOT_UNDERSTOOD")
    results = []
    for index in range(32):
        result = run_reschedule_case(case, f"variant_reschedule_eval_{index}", None, 1)
        results.append(result)
        assert result["observed"] == "NOT_UNDERSTOOD"
        assert result["passed"]
        if {row["utterance"] for row in results} == set(t.static_choices(t.NOT_UNDERSTOOD)):
            break
    assert {row["utterance"] for row in results} == set(t.static_choices(t.NOT_UNDERSTOOD))
    assert summarise_reschedule(results, None)["failed_cases"] == 0
