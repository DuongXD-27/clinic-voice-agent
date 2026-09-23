"""So sánh hai lần chạy `confirm_eval.py`: chỉ số tổng và các câu đổi hành vi.

    python scripts/eval_compare.py outputs/eval/confirm/rule outputs/eval/confirm/semantic

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
    ("unsafe_writes", "Ghi sai"),
    ("holdout_behaviour_accuracy", "Chấp nhận được (holdout)"),
    ("holdout_ideal", "Lý tưởng (holdout)"),
    ("agree_reread_rate", "Đồng ý thật không ghi ngay"),
    ("agree_routed", "Đồng ý thật bị gọi model"),
    ("model_calls", "Lượt gọi model"),
)


def _load(path: Path) -> tuple[dict, dict[tuple[str, str], list[dict[str, str]]]]:
    summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
    rows: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    with (path / "results.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rows[(row["question_id"], row["transcript"])].append(row)
    return summary, rows


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

    print(f"| Chỉ số | {a_path.name} | {b_path.name} |")
    print("| --- | --- | --- |")
    for key, name in METRICS:
        values = [[run.get(key, "") for run in s["runs"]] for s in (a, b)]
        print(f"| {name} | {_span(values[0])} | {_span(values[1])} |")
    latency = [
        [run["semantic_latency_ms"]["p95"] for run in s["runs"] if run["semantic_latency_ms"]["n"]]
        for s in (a, b)
    ]
    print(f"| p95 lượt gọi model (ms) | {_span(latency[0] or [0])} | {_span(latency[1] or [0])} |")

    print("\nCâu đổi hành vi:")
    for key in sorted(set(a_rows) | set(b_rows)):
        before = [r["observed_behaviour"] for r in a_rows.get(key, [])]
        after = [r["observed_behaviour"] for r in b_rows.get(key, [])]
        if set(before) == set(after) and len(set(before)) <= 1:
            continue
        ref = (b_rows.get(key) or a_rows.get(key))[0]
        ok = [r["behaviour_ok"] == "True" for r in b_rows.get(key, [])]
        flag = "~" if len(set(after)) > 1 else " "
        mark = "OK " if ok and all(ok) else "SAI"
        kinds = sorted({r.get("semantic_kind", "") for r in b_rows.get(key, [])} - {""})
        print(
            f"  {mark}{flag} {ref['group']:16} {key[1]:40} {before} -> {after}"
            f"  kỳ vọng={ref['expect_behaviour']} model={kinds}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover - script chạy tay
    raise SystemExit(main())
