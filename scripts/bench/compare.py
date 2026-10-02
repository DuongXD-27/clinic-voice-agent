"""Tóm tắt một lần chạy bench, hoặc so hai lần (trước / sau) — chỉ dùng thư viện chuẩn.

    python3 bench/compare.py bench-results/truoc                       # tóm tắt một lần
    python3 bench/compare.py bench-results/truoc bench-results/sau     # so trước / sau

Mỗi thư mục do run.sh tạo, gồm tts.json, http.json, http_traces.json, livekit.json,
livekit_traces.json (thiếu phần nào thì bỏ qua phần đó). In markdown ra stdout.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import http_turns  # noqa: E402
import livekit_call  # noqa: E402
import traces  # noqa: E402
import tts_component  # noqa: E402
from common import fmt, fmt_diff, load  # noqa: E402

PARTS = {
    "tts": tts_component,
    "http": http_turns,
    "http_traces": traces,
    "livekit": livekit_call,
    "livekit_traces": traces,
}


def load_run(directory: Path) -> dict[str, dict]:
    return {name: data for name in PARTS if (data := load(directory / f"{name}.json")) is not None}


def summary(directory: Path) -> str:
    run = load_run(directory)
    if not run:
        return f"Không có kết quả trong {directory}"
    blocks = [f"# Benchmark — {directory.name}"]
    meta = next(iter(run.values()))["meta"]
    blocks.append(f"Image: `{meta.get('image') or '?'}` · bắt đầu {meta.get('started_at')}")
    for name, data in run.items():
        if name.endswith("_traces"):
            blocks.append(
                f"### Trace phía server — {name.removesuffix('_traces')}\n\n{traces.report(data)}"
            )
        else:
            blocks.append(PARTS[name].report(data))
    return "\n\n".join(blocks)


def _row(label: str, before, after, note: str = "") -> str:
    return f"| {label} | {fmt(before)} | {fmt(after)} | {fmt_diff(before, after)} | {note} |"


def compare(dir_a: Path, dir_b: Path) -> str:
    a, b = load_run(dir_a), load_run(dir_b)
    header = ["| Chỉ số (ms) | Trước | Sau | Chênh | Ghi chú |", "|---|---|---|---|---|"]
    out = [f"# So sánh benchmark: {dir_a.name} → {dir_b.name}"]
    for name, run in ((dir_a.name, a), (dir_b.name, b)):
        meta = next(iter(run.values()))["meta"] if run else {}
        out.append(f"- **{name}**: image `{meta.get('image') or '?'}`, {meta.get('started_at')}")

    if "livekit" in a and "livekit" in b:
        sa, sb = livekit_call.summarize(a["livekit"]), livekit_call.summarize(b["livekit"])
        rows = [
            _row(
                "E2E latency p50 (khách nói xong → bot có tiếng)",
                sa["turn"]["e2e_ms"]["median"],
                sb["turn"]["e2e_ms"]["median"],
                "khách cảm nhận",
            ),
            _row(
                "E2E latency p95",
                sa["turn"]["e2e_ms"]["p95"],
                sb["turn"]["e2e_ms"]["p95"],
                "cần ≥ 10 lượt",
            ),
            _row(
                "STT p50 (endpointing + ASR)",
                sa["turn"]["stt_ms"]["median"],
                sb["turn"]["stt_ms"]["median"],
                "không đổi khi đổi TTS",
            ),
            _row(
                "Engine p50",
                sa["turn"]["engine_ms"]["median"],
                sb["turn"]["engine_ms"]["median"],
                "không đổi khi đổi TTS",
            ),
            _row(
                "TTFA p50 (Engine trả câu → bot có tiếng)",
                sa["turn"]["tts_ms"]["median"],
                sb["turn"]["tts_ms"]["median"],
                "phần streaming tác động",
            ),
            _row(
                "Câu chào: TTFA p50",
                sa["opening"]["tts_ms"]["median"],
                sb["opening"]["tts_ms"]["median"],
                "câu dài nhất",
            ),
            _row(
                "Câu chào: E2E p50 (vào phòng → có tiếng)",
                sa["opening"]["e2e_ms"]["median"],
                sb["opening"]["e2e_ms"]["median"],
                "gồm dispatch worker",
            ),
            _row(
                "Barge-in stop latency p50 (nói chen → bot im)",
                sa["barge_stop"]["median"],
                sb["barge_stop"]["median"],
                "nếu chạy --barge-in",
            ),
        ]
        out += ["", "## Đường B — cuộc gọi LiveKit (phía người gọi)", "", *header, *rows]
        out.append(
            f"\nSố mẫu lượt: {sa['turn']['e2e_ms']['n']} → {sb['turn']['e2e_ms']['n']} · lỗi: {sa['errors']} → {sb['errors']}"
        )

    if "tts" in a and "tts" in b:
        sa, sb = tts_component.summarize(a["tts"]), tts_component.summarize(b["tts"])
        rows = []
        for kind in tts_component.SENTENCES:
            if kind in sa["rows"] and kind in sb["rows"]:
                ra, rb = sa["rows"][kind], sb["rows"][kind]
                rows.append(
                    _row(
                        f"{kind} ({ra['chars']} ký tự): TTFA p50",
                        ra["first"]["median"],
                        rb["first"]["median"],
                        "Đường B",
                    )
                )
                rows.append(
                    _row(
                        f"{kind} ({ra['chars']} ký tự): TTS total p50",
                        ra["last"]["median"],
                        rb["last"]["median"],
                        "≈ TTS trên Đường A",
                    )
                )
                rows.append(_row(f"{kind}: Stall p50", ra["stall"], rb["stall"], "0 = phát liền"))
        if sa["fallback_first"]["n"] or sb["fallback_first"]["n"]:
            rows.append(
                _row(
                    "Fallback: TTFA p50 (Vbee lỗi → dự phòng)",
                    sa["fallback_first"]["median"],
                    sb["fallback_first"]["median"],
                    "",
                )
            )
        if sa["cancel_stop"]["n"] or sb["cancel_stop"]["n"]:
            rows.append(
                _row(
                    "Cancel → stream dừng p50",
                    sa["cancel_stop"]["median"],
                    sb["cancel_stop"]["median"],
                    "bản cũ: không hủy được",
                )
            )
        out += [
            "",
            "## TTS — đo tại SpeechSynthesizer (container livekit-worker)",
            "",
            *header,
            *rows,
        ]
        out.append(
            f"\nstream: {a['tts']['meta']['provider_streams']} → {b['tts']['meta']['provider_streams']}"
        )

    if "http" in a and "http" in b:
        sa, sb = http_turns.summarize(a["http"]), http_turns.summarize(b["http"])
        rows = [
            _row(
                "Turn latency p50 (response + tải audio)",
                sa["all"]["total"]["median"],
                sb["all"]["total"]["median"],
                "§4.1.2 ≤ 8000",
            ),
            _row("Turn latency max", sa["all"]["total"]["max"], sb["all"]["total"]["max"], ""),
            _row(
                "Turn latency p95",
                sa["all"]["total"]["p95"],
                sb["all"]["total"]["p95"],
                "cần ≥ 10 lượt",
            ),
            _row(
                "Response p50", sa["all"]["request"]["median"], sb["all"]["request"]["median"], ""
            ),
            _row(
                "Tải audio p50",
                sa["all"]["download"]["median"],
                sb["all"]["download"]["median"],
                "",
            ),
        ]
        out += ["", "## Đường A — HTTP như harness", "", *header, *rows]
        out.append(
            f"\nLượt ≥ 8 s: {sa['over_budget']} → {sb['over_budget']} · WAV sai: {sa['bad_wav']} → {sb['bad_wav']} "
            f"· lỗi: {sa['errors']} → {sb['errors']}"
        )
    if "http_traces" in a and "http_traces" in b:
        ta = traces.summarize(a["http_traces"]).get("http")
        tb = traces.summarize(b["http_traces"]).get("http")
        if ta and tb:
            rows = [
                _row(f"Server: {label} p50", ta[key]["median"], tb[key]["median"], "")
                for key, label in (
                    ("turn", "Turn"),
                    ("stt", "STT"),
                    ("core", "Engine"),
                    ("tts", "TTS total"),
                    ("tts_ttfa", "TTFA Vbee"),
                )
            ]
            out += ["", "### Đường A — tách theo trace server", "", *header, *rows]
    return "\n".join(out)


def main() -> int:
    paths = [Path(p) for p in sys.argv[1:]]
    if len(paths) == 1:
        print(summary(paths[0]))
    elif len(paths) == 2:
        print(compare(*paths))
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
