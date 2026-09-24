"""So sánh hai lần chạy `confirm_eval.py`: chỉ số tổng và các câu đổi hành vi.

    python scripts/eval_compare.py result/23-09-2026/confirm/rule result/23-09-2026/confirm/semantic

Nhiều lần lặp: chỉ số lấy theo từng lần (min–max); hành vi của một câu là danh sách qua các lần lặp,
câu nào có kết quả khác nhau giữa các lần được đánh dấu `~`. Chỉ đọc file, không gọi API.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

METRICS = (
    ("unsafe_writes", "Unsafe writes"),
    ("holdout_passed", "Correct behaviour (all scored cases)"),
    ("attendance_confirmation_passed", "Attendance confirmed"),
    ("branch_routing_passed", "Correct cancel/reschedule routing"),
    ("rule_passed", "Passed, rule-decidable"),
    ("inference_passed", "Passed, needs inference"),
    ("agree_not_confirmed", "Agreements not confirmed"),
    ("agree_routed", "Agreements sent to model"),
    ("model_calls", "Model calls"),
)


def _load(path: Path) -> tuple[dict, dict[tuple[str, str], list[dict[str, str]]]]:
    summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
    rows: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    with (path / "results.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rows[(row["question_id"], row["transcript"])].append(row)
    return summary, rows


_DENOMINATORS = {
    "attendance_confirmation_passed": "attendance_confirmation_cases",
    "branch_routing_passed": "branch_routing_cases",
    "holdout_passed": "holdout_cases",
    "rule_passed": "rule_cases",
    "inference_passed": "inference_cases",
    "agree_not_confirmed": "agree_cases",
}


def _metric(summary: dict, key: str) -> str:
    """Một chỉ số qua các lần lặp (min–max); đếm được thì kèm mẫu số: "120–121/121"."""
    runs = summary["runs"]
    if key in _DENOMINATORS and all(key in run for run in runs):
        return f"{_span([run[key] for run in runs])}/{runs[0][_DENOMINATORS[key]]}"
    fallback = {
        "holdout_passed": "holdout_behaviour_accuracy",
        "agree_not_confirmed": "agree_reread_rate",
    }
    return _span([run.get(key, run.get(fallback.get(key, ""), "")) for run in runs])


def _span(values: list) -> str:
    low, high = min(values), max(values)
    return f"{low}" if low == high else f"{low}–{high}"


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    a_path, b_path = Path(sys.argv[1]), Path(sys.argv[2])
    a, a_rows = _load(a_path)
    b, b_rows = _load(b_path)

    print(f"| Metric | {a_path.name} | {b_path.name} |")
    print("| --- | --- | --- |")
    for key, name in METRICS:
        values = [_metric(s, key) for s in (a, b)]
        print(f"| {name} | {values[0]} | {values[1]} |")
    latency = [
        [run["semantic_latency_ms"]["p95"] for run in s["runs"] if run["semantic_latency_ms"]["n"]]
        for s in (a, b)
    ]
    print(f"| p95 model call (ms) | {_span(latency[0] or [0])} | {_span(latency[1] or [0])} |")

    print("\nCases whose behaviour changed:")
    for key in sorted(set(a_rows) | set(b_rows)):
        before = [r["observed_behaviour"] for r in a_rows.get(key, [])]
        after = [r["observed_behaviour"] for r in b_rows.get(key, [])]
        if set(before) == set(after) and len(set(before)) <= 1:
            continue
        ref = (b_rows.get(key) or a_rows.get(key))[0]
        ok = [r["behaviour_ok"] == "True" for r in b_rows.get(key, [])]
        flag = "~" if len(set(after)) > 1 else " "
        mark = "PASS" if ok and all(ok) else "FAIL"
        kinds = sorted({r.get("semantic_kind", "") for r in b_rows.get(key, [])} - {""})
        print(
            f"  {mark}{flag} {ref['group']:16} {key[1]:40} {before} -> {after}"
            f"  expected={ref['expect_behaviour']} model={kinds}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover - script chạy tay
    raise SystemExit(main())
