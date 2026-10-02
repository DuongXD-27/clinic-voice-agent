"""Phần 2 — Đường A (HTTP `mode=audio`) đo như harness: response + tải `audio_url` mỗi lượt.

Mỗi cuộc gọi: mở phiên outbound, rồi mỗi câu người gọi: upload WAV qua /demo-api/audio, gửi
`audio_url` vào /turn, đo thời gian response, tải WAV của bot (client riêng, không kèm key, như
harness), kiểm WAV PCM16 mono 8 kHz và trần 8 s (§4.1.2). Câu người gọi sinh bằng TTS rồi cache.

Mặc định gọi qua Caddy (`https://vmec-callbot.tech`) từ trong container bot trên EC2 — cùng đường
harness đi, bỏ phần mạng Internet. Chạy từ máy local (thêm mạng VN, gần với harness ở xa hơn):

    python scripts/bench/http_turns.py --label truoc-local > http-local.json

Không ghi text: chỉ số ký tự câu bot nói. Tách STT / Engine / TTS: chạy traces.py với file này.
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import time
import wave
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    BOT_CHARS_PER_TURN,
    CALLER_LINES,
    TURN_BUDGET_MS,
    base_meta,
    caller_clip,
    caller_quota,
    elapsed_ms,
    emit,
    fmt,
    log,
    result,
    stats,
)

PROFILES = {"quick": {"calls": 1}, "full": {"calls": 3}}
CALLER_RATE = 8000


def api_key(explicit: str | None) -> str:
    if explicit:
        return explicit
    keys = os.environ.get("BOT_API_KEYS", "")
    if not keys and Path(".env").is_file():
        from dotenv import dotenv_values

        keys = dotenv_values(".env").get("BOT_API_KEYS") or ""
    return keys.split(",")[0].strip()


def wav_bytes(pcm: bytes, rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return buffer.getvalue()


def check_wav(data: bytes) -> tuple[str, int | None]:
    try:
        with wave.open(io.BytesIO(data)) as wav:
            rate, channels, width = wav.getframerate(), wav.getnchannels(), wav.getsampwidth()
            audio_ms = round(wav.getnframes() / rate * 1000)
    except (wave.Error, EOFError):
        return "wav_broken", None
    if (rate, channels, width) != (8000, 1, 2):
        return f"wav_{rate}hz_{channels}ch_{width * 8}bit", audio_ms
    return "ok", audio_ms


def fetch(client, audio_url: str | None) -> dict:
    if not audio_url:
        return {"download_ms": None, "wav": "missing_audio_url", "audio_ms": None}
    started = time.perf_counter()
    response = client.get(audio_url)
    download = elapsed_ms(started)
    if response.status_code != 200:
        return {"download_ms": download, "wav": f"http_{response.status_code}", "audio_ms": None}
    wav, audio_ms = check_wav(response.content)
    return {"download_ms": download, "wav": wav, "audio_ms": audio_ms}


def one_call(api, plain, call_id: str, args, clips: list[bytes]) -> list[dict]:
    rows = []
    body = {
        "call_id": call_id,
        "direction": "outbound",
        "appointment_id": args.appointment,
        "caller_number": None,
        "locale": "vi-VN",
        "mode": "audio",
        "max_turns": len(clips) + 2,
    }
    started = time.perf_counter()
    response = api.post("/v1/calls", json=body)
    row = {"call_id": call_id, "turn": 0, "kind": "opening", "request_ms": elapsed_ms(started)}
    if response.status_code != 200:
        row["error"] = f"http_{response.status_code}"
        detail = (
            response.json().get("detail", {})
            if response.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        if isinstance(detail, dict) and detail.get("code"):
            row["error"] += f"_{detail['code']}"
        return [row]
    data = response.json()
    row.update(fetch(plain, data.get("audio_url")), bot_chars=len(data.get("utterance") or ""))
    rows.append(row)

    for turn, clip in enumerate(clips, start=1):
        upload = api.put(
            f"/demo-api/audio/{call_id}/{turn}.wav",
            content=wav_bytes(clip, CALLER_RATE),
            headers={"Content-Type": "audio/wav"},
        )
        row = {"call_id": call_id, "turn": turn, "kind": "turn"}
        if upload.status_code != 200:
            row["error"] = f"upload_http_{upload.status_code}"
            rows.append(row)
            break
        payload = {
            "turn": turn,
            "audio_url": upload.json()["audio_url"],
            "text": None,
            "silence_ms": 0,
        }
        started = time.perf_counter()
        response = api.post(f"/v1/calls/{call_id}/turn", json=payload)
        row["request_ms"] = elapsed_ms(started)
        if response.status_code != 200:
            row["error"] = f"http_{response.status_code}"
            rows.append(row)
            break
        data = response.json()
        row.update(fetch(plain, data.get("audio_url")), bot_chars=len(data.get("utterance") or ""))
        row["ended"] = bool(data.get("ended"))
        rows.append(row)
        if data.get("ended"):
            break
    for row in rows:
        if row.get("request_ms") is not None and row.get("download_ms") is not None:
            row["total_ms"] = round(row["request_ms"] + row["download_ms"], 1)
            row["over_budget"] = row["total_ms"] >= TURN_BUDGET_MS
    return rows


def run(args) -> dict:
    import httpx

    key = api_key(args.api_key)
    cache = Path(args.cache_dir)
    log(f"[http {args.label}] sinh/đọc cache {len(args.lines)} câu người gọi...")
    clips = [caller_clip(text, CALLER_RATE, cache) for text in args.lines]
    meta = base_meta(args.label, args.image)
    meta.update(
        base_url=args.base_url,
        appointment=args.appointment,
        calls=args.calls,
        caller_turns=len(clips),
    )
    samples, call_ids = [], []
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    with (
        httpx.Client(base_url=args.base_url, headers=headers, timeout=30.0) as api,
        httpx.Client(timeout=30.0) as plain,
    ):
        for index in range(1, args.calls + 1):
            call_id = f"bench-http-{args.label}-{datetime.now():%m%d%H%M%S}-{index}"
            call_ids.append(call_id)
            rows = one_call(api, plain, call_id, args, clips)
            samples.extend(rows)
            for row in rows:
                log(
                    f"  {call_id} lượt {row['turn']}: response {fmt(row.get('request_ms'))} ms, "
                    f"tải {fmt(row.get('download_ms'))} ms, {row.get('wav', '')} {row.get('error', '')}"
                )
            if index < args.calls:
                time.sleep(args.gap)
    meta["call_ids"] = call_ids
    return result("http", meta, samples)


def summarize(data: dict) -> dict:
    rows = [r for r in data["samples"] if "error" not in r]
    groups = {"all": rows, "opening": [r for r in rows if r["kind"] == "opening"]}
    groups["turn"] = [r for r in rows if r["kind"] == "turn"]
    out = {}
    for name, group in groups.items():
        out[name] = {
            "request": stats(r.get("request_ms") for r in group),
            "download": stats(r.get("download_ms") for r in group),
            "total": stats(r.get("total_ms") for r in group),
            "bot_chars": stats(r.get("bot_chars") for r in group),
        }
    out["errors"] = sum("error" in r for r in data["samples"])
    out["over_budget"] = sum(bool(r.get("over_budget")) for r in data["samples"])
    out["bad_wav"] = sum(r.get("wav") not in (None, "ok") for r in rows)
    return out


def report(data: dict) -> str:
    meta, summary = data["meta"], summarize(data)
    lines = [
        f"### HTTP — {meta['label']} ({meta['started_at']}, {meta['base_url']}, {meta['calls']} cuộc)",
        "",
        "| Lượt | n | Response p50 / max (ms) | Tải audio p50 (ms) | Turn latency p50 / p95 / max (ms) "
        "| Ký tự bot |",
        "|---|---|---|---|---|---|",
    ]
    for name, label in (("opening", "mở phiên"), ("turn", "lượt"), ("all", "tất cả")):
        row = summary[name]
        lines.append(
            f"| {label} | {row['total']['n']} | {fmt(row['request']['median'])} / {fmt(row['request']['max'])} "
            f"| {fmt(row['download']['median'])} | {fmt(row['total']['median'])} / "
            f"{fmt(row['total']['p95'])} / {fmt(row['total']['max'])} | {fmt(row['bot_chars']['median'])} |"
        )
    lines.append(
        f"\nLỗi: {summary['errors']} · lượt ≥ 8 s: {summary['over_budget']} · WAV sai: {summary['bad_wav']}"
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--label", default="run")
    parser.add_argument("--image", default="")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="quick")
    parser.add_argument("--calls", type=int, help="số cuộc gọi (ghi đè profile)")
    parser.add_argument("--base-url", default="https://vmec-callbot.tech")
    parser.add_argument(
        "--api-key", default=None, help="mặc định: BOT_API_KEYS trong env hoặc .env"
    )
    parser.add_argument("--appointment", default="apt_00427")
    parser.add_argument(
        "--say", action="append", default=None, help="câu người gọi (lặp cho nhiều lượt)"
    )
    parser.add_argument("--gap", type=float, default=3.0, help="giây nghỉ giữa hai cuộc gọi")
    parser.add_argument("--cache-dir", default="/tmp/bench-cache")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.calls is None:
        args.calls = PROFILES[args.profile]["calls"]
    args.lines = args.say or CALLER_LINES
    args.base_url = args.base_url.rstrip("/")

    bot = args.calls * (1 + len(args.lines)) * BOT_CHARS_PER_TURN
    caller = caller_quota(args.lines, Path(args.cache_dir))
    log(f"[http] dự kiến: bot ~{bot} ký tự (ước lượng), câu người gọi {caller} ký tự")
    if args.dry_run:
        return 0
    data = run(args)
    log()
    log(report(data))
    emit(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
