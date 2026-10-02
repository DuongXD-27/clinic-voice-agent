"""Tách thời gian từng lượt theo trace phía server (STT / Engine / TTS) cho các cuộc gọi của bench.

Đọc JSONL trong TRACE_JSONL_DIR, lọc đúng các cuộc gọi bench bằng `call_key` (HMAC của call_id,
tính bằng key trace có sẵn trong container — không cần lưu call_id vào trace). Trace không chứa
text nên kết quả cũng không có.

Chạy trong container đã phục vụ các cuộc gọi đó (HTTP: bot; LiveKit: livekit-worker):

    docker compose ... exec -T bot python /tmp/bench/traces.py --from-json - < http.json

Lưu ý: span TTS của LiveKit trên bản Vbee chưa stream lấy `ttfa_ms` là byte đầu của Vbee dù bot
phải chờ đủ câu mới phát; số "bot bắt đầu có tiếng" tin được nằm ở livekit_call.py (đo phía người gọi).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import emit, fmt, log, result, stats  # noqa: E402

CORE_OPS = ("core.start_call", "core.handle_turn")


def call_keys(call_ids: list[str]) -> dict[str, str]:
    from callbot.tracing.config import TracingSettings
    from callbot.tracing.pseudonym import CallKeyFactory

    settings = TracingSettings()
    factory = CallKeyFactory(
        settings.pseudonymization_key.get_secret_value(),
        version=settings.key_version,
        environment=settings.environment,
    )
    return {factory.create(call_id): call_id for call_id in call_ids}


def default_dir() -> Path:
    from callbot.tracing.config import TracingSettings

    configured = TracingSettings().jsonl_dir
    return Path(configured) if configured else Path("traces")


def load_spans(directory: Path, keys: dict[str, str]) -> list[dict]:
    spans = []
    for path in sorted(directory.glob("trace-*.jsonl")):
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if record.get("call_key") in keys:
                    record["call_id"] = keys[record["call_key"]]
                    spans.append(record)
    return spans


def _first(group: list[dict], operations: tuple[str, ...]) -> dict:
    return next((s for s in group if s.get("operation") in operations), {})


def turn_rows(spans: list[dict]) -> list[dict]:
    by_trace: dict[str, list[dict]] = defaultdict(list)
    for span in spans:
        by_trace[span["trace_id"]].append(span)
    rows = []
    for group in by_trace.values():
        root = next((s for s in group if s.get("parent_span_id") is None), None)
        if root is None:
            continue

        stt = _first(group, ("speech.stt.transcribe",))
        core = _first(group, CORE_OPS)
        tts = _first(group, ("speech.tts.synthesize",))
        rows.append(
            {
                "call_id": root["call_id"],
                "turn": root.get("turn"),
                "path": "http" if str(root.get("operation", "")).startswith("http.") else "livekit",
                "operation": root.get("operation"),
                "status": root.get("status"),
                "turn_ms": root.get("duration_ms"),
                "stt_ms": stt.get("duration_ms"),
                "stt_final_ms": stt.get("final_ms"),
                "core_ms": core.get("duration_ms"),
                "tts_ms": tts.get("latency_ms"),
                "tts_ttfa_ms": tts.get("ttfa_ms"),
                "tts_chars": tts.get("character_count"),
                "tts_provider": tts.get("provider_actual"),
                "tts_fallback": bool(tts.get("fallback_used")),
                "tts_interrupted": bool(tts.get("interrupted")),
            }
        )
    return sorted(rows, key=lambda r: (r["call_id"], r["turn"] or 0))


def summarize(data: dict) -> dict:
    out = {}
    for path in ("http", "livekit"):
        rows = [r for r in data.get("turns", []) if r["path"] == path]
        if not rows:
            continue
        out[path] = {
            "n": len(rows),
            "turn": stats(r["turn_ms"] for r in rows),
            "stt": stats(r["stt_ms"] for r in rows),
            "core": stats(r["core_ms"] for r in rows),
            "tts": stats(r["tts_ms"] for r in rows),
            "tts_ttfa": stats(r["tts_ttfa_ms"] for r in rows),
            "fallback": sum(r["tts_fallback"] for r in rows),
            "errors": sum(r["status"] != "OK" for r in rows),
        }
    return out


def report(data: dict) -> str:
    lines = [
        "| Đường | n lượt | Turn (server) p50 | STT p50 | Engine p50 | TTS total p50 | TTFA Vbee p50 "
        "| Fallback | Lỗi |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for path, row in summarize(data).items():
        cells = [fmt(row[key]["median"]) for key in ("turn", "stt", "core", "tts", "tts_ttfa")]
        lines.append(
            f"| {path} | {row['n']} | "
            + " | ".join(cells)
            + f" | {row['fallback']} | {row['errors']} |"
        )
    lines.append(
        "\n(ms; LiveKit: 'Turn' và 'TTS total' gồm cả thời gian bot phát; 'TTFA Vbee' là byte đầu "
        "của Vbee về server, chưa phải lúc khách nghe)"
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--from-json", help="file kết quả http/livekit (đọc meta.call_ids); '-' = stdin"
    )
    parser.add_argument("--call-ids", help="danh sách call_id, cách nhau dấu phẩy")
    parser.add_argument("--dir", help="thư mục trace (mặc định TRACE_JSONL_DIR)")
    parser.add_argument("--wait", type=float, default=2.0, help="giây chờ span cuối được ghi")
    args = parser.parse_args()

    source: dict = {}
    if args.from_json:
        text = (
            sys.stdin.read() if args.from_json == "-" else Path(args.from_json).read_text("utf-8")
        )
        source = json.loads(text) if text.strip() else {}
    call_ids = list(source.get("meta", {}).get("call_ids", []))
    if args.call_ids:
        call_ids += [c.strip() for c in args.call_ids.split(",") if c.strip()]
    if not call_ids:
        log("[traces] không có call_id nào")
        return 1

    time.sleep(args.wait)
    directory = Path(args.dir) if args.dir else default_dir()
    meta = {
        "of": source.get("part"),
        "label": source.get("meta", {}).get("label"),
        "dir": str(directory),
    }
    if not directory.is_dir():
        log(f"[traces] không thấy thư mục trace {directory.resolve()} (TRACE_ENABLED tắt?)")
        emit(result("traces", meta, [], turns=[]))
        return 0
    rows = turn_rows(load_spans(directory, call_keys(call_ids)))
    data = result("traces", meta, [], turns=rows)
    log(f"[traces] {len(rows)} lượt có trace / {len(call_ids)} cuộc gọi")
    log(report(data))
    emit(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
