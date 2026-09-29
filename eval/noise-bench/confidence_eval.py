"""Confidence ASR (exp trung bình log-prob token) có tách được ảo giác khỏi lời thật không?

Đọc kết quả bench.py (bản có `final_confidences`): GIẢ = final trong trial chỉ có nhiễu; THẬT =
final trong trial có câu nói mà text trùng decode câu sạch. Chỉ xét final ngắn (<= 2 từ) — loại
ảo giác nguy hiểm nhất ("Ừ", "CÓ"), và giọng nền là lời thật của người khác nên confidence cao là
đúng. In phân vị và, với từng ngưỡng, tỉ lệ ảo giác bị chặn / lời thật bị chặn nhầm.

    .venv/bin/python eval/noise-bench/confidence_eval.py B1target_web B1target_short
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

RESULTS = Path(__file__).resolve().parents[2] / "temp" / "noise-bench" / "results"
MAX_WORDS = 2


def collect(labels: list[str]) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    real, fake = [], []
    for label in labels:
        data = json.loads((RESULTS / f"{label}.json").read_text(encoding="utf-8"))
        for condition in data["conditions"].values():
            for row in condition["cases"]:
                for text, conf in zip(
                    row["finals"], row.get("final_confidences", []), strict=False
                ):
                    if (
                        conf is not None
                        and len(text.split()) <= MAX_WORDS
                        and text == row["clean_batch"]
                    ):
                        real.append((text, conf))
            for row in condition["noise_only"]:
                for text, conf in zip(
                    row["finals"], row.get("final_confidences", []), strict=False
                ):
                    if conf is not None and len(text.split()) <= MAX_WORDS:
                        fake.append((text, conf))
    return real, fake


def main() -> None:
    real, fake = collect(sys.argv[1:])
    r = np.array([c for _, c in real])
    f = np.array([c for _, c in fake])
    print(f"THẬT (final ngắn đúng câu sạch): {len(r)}  GIẢ (final ngắn, trial chỉ nhiễu): {len(f)}")
    for name, values in (("thật", r), ("giả", f)):
        if values.size:
            print(
                f"  {name}: p10={np.percentile(values, 10):.2f} p50={np.median(values):.2f} "
                f"p90={np.percentile(values, 90):.2f}"
            )
    print("  giả hay gặp:", sorted({t for t, _ in fake})[:15])
    print("ngưỡng | ảo giác bị chặn | lời thật bị chặn nhầm")
    for threshold in (0.3, 0.4, 0.5, 0.6, 0.7):
        blocked_fake = float((f < threshold).mean()) if f.size else 0.0
        blocked_real = float((r < threshold).mean()) if r.size else 0.0
        print(f"  {threshold:.1f}  | {blocked_fake:6.0%} | {blocked_real:6.0%}")


if __name__ == "__main__":
    main()
