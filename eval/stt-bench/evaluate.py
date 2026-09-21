"""Validate and score the STT Golden Audio Suite without an STT dependency."""

from __future__ import annotations

import argparse
import csv
import importlib
import json
import math
import re
import statistics
import sys
import unicodedata
import wave
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml
from adapters.base import STTAdapter, STTResult

BENCHMARK_DIR = Path(__file__).resolve().parent
DEFAULT_DATASET = BENCHMARK_DIR / "golden-cases.yaml"
DEFAULT_RESULTS_DIR = BENCHMARK_DIR / "results"
CSV_COLUMNS = (
    "case_id",
    "category",
    "audio",
    "reference",
    "prediction",
    "wer",
    "substitutions",
    "deletions",
    "insertions",
    "reference_word_count",
    "critical",
    "critical_entities_pass",
    "critical_failures",
    "hallucination",
    "latency_ms",
    "result",
    "notes",
)


class EvaluationError(ValueError):
    """Raised when benchmark input is invalid or incomplete."""


@dataclass(frozen=True)
class CriticalEntity:
    type: str
    value: str


@dataclass(frozen=True)
class GoldenCase:
    id: str
    audio: str
    audio_path: Path
    category: str
    reference: str
    critical_entities: tuple[CriticalEntity, ...]
    critical: bool
    should_produce_text: bool
    expected_semantic: str | None = None
    expected_signal: str | None = None
    notes: str = ""


@dataclass(frozen=True)
class GoldenDataset:
    path: Path
    name: str
    language: str
    cases: tuple[GoldenCase, ...]
    audio_spec: Mapping[str, Any]


@dataclass(frozen=True)
class WERMetrics:
    substitutions: int
    deletions: int
    insertions: int
    reference_word_count: int
    wer: float | None


@dataclass(frozen=True)
class CriticalFailure:
    type: str
    expected: str
    prediction: str


@dataclass(frozen=True)
class CaseScore:
    case: GoldenCase
    prediction: str
    latency_ms: float | None
    is_final: bool
    wer: WERMetrics
    critical_entities_pass: bool
    critical_failures: tuple[CriticalFailure, ...]
    hallucination: bool
    passed: bool
    failure_reasons: tuple[str, ...]


def _mapping(value: object, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EvaluationError(f"{location} must be a mapping")
    return value


def _non_empty_string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationError(f"{location} must be a non-empty string")
    return value


def _optional_string(value: object, location: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise EvaluationError(f"{location} must be a string when present")
    return value


def _validate_wav(audio_path: Path, audio_spec: Mapping[str, Any], case_id: str) -> None:
    if not audio_path.is_file():
        raise EvaluationError(f"{case_id}: audio file not found: {audio_path}")

    expected_format = str(audio_spec.get("format", "")).casefold()
    if expected_format and audio_path.suffix.casefold() != f".{expected_format}":
        raise EvaluationError(
            f"{case_id}: expected .{expected_format} audio, got {audio_path.suffix}"
        )

    try:
        with wave.open(str(audio_path), "rb") as wav_file:
            actual_rate = wav_file.getframerate()
            actual_channels = wav_file.getnchannels()
            actual_width = wav_file.getsampwidth()
            compression = wav_file.getcomptype()
    except (OSError, EOFError, wave.Error) as exc:
        raise EvaluationError(f"{case_id}: invalid WAV file {audio_path}: {exc}") from exc

    expected_rate = audio_spec.get("sample_rate_hz")
    expected_channels = audio_spec.get("channels")
    if actual_rate != expected_rate:
        raise EvaluationError(f"{case_id}: sample rate is {actual_rate}, expected {expected_rate}")
    if actual_channels != expected_channels:
        raise EvaluationError(
            f"{case_id}: channel count is {actual_channels}, expected {expected_channels}"
        )
    if str(audio_spec.get("encoding", "")).casefold() == "pcm_s16le" and actual_width != 2:
        raise EvaluationError(f"{case_id}: sample width is {actual_width}, expected 2 bytes")
    if compression != "NONE":
        raise EvaluationError(f"{case_id}: compressed WAV is not supported ({compression})")


def load_dataset(dataset_path: Path, *, validate_audio: bool = True) -> GoldenDataset:
    """Load and validate the actual golden YAML schema and referenced audio."""
    dataset_path = dataset_path.resolve()
    try:
        raw = yaml.safe_load(dataset_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EvaluationError(f"dataset file not found: {dataset_path}") from exc
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise EvaluationError(f"cannot parse dataset {dataset_path}: {exc}") from exc

    root = _mapping(raw, "dataset")
    suite = _mapping(root.get("suite"), "suite")
    audio_spec = _mapping(root.get("audio_spec"), "audio_spec")
    raw_cases = root.get("cases")
    if not isinstance(raw_cases, list):
        raise EvaluationError("cases must be a list")

    expected_total = suite.get("total_cases")
    if not isinstance(expected_total, int) or isinstance(expected_total, bool):
        raise EvaluationError("suite.total_cases must be an integer")
    if expected_total != len(raw_cases):
        raise EvaluationError(
            f"suite.total_cases is {expected_total}, but dataset contains {len(raw_cases)} cases"
        )

    cases: list[GoldenCase] = []
    seen_ids: set[str] = set()
    for index, raw_case in enumerate(raw_cases, start=1):
        item = _mapping(raw_case, f"cases[{index}]")
        case_id = _non_empty_string(item.get("id"), f"cases[{index}].id")
        if case_id in seen_ids:
            raise EvaluationError(f"duplicate case ID: {case_id}")
        seen_ids.add(case_id)

        audio = _non_empty_string(item.get("audio"), f"{case_id}.audio")
        category = _non_empty_string(item.get("category"), f"{case_id}.category")
        reference = item.get("reference")
        if not isinstance(reference, str):
            raise EvaluationError(f"{case_id}.reference must be a string")
        critical = item.get("critical")
        if not isinstance(critical, bool):
            raise EvaluationError(f"{case_id}.critical must be a boolean")
        should_produce_text = item.get("should_produce_text", True)
        if not isinstance(should_produce_text, bool):
            raise EvaluationError(f"{case_id}.should_produce_text must be a boolean")
        if should_produce_text and not reference.strip():
            raise EvaluationError(
                f"{case_id}.reference must not be empty when should_produce_text is true"
            )

        raw_entities = item.get("critical_entities", [])
        if not isinstance(raw_entities, list):
            raise EvaluationError(f"{case_id}.critical_entities must be a list")
        entities: list[CriticalEntity] = []
        for entity_index, raw_entity in enumerate(raw_entities, start=1):
            entity = _mapping(
                raw_entity,
                f"{case_id}.critical_entities[{entity_index}]",
            )
            entities.append(
                CriticalEntity(
                    type=_non_empty_string(
                        entity.get("type"),
                        f"{case_id}.critical_entities[{entity_index}].type",
                    ),
                    value=_non_empty_string(
                        entity.get("value"),
                        f"{case_id}.critical_entities[{entity_index}].value",
                    ),
                )
            )

        audio_path = (dataset_path.parent / audio).resolve()
        if validate_audio:
            _validate_wav(audio_path, audio_spec, case_id)

        notes = item.get("notes", "")
        if not isinstance(notes, str):
            raise EvaluationError(f"{case_id}.notes must be a string when present")
        cases.append(
            GoldenCase(
                id=case_id,
                audio=audio,
                audio_path=audio_path,
                category=category,
                reference=reference,
                critical_entities=tuple(entities),
                critical=critical,
                should_produce_text=should_produce_text,
                expected_semantic=_optional_string(
                    item.get("expected_semantic"), f"{case_id}.expected_semantic"
                ),
                expected_signal=_optional_string(
                    item.get("expected_signal"), f"{case_id}.expected_signal"
                ),
                notes=notes.strip(),
            )
        )

    return GoldenDataset(
        path=dataset_path,
        name=_non_empty_string(suite.get("name"), "suite.name"),
        language=_non_empty_string(suite.get("language"), "suite.language"),
        cases=tuple(cases),
        audio_spec=audio_spec,
    )


def normalize_for_wer(text: str) -> str:
    """Normalize casing, punctuation, and whitespace without changing meaning."""
    lowered = unicodedata.normalize("NFC", text).casefold()
    without_punctuation = "".join(
        " " if unicodedata.category(character).startswith("P") else character
        for character in lowered
    )
    return " ".join(without_punctuation.split())


def calculate_wer(reference: str, prediction: str) -> WERMetrics:
    """Return word-level Levenshtein counts and WER."""
    reference_words = normalize_for_wer(reference).split()
    prediction_words = normalize_for_wer(prediction).split()
    # Each cell contains: total edit distance, substitutions, deletions, insertions.
    matrix: list[list[tuple[int, int, int, int]]] = [
        [(0, 0, 0, 0) for _ in range(len(prediction_words) + 1)]
        for _ in range(len(reference_words) + 1)
    ]
    for reference_index in range(1, len(reference_words) + 1):
        matrix[reference_index][0] = (reference_index, 0, reference_index, 0)
    for prediction_index in range(1, len(prediction_words) + 1):
        matrix[0][prediction_index] = (prediction_index, 0, 0, prediction_index)

    def increment(
        value: tuple[int, int, int, int],
        *,
        substitution: int = 0,
        deletion: int = 0,
        insertion: int = 0,
    ) -> tuple[int, int, int, int]:
        return (
            value[0] + substitution + deletion + insertion,
            value[1] + substitution,
            value[2] + deletion,
            value[3] + insertion,
        )

    for reference_index, reference_word in enumerate(reference_words, start=1):
        for prediction_index, prediction_word in enumerate(prediction_words, start=1):
            diagonal = matrix[reference_index - 1][prediction_index - 1]
            if reference_word == prediction_word:
                matrix[reference_index][prediction_index] = diagonal
                continue
            candidates = (
                increment(diagonal, substitution=1),
                increment(matrix[reference_index - 1][prediction_index], deletion=1),
                increment(matrix[reference_index][prediction_index - 1], insertion=1),
            )
            matrix[reference_index][prediction_index] = min(candidates)

    _, substitutions, deletions, insertions = matrix[-1][-1]
    reference_word_count = len(reference_words)
    wer = (
        (substitutions + deletions + insertions) / reference_word_count
        if reference_word_count
        else None
    )
    return WERMetrics(
        substitutions=substitutions,
        deletions=deletions,
        insertions=insertions,
        reference_word_count=reference_word_count,
        wer=wer,
    )


def _contains_phrase(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "


def _entity_is_preserved(case: GoldenCase, entity: CriticalEntity, prediction: str) -> bool:
    normalized_value = normalize_for_wer(entity.value)
    normalized_prediction = normalize_for_wer(prediction)
    if _contains_phrase(normalized_prediction, normalized_value):
        return True

    normalized_reference = normalize_for_wer(case.reference)
    if not _contains_phrase(normalized_reference, normalized_value):
        # The current suite has one DOB whose entity is numeric while its reference is fully
        # spoken. Accept the exact reference representation, without fuzzy number rewriting.
        return normalized_prediction == normalized_reference
    return False


def _has_lexical_speech(text: str) -> bool:
    """Treat any Unicode letter or number as lexical speech; punctuation alone is empty."""
    return any(unicodedata.category(character)[0] in {"L", "N"} for character in text)


def evaluate_case(case: GoldenCase, result: STTResult) -> CaseScore:
    if not isinstance(result.text, str):
        raise EvaluationError(f"{case.id}: adapter result text must be a string")
    if result.latency_ms is not None and (
        isinstance(result.latency_ms, bool)
        or not isinstance(result.latency_ms, (int, float))
        or not math.isfinite(result.latency_ms)
        or result.latency_ms < 0
    ):
        raise EvaluationError(f"{case.id}: latency_ms must be a finite non-negative number")

    critical_failures = tuple(
        CriticalFailure(
            type=entity.type,
            expected=entity.value,
            prediction=result.text,
        )
        for entity in case.critical_entities
        if not _entity_is_preserved(case, entity, result.text)
    )
    critical_entities_pass = not critical_failures
    hallucination = not case.should_produce_text and _has_lexical_speech(result.text)
    passed = not hallucination and (not case.critical or critical_entities_pass)
    failure_reasons: list[str] = []
    if case.critical and not critical_entities_pass:
        failure_reasons.append("CRITICAL_ENTITY")
    if hallucination:
        failure_reasons.append("HALLUCINATION")

    return CaseScore(
        case=case,
        prediction=result.text,
        latency_ms=float(result.latency_ms) if result.latency_ms is not None else None,
        is_final=result.is_final,
        wer=calculate_wer(case.reference, result.text),
        critical_entities_pass=critical_entities_pass,
        critical_failures=critical_failures,
        hallucination=hallucination,
        passed=passed,
        failure_reasons=tuple(failure_reasons),
    )


def load_predictions(predictions_path: Path) -> dict[str, STTResult]:
    """Load strict JSONL predictions indexed by golden case ID."""
    predictions: dict[str, STTResult] = {}
    try:
        lines = predictions_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise EvaluationError(f"cannot read prediction file {predictions_path}: {exc}") from exc

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvaluationError(
                f"malformed prediction JSON on line {line_number}: {exc.msg}"
            ) from exc
        item = _mapping(raw, f"prediction line {line_number}")
        case_id = _non_empty_string(item.get("id"), f"prediction line {line_number}.id")
        if case_id in predictions:
            raise EvaluationError(f"duplicate prediction ID on line {line_number}: {case_id}")
        text = item.get("text")
        if not isinstance(text, str):
            raise EvaluationError(f"prediction {case_id}.text must be a string")
        latency_ms = item.get("latency_ms")
        if latency_ms is not None and (
            isinstance(latency_ms, bool)
            or not isinstance(latency_ms, (int, float))
            or not math.isfinite(latency_ms)
            or latency_ms < 0
        ):
            raise EvaluationError(
                f"prediction {case_id}.latency_ms must be a finite non-negative number"
            )
        is_final = item.get("is_final", True)
        if not isinstance(is_final, bool):
            raise EvaluationError(f"prediction {case_id}.is_final must be a boolean")
        metadata = item.get("metadata", {})
        if not isinstance(metadata, dict):
            raise EvaluationError(f"prediction {case_id}.metadata must be an object")
        predictions[case_id] = STTResult(
            text=text,
            latency_ms=float(latency_ms) if latency_ms is not None else None,
            is_final=is_final,
            metadata=metadata,
        )

    if not predictions:
        raise EvaluationError(f"prediction file contains no predictions: {predictions_path}")
    return predictions


def _predictions_from_adapter(dataset: GoldenDataset, adapter: STTAdapter) -> dict[str, STTResult]:
    predictions: dict[str, STTResult] = {}
    for case in dataset.cases:
        try:
            result = adapter.transcribe(case.audio_path)
        except Exception as exc:
            raise EvaluationError(f"{case.id}: adapter transcription failed: {exc}") from exc
        if not isinstance(result, STTResult):
            raise EvaluationError(f"{case.id}: adapter must return adapters.base.STTResult")
        predictions[case.id] = result
    return predictions


def score_dataset(
    dataset: GoldenDataset,
    predictions: Mapping[str, STTResult],
) -> tuple[CaseScore, ...]:
    expected_ids = {case.id for case in dataset.cases}
    prediction_ids = set(predictions)
    missing = sorted(expected_ids - prediction_ids)
    unexpected = sorted(prediction_ids - expected_ids)
    if missing:
        raise EvaluationError(f"missing predictions for case IDs: {', '.join(missing)}")
    if unexpected:
        raise EvaluationError(f"unknown prediction case IDs: {', '.join(unexpected)}")
    return tuple(evaluate_case(case, predictions[case.id]) for case in dataset.cases)


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def build_summary(model: str, scores: Sequence[CaseScore]) -> dict[str, Any]:
    critical_scores = [score for score in scores if score.case.critical]
    latencies = [score.latency_ms for score in scores if score.latency_ms is not None]
    wers = [score.wer.wer for score in scores if score.wer.wer is not None]
    grouped: dict[str, list[CaseScore]] = defaultdict(list)
    for score in scores:
        grouped[score.case.category].append(score)

    categories: dict[str, dict[str, Any]] = {}
    for category, category_scores in sorted(grouped.items()):
        category_wers = [score.wer.wer for score in category_scores if score.wer.wer is not None]
        categories[category] = {
            "total": len(category_scores),
            "passed": sum(score.passed for score in category_scores),
            "failed": sum(not score.passed for score in category_scores),
            "mean_wer": _mean(category_wers),
            "hallucination_cases": sum(score.hallucination for score in category_scores),
        }

    return {
        "model": model,
        "total_cases": len(scores),
        "passed": sum(score.passed for score in scores),
        "failed": sum(not score.passed for score in scores),
        "critical_passed": sum(score.passed for score in critical_scores),
        "critical_failed": sum(not score.passed for score in critical_scores),
        "hallucination_cases": sum(score.hallucination for score in scores),
        "mean_wer": _mean(wers),
        "median_latency_ms": statistics.median(latencies) if latencies else None,
        "p95_latency_ms": _percentile(latencies, 0.95),
        "categories": categories,
    }


def _safe_model_name(model: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", model.strip()).strip("-._")
    return safe or "stt"


def write_scorecard(
    model: str,
    scores: Sequence[CaseScore],
    results_dir: Path,
) -> tuple[Path, Path, dict[str, Any]]:
    results_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    prefix = f"{_safe_model_name(model)}-{timestamp}"
    csv_path = results_dir / f"{prefix}.csv"
    summary_path = results_dir / f"{prefix}-summary.json"

    with csv_path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for score in scores:
            writer.writerow(
                {
                    "case_id": score.case.id,
                    "category": score.case.category,
                    "audio": score.case.audio,
                    "reference": score.case.reference,
                    "prediction": score.prediction,
                    "wer": score.wer.wer,
                    "substitutions": score.wer.substitutions,
                    "deletions": score.wer.deletions,
                    "insertions": score.wer.insertions,
                    "reference_word_count": score.wer.reference_word_count,
                    "critical": score.case.critical,
                    "critical_entities_pass": score.critical_entities_pass,
                    "critical_failures": json.dumps(
                        [
                            {
                                "type": failure.type,
                                "expected": failure.expected,
                                "prediction": failure.prediction,
                            }
                            for failure in score.critical_failures
                        ],
                        ensure_ascii=False,
                    ),
                    "hallucination": score.hallucination,
                    "latency_ms": score.latency_ms,
                    "result": "PASS" if score.passed else "FAIL",
                    "notes": score.case.notes,
                }
            )

    summary = build_summary(model, scores)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return csv_path, summary_path, summary


def _format_metric(value: float | None, digits: int = 3) -> str:
    return "N/A" if value is None else f"{value:.{digits}f}"


def print_console_summary(summary: Mapping[str, Any], scores: Sequence[CaseScore]) -> None:
    print("STT EVALUATION")
    print("==============")
    print()
    print(f"Model: {summary['model']}")
    print(f"Cases: {summary['total_cases']}")
    print()
    print(f"PASS: {summary['passed']}")
    print(f"FAIL: {summary['failed']}")
    print()
    print(f"Mean WER: {_format_metric(summary['mean_wer'])}")
    print()
    print("Critical:")
    print(f"PASS: {summary['critical_passed']}")
    print(f"FAIL: {summary['critical_failed']}")
    print()
    print("Hallucination:")
    print(summary["hallucination_cases"])
    print()
    print("Latency:")
    print(f"Median: {_format_metric(summary['median_latency_ms'], 1)}")
    print(f"P95: {_format_metric(summary['p95_latency_ms'], 1)}")
    print()
    print("By category:")
    for category, values in summary["categories"].items():
        print(
            f"{category}: PASS {values['passed']}/{values['total']}, "
            f"mean WER {_format_metric(values['mean_wer'])}"
        )
    print()
    print("FAILED CASES:")
    failed = [score for score in scores if not score.passed]
    if not failed:
        print("None")
    for score in failed:
        print(f"{score.case.id:<14} {'+'.join(score.failure_reasons)}")


def load_adapter(adapter_reference: str) -> STTAdapter:
    """Load an adapter instance or zero-argument factory from module:attribute."""
    module_name, separator, attribute_name = adapter_reference.partition(":")
    if not separator or not module_name or not attribute_name:
        raise EvaluationError("--adapter must use the format module:attribute")
    try:
        module = importlib.import_module(module_name)
        target = getattr(module, attribute_name)
        adapter = target() if callable(target) else target
    except (ImportError, AttributeError, TypeError) as exc:
        raise EvaluationError(f"cannot load adapter {adapter_reference}: {exc}") from exc
    if not isinstance(adapter, STTAdapter):
        raise EvaluationError(
            f"adapter {adapter_reference} must provide name and transcribe(audio_path)"
        )
    if not isinstance(adapter.name, str) or not adapter.name.strip():
        raise EvaluationError(f"adapter {adapter_reference} has an invalid name")
    return adapter


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--validate-only",
        action="store_true",
        help="validate YAML and WAV files without transcribing audio",
    )
    mode.add_argument("--predictions", type=Path, help="JSONL predictions to score")
    mode.add_argument(
        "--adapter",
        help="adapter instance or zero-argument factory as module:attribute",
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--model-name", help="override the model name in scorecard output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        dataset = load_dataset(args.dataset)
        if args.validate_only:
            print("Dataset validation: PASS")
            print(f"Cases: {len(dataset.cases)}")
            return 0

        if args.predictions:
            predictions = load_predictions(args.predictions)
            model = args.model_name or args.predictions.stem
        else:
            adapter = load_adapter(args.adapter)
            predictions = _predictions_from_adapter(dataset, adapter)
            model = args.model_name or adapter.name
        scores = score_dataset(dataset, predictions)
        csv_path, summary_path, summary = write_scorecard(model, scores, args.results_dir)
        print_console_summary(summary, scores)
        print()
        print(f"CSV: {csv_path}")
        print(f"Summary: {summary_path}")
        return 0
    except EvaluationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
