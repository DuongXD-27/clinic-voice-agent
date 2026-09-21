from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest

BENCHMARK_DIR = Path(__file__).resolve().parents[2] / "eval" / "tts-bench"
MODULE_SPEC = importlib.util.spec_from_file_location(
    "tts_benchmark_evaluate", BENCHMARK_DIR / "evaluate.py"
)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
evaluator = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = evaluator
MODULE_SPEC.loader.exec_module(evaluator)
GOLDEN_DATASET = BENCHMARK_DIR / "golden-cases.yaml"


def _case(*, zero_tolerance: bool = True) -> evaluator.GoldenCase:
    return evaluator.GoldenCase(
        id="TTS_TEST_01",
        category="unit_test",
        text="Ngày 14 tháng 10 lúc 9 giờ sáng.",
        critical_items=(evaluator.CriticalItem(type="time", value="9 giờ sáng"),),
        zero_tolerance=zero_tolerance,
    )


def _review_row(
    *,
    critical_content_pass: str = "PASS",
    naturalness: str = "4",
    intelligibility: str = "5",
    pacing: str = "4",
    pronunciation: str = "5",
    critical_failures: str = "",
) -> dict[str, str]:
    return {
        "critical_content_pass": critical_content_pass,
        "critical_failures": critical_failures,
        "naturalness": naturalness,
        "intelligibility": intelligibility,
        "pacing": pacing,
        "pronunciation": pronunciation,
    }


def _write_invalid_dataset(path: Path, cases: list[dict[str, object]]) -> None:
    data = {
        "version": "1.0",
        "suite": {"name": "test", "language": "vi-VN", "total_cases": len(cases)},
        "cases": cases,
    }
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _raw_case(case_id: str) -> dict[str, object]:
    return {
        "id": case_id,
        "category": "identity_prompt",
        "text": "Xin chào",
        "critical_items": [],
        "zero_tolerance": False,
    }


def test_valid_golden_yaml_passes() -> None:
    dataset = evaluator.load_dataset(GOLDEN_DATASET)

    assert len(dataset.cases) == 40


def test_duplicate_id_is_validation_error(tmp_path: Path) -> None:
    dataset_path = tmp_path / "golden.yaml"
    _write_invalid_dataset(dataset_path, [_raw_case("DUPLICATE"), _raw_case("DUPLICATE")])

    with pytest.raises(evaluator.EvaluationError, match="duplicate case ID: DUPLICATE"):
        evaluator.load_dataset(dataset_path)


def test_empty_text_is_validation_error(tmp_path: Path) -> None:
    dataset_path = tmp_path / "golden.yaml"
    case = _raw_case("EMPTY_TEXT")
    case["text"] = "   "
    _write_invalid_dataset(dataset_path, [case])

    with pytest.raises(evaluator.EvaluationError, match=r"EMPTY_TEXT\.text"):
        evaluator.load_dataset(dataset_path)


def test_malformed_critical_items_is_validation_error(tmp_path: Path) -> None:
    dataset_path = tmp_path / "golden.yaml"
    case = _raw_case("BAD_ITEMS")
    case["critical_items"] = {"type": "time", "value": "9 giờ"}
    _write_invalid_dataset(dataset_path, [case])

    with pytest.raises(evaluator.EvaluationError, match=r"BAD_ITEMS\.critical_items"):
        evaluator.load_dataset(dataset_path)


def test_prepare_review_creates_one_blank_row_per_case(tmp_path: Path) -> None:
    dataset = evaluator.load_dataset(GOLDEN_DATASET)
    review_path = tmp_path / "results" / "tts-review.csv"

    evaluator.prepare_review(dataset, review_path, tmp_path / "outputs")

    with review_path.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 40
    assert rows[0]["critical_content_pass"] == ""
    assert rows[0]["naturalness"] == ""
    assert rows[0]["mos"] == ""
    assert rows[0]["result"] == ""


def test_human_scores_four_five_four_five_produce_mos_4_5() -> None:
    review = evaluator.evaluate_review_row(_case(), _review_row())

    assert review.mos == 4.5
    assert review.reviewed


def test_mos_score_outside_one_to_five_is_validation_error() -> None:
    row = _review_row(naturalness="6")

    with pytest.raises(evaluator.EvaluationError, match="naturalness"):
        evaluator.evaluate_review_row(_case(), row)


def test_zero_tolerance_critical_failure_overrides_mos_five() -> None:
    row = _review_row(
        critical_content_pass="FAIL",
        naturalness="5",
        intelligibility="5",
        pacing="5",
        pronunciation="5",
        critical_failures="TIME_MISMATCH: expected 9 giờ, heard 10 giờ",
    )

    review = evaluator.evaluate_review_row(_case(zero_tolerance=True), row)

    assert review.mos == 5.0
    assert review.result == "FAIL"


def test_critical_pass_with_valid_mos_is_not_a_critical_failure() -> None:
    review = evaluator.evaluate_review_row(_case(), _review_row())

    assert review.critical_content_pass == "PASS"
    assert review.result == "REVIEWED"


def test_incomplete_human_review_is_pending_not_pass() -> None:
    row = _review_row(pronunciation="")

    review = evaluator.evaluate_review_row(_case(), row)

    assert not review.reviewed
    assert review.mos is None
    assert review.result == "PENDING"


def test_missing_output_audio_has_clear_technical_status(tmp_path: Path) -> None:
    missing = tmp_path / "outputs" / "TTS_TEST_01.wav"

    technical = evaluator.check_audio(missing)

    assert technical.status == "FAIL"
    assert "Audio file missing" in technical.notes
