"""Bảng độ trễ TTS theo độ dài câu, đọc từ trace JSONL (TRACE_JSONL_DIR) — không gọi Vbee.

Mỗi span `speech.tts.synthesize` có `character_count`, `ttfa_ms` (byte audio đầu của provider),
`latency_ms` (cả câu), provider thực tế và fallback. Trace không chứa text (NFR-16), nên script
cũng không in text. `latency − ttfa` gần 0 ở câu dài nghĩa là provider gửi khi đã sinh xong
gần hết câu; tăng theo độ dài câu nghĩa là provider sinh và gửi dần.

Chạy trong container trên EC2 (image không có scripts/, đẩy qua stdin):

    docker compose --env-file .env --env-file image.env exec -T bot python - traces < tts_trace_report.py

Local: python scripts/tts_trace_report.py <thư-mục-trace> [--since 2026-10-01] [--rows]
"""

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

OPERATION = "speech.tts.synthesize"
# Ngưỡng nhóm theo số ký tự, khớp ba loại câu của scripts/bench/tts_component.py (45 / 113 / 234)
BUCKETS = ((0, 60, "ngắn ≤ 60"), (61, 150, "vừa 61–150"), (151, 10_000, "dài > 150"))


def load_spans(directory: Path, since: str | None) -> list[dict]:
    spans = []
    for path in sorted(directory.glob("trace-*.jsonl")):
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if record.get("operation") != OPERATION:
                    continue
                if since and str(record.get("start_time", "")) < since:
                    continue
                spans.append(record)
    return spans


def _path(span: dict) -> str:
    # Span LiveKit có các trường barge-in; span HTTP thì không
    return "livekit" if "interrupted" in span else "http"


def _median(values: list[float]) -> str:
    return f"{statistics.median(values):.0f}" if values else "-"


def _p90(values: list[float]) -> str:
    if len(values) < 10:
        return "-"
    ordered = sorted(values)
    return f"{ordered[int(0.9 * (len(ordered) - 1) + 0.5)]:.0f}"


def summarize(spans: list[dict]) -> str:
    lines = [
        "| Đường | Nhóm câu | n | ký tự (trung vị) | ttfa trung vị / p90 (ms) "
        "| tổng trung vị / p90 (ms) | tổng − ttfa trung vị (ms) | fallback | lỗi |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for path in ("http", "livekit"):
        for low, high, label in BUCKETS:
            group = [
                s
                for s in spans
                if _path(s) == path and low <= int(s.get("character_count") or 0) <= high
            ]
            if not group:
                continue
            ok = [s for s in group if s.get("status") == "OK" and s.get("ttfa_ms") is not None]
            ttfa = [float(s["ttfa_ms"]) for s in ok]
            total = [float(s["latency_ms"]) for s in ok if s.get("latency_ms") is not None]
            gap = [
                float(s["latency_ms"]) - float(s["ttfa_ms"])
                for s in ok
                if s.get("latency_ms") is not None
            ]
            chars = [int(s.get("character_count") or 0) for s in group]
            lines.append(
                f"| {path} | {label} | {len(group)} | {statistics.median(chars):.0f} "
                f"| {_median(ttfa)} / {_p90(ttfa)} | {_median(total)} / {_p90(total)} "
                f"| {_median(gap)} | {sum(bool(s.get('fallback_used')) for s in group)} "
                f"| {sum(s.get('status') != 'OK' for s in group)} |"
            )
    return "\n".join(lines)


def rows(spans: list[dict]) -> str:
    lines = ["| thời điểm | đường | ký tự | ttfa | tổng | provider | fallback | status |"]
    lines.append("|---|---|---|---|---|---|---|---|")
    for s in sorted(spans, key=lambda s: str(s.get("start_time"))):
        lines.append(
            f"| {str(s.get('start_time'))[:19]} | {_path(s)} | {s.get('character_count')} "
            f"| {s.get('ttfa_ms') if s.get('ttfa_ms') is None else round(s['ttfa_ms'])} "
            f"| {s.get('latency_ms') if s.get('latency_ms') is None else round(s['latency_ms'])} "
            f"| {s.get('provider_actual')} | {s.get('fallback_used')} | {s.get('status')} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("directory", nargs="?", default="traces")
    parser.add_argument("--since", help="chỉ lấy span bắt đầu từ ngày này, vd. 2026-10-01")
    parser.add_argument("--rows", action="store_true", help="in thêm từng câu (không có text)")
    args = parser.parse_args()

    directory = Path(args.directory)
    if not directory.is_dir():
        print(f"không thấy thư mục trace: {directory.resolve()}", file=sys.stderr)
        return 2
    spans = load_spans(directory, args.since)
    if not spans:
        print(f"không có span {OPERATION} trong {directory.resolve()}", file=sys.stderr)
        return 1

    first = min(str(s.get("start_time")) for s in spans)
    last = max(str(s.get("start_time")) for s in spans)
    providers = Counter(str(s.get("provider_actual")) for s in spans)
    print(
        f"{len(spans)} câu TTS, từ {first[:19]} tới {last[:19]}; provider thực tế: {dict(providers)}"
    )
    print()
    print(summarize(spans))
    if args.rows:
        print()
        print(rows(spans))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
