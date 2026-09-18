"""Validate the TTS suite and aggregate human review without automated MOS."""

from __future__ import annotations

import argparse
import csv
import importlib
import json
import math
import re
import statistics
import sys
import wave
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

import yaml

BENCHMARK_DIR = Path(__file__).resolve().parent
DEFAULT_DATASET = BENCHMARK_DIR / "golden-cases.yaml"
DEFAULT_OUTPUTS_DIR = BENCHMARK_DIR / "outputs"
DEFAULT_RESULTS_DIR = BENCHMARK_DIR / "results"
DEFAULT_REVIEW = DEFAULT_RESULTS_DIR / "tts-review.csv"
DEFAULT_SUMMARY = DEFAULT_RESULTS_DIR / "tts-summary.json"
MOS_DIMENSIONS = ("naturalness", "intelligibility", "pacing", "pronunciation")
REVIEW_COLUMNS = (
    "case_id",
    "category",
    "text",
    "audio_path",
    "zero_tolerance",
    "critical_items",
    "technical_status",
    "technical_notes",
    "critical_content_pass",
    "critical_failures",
    "naturalness",
    "intelligibility",
    "pacing",
    "pronunciation",
    "mos",
    "reviewer_notes",
    "result",
)
VALID_CRITICAL_RESULTS = {"PASS", "FAIL", "NA"}
VALID_TECHNICAL_STATUSES = {"PASS", "WARN", "FAIL"}
CATEGORY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class EvaluationError(ValueError):
    """Raised when dataset, audio, or human review input is invalid."""


@dataclass(frozen=True)
class CriticalItem:
    type: str
    value: str


@dataclass(frozen=True)
class GoldenCase:
    id: str
    category: str
    text: str
    critical_items: tuple[CriticalItem, ...]
    zero_tolerance: bool


@dataclass(frozen=True)
class GoldenDataset:
    path: Path
    name: str
    language: str
    cases: tuple[GoldenCase, ...]


@dataclass(frozen=True)
class TechnicalCheck:
    status: str
    notes: str


@dataclass(frozen=True)
class ReviewScore:
    case_id: str
    reviewed: bool
    critical_content_pass: str | None
    scores: Mapping[str, int]
    mos: float | None
    result: str
    critical_failures: str


@dataclass(frozen=True)
class _AdapterResult:
    audio_path: Path
    latency_ms: float | None


@runtime_checkable
class _AdapterContract(Protocol):
    name: str

    def synthesize(self, text: str, output_path: Path) -> object: ...


def _mapping(value: object, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EvaluationError(f"{location} must be a mapping")
    return value


def _non_empty_string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationError(f"{location} must be a non-empty string")
    return value


def load_dataset(dataset_path: Path) -> GoldenDataset:
    """Load and validate the schema used by the real 40-case golden suite."""
    dataset_path = dataset_path.resolve()
    try:
        raw = yaml.safe_load(dataset_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EvaluationError(f"dataset file not found: {dataset_path}") from exc
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise EvaluationError(f"cannot parse dataset {dataset_path}: {exc}") from exc

    root = _mapping(raw, "dataset")
    suite = _mapping(root.get("suite"), "suite")
    raw_cases = root.get("cases")
    if not isinstance(raw_cases, list):
        raise EvaluationError("cases must be a list")

    declared_total = suite.get("total_cases")
    if not isinstance(declared_total, int) or isinstance(declared_total, bool):
        raise EvaluationError("suite.total_cases must be an integer")

    seen_ids: set[str] = set()
    cases: list[GoldenCase] = []
    for index, raw_case in enumerate(raw_cases, start=1):
        item = _mapping(raw_case, f"cases[{index}]")
        case_id = _non_empty_string(item.get("id"), f"cases[{index}].id")
        if case_id in seen_ids:
            raise EvaluationError(f"duplicate case ID: {case_id}")
        seen_ids.add(case_id)

        category = _non_empty_string(item.get("category"), f"{case_id}.category")
        if not CATEGORY_PATTERN.fullmatch(category):
            raise EvaluationError(
                f"{case_id}.category must contain lowercase letters, numbers, or underscores"
            )
        text = _non_empty_string(item.get("text"), f"{case_id}.text")
        zero_tolerance = item.get("zero_tolerance")
        if not isinstance(zero_tolerance, bool):
            raise EvaluationError(f"{case_id}.zero_tolerance must be a boolean")

        raw_critical_items = item.get("critical_items")
        if not isinstance(raw_critical_items, list):
            raise EvaluationError(f"{case_id}.critical_items must be a list")
        critical_items: list[CriticalItem] = []
        for item_index, raw_critical_item in enumerate(raw_critical_items, start=1):
            critical_item = _mapping(
                raw_critical_item,
                f"{case_id}.critical_items[{item_index}]",
            )
            critical_items.append(
                CriticalItem(
                    type=_non_empty_string(
                        critical_item.get("type"),
                        f"{case_id}.critical_items[{item_index}].type",
                    ),
                    value=_non_empty_string(
                        critical_item.get("value"),
                        f"{case_id}.critical_items[{item_index}].value",
                    ),
                )
            )

        cases.append(
            GoldenCase(
                id=case_id,
                category=category,
                text=text,
                critical_items=tuple(critical_items),
                zero_tolerance=zero_tolerance,
            )
        )

    if declared_total != len(cases):
        raise EvaluationError(
            f"suite.total_cases is {declared_total}, but dataset contains {len(cases)} cases"
        )
    if declared_total != 40:
        raise EvaluationError(f"TTS golden suite must contain 40 cases, got {declared_total}")

    return GoldenDataset(
        path=dataset_path,
        name=_non_empty_string(suite.get("name"), "suite.name"),
        language=_non_empty_string(suite.get("language"), "suite.language"),
        cases=tuple(cases),
    )


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(resolved)


def check_audio(audio_path: Path) -> TechnicalCheck:
    """Check only objective WAV properties; never infer semantic correctness."""
    if not audio_path.is_file():
        return TechnicalCheck("FAIL", f"Audio file missing: {_display_path(audio_path)}")
    size_bytes = audio_path.stat().st_size
    if size_bytes == 0:
        return TechnicalCheck("FAIL", "Audio file is empty (0 bytes)")

    try:
        with wave.open(str(audio_path), "rb") as audio:
            frame_count = audio.getnframes()
            sample_rate = audio.getframerate()
            channel_count = audio.getnchannels()
            sample_width = audio.getsampwidth()
            compression = audio.getcomptype()
    except (OSError, EOFError, wave.Error) as exc:
        return TechnicalCheck("FAIL", f"WAV decode failed: {exc}")

    if frame_count <= 0 or sample_rate <= 0:
        return TechnicalCheck("FAIL", "WAV has zero duration")
    duration_seconds = frame_count / sample_rate
    status = "PASS" if compression == "NONE" else "WARN"
    notes = (
        f"duration_seconds={duration_seconds:.3f}; sample_rate_hz={sample_rate}; "
        f"channels={channel_count}; sample_width_bytes={sample_width}; "
        f"size_bytes={size_bytes}; compression={compression}"
    )
    return TechnicalCheck(status, notes)


def _critical_items_json(case: GoldenCase) -> str:
    return json.dumps(
        [{"type": item.type, "value": item.value} for item in case.critical_items],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def prepare_review(
    dataset: GoldenDataset,
    review_path: Path,
    outputs_dir: Path,
) -> Path:
    """Create a blank human-review scorecard with automated technical checks."""
    if review_path.exists():
        raise EvaluationError(
            f"review scorecard already exists; refusing to overwrite: {review_path}"
        )
    review_path.parent.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    with review_path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        for case in dataset.cases:
            audio_path = outputs_dir / f"{case.id}.wav"
            technical = check_audio(audio_path)
            writer.writerow(
                {
                    "case_id": case.id,
                    "category": case.category,
                    "text": case.text,
                    "audio_path": _display_path(audio_path),
                    "zero_tolerance": str(case.zero_tolerance).lower(),
                    "critical_items": _critical_items_json(case),
                    "technical_status": technical.status,
                    "technical_notes": technical.notes,
                    "critical_content_pass": "",
                    "critical_failures": "",
                    "naturalness": "",
                    "intelligibility": "",
                    "pacing": "",
                    "pronunciation": "",
                    "mos": "",
                    "reviewer_notes": "",
                    "result": "",
                }
            )
    return review_path


def _parse_human_score(value: str, case_id: str, dimension: str) -> int | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        parsed = float(stripped)
    except ValueError as exc:
        raise EvaluationError(f"{case_id}: {dimension} must be an integer from 1 to 5") from exc
    if not parsed.is_integer() or not 1 <= parsed <= 5:
        raise EvaluationError(f"{case_id}: {dimension} must be an integer from 1 to 5")
    return int(parsed)


def calculate_mos(scores: Mapping[str, int]) -> float:
    """Calculate an arithmetic mean from four human-entered dimension scores."""
    missing = [dimension for dimension in MOS_DIMENSIONS if dimension not in scores]
    if missing:
        raise EvaluationError(f"MOS scores missing dimensions: {', '.join(missing)}")
    values = [scores[dimension] for dimension in MOS_DIMENSIONS]
    if any(
        isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5
        for value in values
    ):
        raise EvaluationError("MOS dimensions must be integers from 1 to 5")
    return statistics.fmean(values)


def evaluate_review_row(case: GoldenCase, row: Mapping[str, str]) -> ReviewScore:
    """Validate one human row and apply only the defined zero-tolerance rule."""
    raw_critical = row.get("critical_content_pass", "").strip().upper()
    if raw_critical and raw_critical not in VALID_CRITICAL_RESULTS:
        raise EvaluationError(f"{case.id}: critical_content_pass must be PASS, FAIL, NA, or blank")
    scores = {
        dimension: parsed
        for dimension in MOS_DIMENSIONS
        if (parsed := _parse_human_score(row.get(dimension, ""), case.id, dimension)) is not None
    }
    reviewed = bool(raw_critical) and len(scores) == len(MOS_DIMENSIONS)
    critical_failures = row.get("critical_failures", "").strip()
    if raw_critical == "FAIL" and not critical_failures:
        raise EvaluationError(
            f"{case.id}: critical_failures is required when critical_content_pass is FAIL"
        )

    zero_tolerance_failure = case.zero_tolerance and raw_critical == "FAIL"
    if not reviewed:
        return ReviewScore(
            case_id=case.id,
            reviewed=False,
            critical_content_pass=raw_critical or None,
            scores=scores,
            mos=None,
            result="FAIL" if zero_tolerance_failure else "PENDING",
            critical_failures=critical_failures,
        )

    mos = calculate_mos(scores)
    result = "FAIL" if zero_tolerance_failure else "REVIEWED"
    return ReviewScore(
        case_id=case.id,
        reviewed=True,
        critical_content_pass=raw_critical,
        scores=scores,
        mos=mos,
        result=result,
        critical_failures=critical_failures,
    )


def _read_review_rows(review_path: Path) -> list[dict[str, str]]:
    try:
        with review_path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames is None:
                raise EvaluationError(f"review scorecard has no header: {review_path}")
            missing_columns = [
                column for column in REVIEW_COLUMNS if column not in reader.fieldnames
            ]
            if missing_columns:
                raise EvaluationError(
                    f"review scorecard missing columns: {', '.join(missing_columns)}"
                )
            return [dict(row) for row in reader]
    except (OSError, UnicodeError, csv.Error) as exc:
        raise EvaluationError(f"cannot read review scorecard {review_path}: {exc}") from exc


def _validate_review_identity(
    dataset: GoldenDataset,
    rows: Sequence[Mapping[str, str]],
) -> dict[str, Mapping[str, str]]:
    if len(rows) != len(dataset.cases):
        raise EvaluationError(
            f"review scorecard has {len(rows)} rows, expected {len(dataset.cases)}"
        )
    by_id: dict[str, Mapping[str, str]] = {}
    expected = {case.id: case for case in dataset.cases}
    for row_number, row in enumerate(rows, start=2):
        case_id = row.get("case_id", "").strip()
        if not case_id:
            raise EvaluationError(f"review row {row_number} has no case_id")
        if case_id in by_id:
            raise EvaluationError(f"duplicate review case ID: {case_id}")
        if case_id not in expected:
            raise EvaluationError(f"unknown review case ID: {case_id}")
        case = expected[case_id]
        if row.get("category", "") != case.category or row.get("text", "") != case.text:
            raise EvaluationError(f"{case_id}: category/text differs from golden dataset")
        if row.get("zero_tolerance", "").strip().casefold() != str(case.zero_tolerance).lower():
            raise EvaluationError(f"{case_id}: zero_tolerance differs from golden dataset")
        try:
            critical_items = json.loads(row.get("critical_items", ""))
        except json.JSONDecodeError as exc:
            raise EvaluationError(f"{case_id}: malformed critical_items JSON") from exc
        expected_items = json.loads(_critical_items_json(case))
        if critical_items != expected_items:
            raise EvaluationError(f"{case_id}: critical_items differs from golden dataset")
        technical_status = row.get("technical_status", "").strip().upper()
        if technical_status not in VALID_TECHNICAL_STATUSES:
            raise EvaluationError(f"{case_id}: technical_status must be PASS, WARN, or FAIL")
        by_id[case_id] = row

    missing = sorted(set(expected) - set(by_id))
    if missing:
        raise EvaluationError(f"review scorecard missing case IDs: {', '.join(missing)}")
    return by_id


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def build_summary(
    dataset: GoldenDataset,
    rows_by_id: Mapping[str, Mapping[str, str]],
) -> tuple[dict[str, Any], dict[str, ReviewScore]]:
    reviews = {case.id: evaluate_review_row(case, rows_by_id[case.id]) for case in dataset.cases}
    reviewed = [review for review in reviews.values() if review.reviewed]
    pending = [review for review in reviews.values() if not review.reviewed]
    grouped: dict[str, list[ReviewScore]] = defaultdict(list)
    for case in dataset.cases:
        grouped[case.category].append(reviews[case.id])

    categories: dict[str, dict[str, Any]] = {}
    for category, category_reviews in sorted(grouped.items()):
        category_mos = [review.mos for review in category_reviews if review.mos is not None]
        categories[category] = {
            "total_cases": len(category_reviews),
            "reviewed_cases": sum(review.reviewed for review in category_reviews),
            "pending_cases": sum(not review.reviewed for review in category_reviews),
            "critical_passed": sum(
                review.critical_content_pass == "PASS" for review in category_reviews
            ),
            "critical_failed": sum(
                review.critical_content_pass == "FAIL" for review in category_reviews
            ),
            "mos_mean": _mean(category_mos),
        }

    technical_counts = {status: 0 for status in VALID_TECHNICAL_STATUSES}
    for row in rows_by_id.values():
        technical_counts[row["technical_status"].strip().upper()] += 1

    failed_cases = [
        {
            "case_id": review.case_id,
            "critical_failures": review.critical_failures,
        }
        for review in reviews.values()
        if review.result == "FAIL"
    ]
    mos_values = [review.mos for review in reviewed if review.mos is not None]
    summary = {
        "total_cases": len(dataset.cases),
        "reviewed_cases": len(reviewed),
        "pending_cases": len(pending),
        "pending_case_ids": [review.case_id for review in pending],
        "critical": {
            "passed": sum(review.critical_content_pass == "PASS" for review in reviews.values()),
            "failed": sum(review.critical_content_pass == "FAIL" for review in reviews.values()),
            "not_applicable": sum(
                review.critical_content_pass == "NA" for review in reviews.values()
            ),
        },
        "technical": {
            "passed": technical_counts["PASS"],
            "warnings": technical_counts["WARN"],
            "failed": technical_counts["FAIL"],
        },
        "mos": {
            "mean": _mean(mos_values),
            **{
                f"{dimension}_mean": _mean([review.scores[dimension] for review in reviewed])
                for dimension in MOS_DIMENSIONS
            },
        },
        "categories": categories,
        "failed_cases": failed_cases,
    }
    return summary, reviews


def _write_review_rows(
    review_path: Path,
    rows: Sequence[Mapping[str, str]],
    reviews: Mapping[str, ReviewScore],
) -> None:
    temporary_path = review_path.with_suffix(review_path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        for original_row in rows:
            row = dict(original_row)
            review = reviews[row["case_id"]]
            row["mos"] = "" if review.mos is None else f"{review.mos:.2f}"
            row["result"] = review.result
            writer.writerow({column: row.get(column, "") for column in REVIEW_COLUMNS})
    temporary_path.replace(review_path)


def summarize_review(
    dataset: GoldenDataset,
    review_path: Path,
    summary_path: Path,
) -> dict[str, Any]:
    rows = _read_review_rows(review_path)
    rows_by_id = _validate_review_identity(dataset, rows)
    summary, reviews = build_summary(dataset, rows_by_id)
    _write_review_rows(review_path, rows, reviews)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def _format_mean(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}"


def print_console_summary(summary: Mapping[str, Any]) -> None:
    print("TTS EVALUATION")
    print("==============")
    print()
    print(f"Cases: {summary['total_cases']}")
    print(f"Reviewed: {summary['reviewed_cases']}")
    print(f"Pending: {summary['pending_cases']}")
    print()
    print("Critical content:")
    print(f"PASS: {summary['critical']['passed']}")
    print(f"FAIL: {summary['critical']['failed']}")
    print()
    print("MOS:")
    print(f"Overall: {_format_mean(summary['mos']['mean'])}")
    for dimension in MOS_DIMENSIONS:
        print(f"{dimension.title()}: {_format_mean(summary['mos'][f'{dimension}_mean'])}")
    print()
    print("Technical:")
    print(f"PASS: {summary['technical']['passed']}")
    print(f"WARN: {summary['technical']['warnings']}")
    print(f"FAIL: {summary['technical']['failed']}")
    print()
    if summary["pending_case_ids"]:
        print("PENDING CASES:")
        for case_id in summary["pending_case_ids"]:
            print(case_id)
        print()
    print("FAILED CASES:")
    if not summary["failed_cases"]:
        print("None")
    for failed in summary["failed_cases"]:
        print(f"{failed['case_id']:<14} {failed['critical_failures']}")


def load_adapter(adapter_reference: str) -> _AdapterContract:
    module_name, separator, attribute_name = adapter_reference.partition(":")
    if not separator or not module_name or not attribute_name:
        raise EvaluationError("--adapter must use the format module:attribute")
    try:
        module = importlib.import_module(module_name)
        target = getattr(module, attribute_name)
        adapter = target() if callable(target) else target
    except (ImportError, AttributeError, TypeError) as exc:
        raise EvaluationError(f"cannot load adapter {adapter_reference}: {exc}") from exc
    if not isinstance(adapter, _AdapterContract):
        raise EvaluationError(
            f"adapter {adapter_reference} must provide name and synthesize(text, output_path)"
        )
    if not isinstance(adapter.name, str) or not adapter.name.strip():
        raise EvaluationError(f"adapter {adapter_reference} has an invalid name")
    return adapter


def _coerce_adapter_result(result: object, case_id: str) -> _AdapterResult:
    audio_path = getattr(result, "audio_path", None)
    latency_ms = getattr(result, "latency_ms", None)
    metadata = getattr(result, "metadata", None)
    if not isinstance(audio_path, Path):
        raise EvaluationError(f"{case_id}: adapter result audio_path must be a Path")
    if latency_ms is not None and (
        isinstance(latency_ms, bool)
        or not isinstance(latency_ms, (int, float))
        or not math.isfinite(latency_ms)
        or latency_ms < 0
    ):
        raise EvaluationError(f"{case_id}: adapter latency_ms must be a finite non-negative number")
    if not isinstance(metadata, dict):
        raise EvaluationError(f"{case_id}: adapter metadata must be a dict")
    return _AdapterResult(
        audio_path=audio_path,
        latency_ms=float(latency_ms) if latency_ms is not None else None,
    )


def generate_audio(
    dataset: GoldenDataset,
    adapter: _AdapterContract,
    outputs_dir: Path,
) -> None:
    outputs_dir.mkdir(parents=True, exist_ok=True)
    existing = [outputs_dir / f"{case.id}.wav" for case in dataset.cases]
    existing = [path for path in existing if path.exists()]
    if existing:
        raise EvaluationError(
            f"refusing to overwrite {len(existing)} existing output file(s); remove them explicitly"
        )

    for case in dataset.cases:
        output_path = outputs_dir / f"{case.id}.wav"
        try:
            raw_result = adapter.synthesize(case.text, output_path)
        except Exception as exc:
            raise EvaluationError(f"{case.id}: adapter synthesis failed: {exc}") from exc
        result = _coerce_adapter_result(raw_result, case.id)
        if result.audio_path.resolve() != output_path.resolve():
            raise EvaluationError(
                f"{case.id}: adapter returned {result.audio_path}, expected {output_path}"
            )
        technical = check_audio(output_path)
        if technical.status == "FAIL":
            raise EvaluationError(
                f"{case.id}: generated audio failed technical check: {technical.notes}"
            )
        print(f"{case.id}: {technical.status} ({technical.notes})")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--prepare-review", action="store_true")
    mode.add_argument("--summarize", type=Path, metavar="CSV")
    mode.add_argument("--generate", action="store_true")
    parser.add_argument("--adapter", help="adapter instance/factory as module:attribute")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--outputs-dir", type=Path, default=DEFAULT_OUTPUTS_DIR)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        dataset = load_dataset(args.dataset)
        if args.validate_only:
            if args.adapter:
                raise EvaluationError("--adapter is only valid with --generate")
            print("TTS Dataset validation: PASS")
            print(f"Cases: {len(dataset.cases)}")
            return 0
        if args.prepare_review:
            if args.adapter:
                raise EvaluationError("--adapter is only valid with --generate")
            review_path = args.results_dir / "tts-review.csv"
            prepare_review(dataset, review_path, args.outputs_dir)
            print(f"Human review scorecard: {review_path}")
            print(f"Cases: {len(dataset.cases)}")
            return 0
        if args.summarize:
            if args.adapter:
                raise EvaluationError("--adapter is only valid with --generate")
            summary = summarize_review(
                dataset, args.summarize, args.results_dir / "tts-summary.json"
            )
            print_console_summary(summary)
            return 0
        if not args.adapter:
            raise EvaluationError("--generate requires --adapter module:attribute")
        adapter = load_adapter(args.adapter)
        generate_audio(dataset, adapter, args.outputs_dir)
        print(f"Generated {len(dataset.cases)} audio files with adapter {adapter.name}")
        return 0
    except EvaluationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
