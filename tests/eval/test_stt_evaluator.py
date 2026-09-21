from __future__ import annotations

import importlib.util
import json
import sys
import wave
from pathlib import Path

import pytest

BENCHMARK_DIR = Path(__file__).resolve().parents[2] / "eval" / "stt-bench"
MODULE_SPEC = importlib.util.spec_from_file_location(
    "stt_benchmark_evaluate", BENCHMARK_DIR / "evaluate.py"
)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
sys.path.insert(0, str(BENCHMARK_DIR))
evaluator = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = evaluator
MODULE_SPEC.loader.exec_module(evaluator)


def _case(
    *,
    reference: str,
    entity_type: str | None = None,
    entity_value: str | None = None,
    critical: bool = True,
    should_produce_text: bool = True,
) -> evaluator.GoldenCase:
    entities = (
        (evaluator.CriticalEntity(type=entity_type, value=entity_value),)
        if entity_type is not None and entity_value is not None
        else ()
    )
    return evaluator.GoldenCase(
        id="CASE_01",
        audio="audio.wav",
        audio_path=Path("audio.wav"),
        category="unit",
        reference=reference,
        critical_entities=entities,
        critical=critical,
        should_produce_text=should_produce_text,
    )


def _write_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\x00\x00" * 80)


def _write_dataset(path: Path, cases: list[dict[str, object]]) -> None:
    dataset = {
        "version": "1.0",
        "suite": {"name": "test", "language": "vi-VN", "total_cases": len(cases)},
        "audio_spec": {
            "sample_rate_hz": 8000,
            "channels": 1,
            "format": "wav",
            "encoding": "pcm_s16le",
        },
        "cases": cases,
    }
    path.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")


def _raw_case(case_id: str, audio: str = "audio.wav") -> dict[str, object]:
    return {
        "id": case_id,
        "audio": audio,
        "category": "unit",
        "reference": "Alo",
        "critical_entities": [],
        "critical": False,
    }


def test_perfect_transcript_has_zero_wer() -> None:
    metrics = evaluator.calculate_wer("Tôi là Nguyễn Văn An.", "tôi là Nguyễn Văn An")

    assert metrics.wer == 0
    assert (metrics.substitutions, metrics.deletions, metrics.insertions) == (0, 0, 0)


def test_substitution_has_nonzero_wer() -> None:
    metrics = evaluator.calculate_wer("ngày mười bốn", "ngày mười lăm")

    assert metrics.wer is not None and metrics.wer > 0
    assert metrics.substitutions == 1


def test_person_name_an_and_anh_is_critical_failure() -> None:
    case = _case(
        reference="Tôi là Nguyễn Văn An.",
        entity_type="person_name",
        entity_value="Nguyễn Văn An",
    )

    score = evaluator.evaluate_case(case, evaluator.STTResult("Tôi là Nguyễn Văn Anh."))

    assert not score.critical_entities_pass
    assert not score.passed
    assert score.failure_reasons == ("CRITICAL_ENTITY",)


def test_day_fourteen_and_four_is_critical_failure() -> None:
    case = _case(
        reference="Ngày 14 tháng 3 năm 1978.",
        entity_type="dob",
        entity_value="14 tháng 3 năm 1978",
    )

    score = evaluator.evaluate_case(case, evaluator.STTResult("Ngày 4 tháng 3 năm 1978."))

    assert not score.critical_entities_pass
    assert not score.passed


def test_spoken_dob_reference_preserves_numeric_entity_representation() -> None:
    case = _case(
        reference="Mười bốn tháng ba năm một nghìn chín trăm bảy mươi tám.",
        entity_type="dob",
        entity_value="14 tháng 3 năm 1978",
    )

    score = evaluator.evaluate_case(
        case,
        evaluator.STTResult("Mười bốn tháng ba năm một nghìn chín trăm bảy mươi tám."),
    )

    assert score.critical_entities_pass
    assert score.passed


def test_missing_negation_is_critical_failure() -> None:
    case = _case(
        reference="Không, tôi không đến được.",
        entity_type="negation",
        entity_value="không đến được",
    )

    score = evaluator.evaluate_case(case, evaluator.STTResult("Có, tôi đến được."))

    assert not score.critical_entities_pass
    assert not score.passed


def test_silence_with_empty_prediction_passes() -> None:
    case = _case(
        reference="",
        critical=True,
        should_produce_text=False,
    )

    score = evaluator.evaluate_case(case, evaluator.STTResult("  ... "))

    assert not score.hallucination
    assert score.passed


def test_silence_with_hallucinated_text_fails() -> None:
    case = _case(
        reference="",
        critical=True,
        should_produce_text=False,
    )

    score = evaluator.evaluate_case(case, evaluator.STTResult("Xin chào"))

    assert score.hallucination
    assert not score.passed
    assert score.failure_reasons == ("HALLUCINATION",)


def test_malformed_prediction_file_has_clear_error(tmp_path: Path) -> None:
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text('{"id": "CASE_01",', encoding="utf-8")

    with pytest.raises(evaluator.EvaluationError, match="malformed prediction JSON on line 1"):
        evaluator.load_predictions(predictions)


def test_duplicate_case_id_is_validation_error(tmp_path: Path) -> None:
    audio = tmp_path / "audio.wav"
    _write_wav(audio)
    dataset = tmp_path / "golden-cases.yaml"
    _write_dataset(dataset, [_raw_case("DUPLICATE"), _raw_case("DUPLICATE")])

    with pytest.raises(evaluator.EvaluationError, match="duplicate case ID: DUPLICATE"):
        evaluator.load_dataset(dataset)


def test_missing_audio_is_validation_error(tmp_path: Path) -> None:
    dataset = tmp_path / "golden-cases.yaml"
    _write_dataset(dataset, [_raw_case("MISSING", "does-not-exist.wav")])

    with pytest.raises(evaluator.EvaluationError, match="audio file not found"):
        evaluator.load_dataset(dataset)
