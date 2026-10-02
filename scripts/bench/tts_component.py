"""Phần 1 — TTS đo đúng chỗ worker LiveKit gọi: `SpeechSynthesizer.synthesize_stream`.

Hàm này có ở cả bản cũ (Vbee chưa stream: chờ đủ câu rồi đưa một khối) lẫn bản stream, nên cùng
một script so được trước / sau. Mỗi câu gọi Vbee một lần, cho:
- first_ms: chunk đầu tới bên phát = lúc khách bắt đầu nghe (Đường B);
- last_ms: chunk cuối = xong cả câu ≈ thời gian TTS của Đường A (HTTP gom cả câu);
- rtf: thời lượng audio / last_ms (> 1: sinh nhanh hơn phát);
- stall_ms: tổng thời gian bên phát sẽ hết audio chờ chunk sau (giật), mô phỏng phát từ chunk đầu.

Tuỳ chọn:
- --cancel-reps: phát câu dài, hủy 300 ms sau chunk đầu, đo bao lâu stream dừng;
- --fallback-reps: trỏ Vbee vào cổng đóng (chỉ trong process bench) để đo âm đầu khi phải đọc
  bằng provider dự phòng (tốn quota ElevenLabs, không tốn Vbee).

Chạy trong container livekit-worker (xem run.sh). Kết quả JSON ra stdout.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import base_meta, elapsed_ms, emit, fmt, log, median, result, stats  # noqa: E402

# Cùng bộ câu với lần đo 29/09 (docs/evidence/tts-vbee-connection-reuse.md) để so được
SENTENCES = {
    "ngan": "Dạ, anh chị cho em xin ngày tháng năm sinh ạ?",
    "vua": (
        "Cảm ơn anh chị. Lịch khám Nội tổng quát của anh chị là 3 giờ 30 chiều, "
        "ngày 14 tháng 10, tại Vinmec Times City ạ."
    ),
    "dai": (
        "Dạ, em chưa nghe rõ ạ. Cảm ơn anh chị. Lịch khám Nội tổng quát của anh chị là "
        "3 giờ 30 chiều, ngày 14 tháng 10, tại Vinmec Times City ạ. Anh chị có đến khám "
        "được theo lịch này không ạ? Anh chị vui lòng trả lời có hoặc không giúp em ạ."
    ),
}
WARMUP = "ngan"
CANCEL_KIND = "dai"
CANCEL_AFTER_S = 0.3
FALLBACK_KIND = "vua"
DEAD_ENDPOINT = "http://127.0.0.1:9/v1/tts"  # cổng discard: bị từ chối ngay, không treo
PROFILES = {
    "quick": {"reps": 3, "cancel_reps": 0, "fallback_reps": 0},
    "full": {"reps": 5, "cancel_reps": 2, "fallback_reps": 2},
}


def quota(kinds: list[str], reps: int, cancel_reps: int, fallback_reps: int) -> dict[str, int]:
    vbee = len(SENTENCES[WARMUP]) + reps * sum(len(SENTENCES[k]) for k in kinds)
    # Hủy giữa chừng: Vbee vẫn tính cả câu đã gửi
    vbee += cancel_reps * len(SENTENCES[CANCEL_KIND])
    return {"vbee": vbee, "fallback": fallback_reps * len(SENTENCES[FALLBACK_KIND])}


def stall_ms(arrivals: list[tuple[float, int]], sample_rate: int) -> float:
    """Phát từ lúc chunk đầu về; cộng dồn thời gian bên phát hết audio trong khi chờ chunk sau."""
    if not arrivals:
        return 0.0
    clock = arrivals[0][0]  # lúc bắt đầu phát
    buffered_until = clock
    stalled = 0.0
    for at, size in arrivals:
        if at > buffered_until:
            stalled += at - buffered_until
            buffered_until = at
        buffered_until += size / 2 / sample_rate * 1000
    return round(stalled, 1)


async def measure(tts, text: str, kind: str, rep: int) -> dict:
    sample = {"kind": kind, "rep": rep, "chars": len(text)}
    started = time.perf_counter()
    arrivals: list[tuple[float, int]] = []
    try:
        async for chunk in tts.synthesize_stream(text):
            arrivals.append((elapsed_ms(started), len(chunk)))
    except Exception as exc:  # noqa: BLE001 — bộ đo: ghi mã lỗi rồi đo tiếp, không in message
        sample["error"] = getattr(exc, "code", None) or type(exc).__name__
    rate = tts.stream_sample_rate
    audio_ms = sum(size for _, size in arrivals) / 2 / rate * 1000
    info = getattr(tts, "last_stream_result", None)
    last = arrivals[-1][0] if arrivals else None
    sample.update(
        first_ms=arrivals[0][0] if arrivals else None,
        last_ms=last,
        chunks=len(arrivals),
        audio_ms=round(audio_ms),
        rtf=round(audio_ms / last, 1) if last else None,
        stall_ms=stall_ms(arrivals, rate),
        provider_actual=getattr(info, "provider_actual", None),
        fallback_used=bool(getattr(info, "fallback_used", False)),
    )
    return sample


async def measure_cancel(tts, rep: int) -> dict:
    """Hủy 300 ms sau chunk đầu như khách nói chen; đo từ lúc gọi cancel() tới khi stream dừng."""
    text = SENTENCES[CANCEL_KIND]
    sample = {"kind": CANCEL_KIND, "rep": rep, "chars": len(text)}
    first = asyncio.Event()
    after_cancel = {"chunks": 0, "bytes": 0}
    cancelled_at: list[float] = []

    async def consume() -> None:
        async for chunk in tts.synthesize_stream(text):
            first.set()
            if cancelled_at:
                after_cancel["chunks"] += 1
                after_cancel["bytes"] += len(chunk)

    task = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(first.wait(), timeout=10)
        await asyncio.sleep(CANCEL_AFTER_S)
        if task.done():
            # Bản cũ: cả câu là một khối, đã phát xong trước khi kịp hủy
            sample.update(stop_ms=None, note="stream đã xong trước khi hủy (không stream)")
        else:
            cancelled_at.append(time.perf_counter())
            await tts.cancel()
            await asyncio.wait_for(task, timeout=10)
            sample.update(stop_ms=elapsed_ms(cancelled_at[0]))
    except Exception as exc:  # noqa: BLE001
        sample["error"] = getattr(exc, "code", None) or type(exc).__name__
        task.cancel()
    sample.update(
        chunks_after_cancel=after_cancel["chunks"], bytes_after_cancel=after_cancel["bytes"]
    )
    return sample


def build_synthesizer(dead_primary: bool = False):
    from inference.tts import create_tts_gateway
    from speech.bundle import SpeechSynthesizer
    from speech.settings import SpeechSettings

    settings = SpeechSettings()
    saved = os.environ.get("VBEE_ENDPOINT")
    if dead_primary:
        os.environ["VBEE_ENDPOINT"] = DEAD_ENDPOINT
    try:
        gateway = create_tts_gateway(settings.tts_provider, fallback=settings.tts_fallback_provider)
    finally:
        if dead_primary:
            if saved is None:
                os.environ.pop("VBEE_ENDPOINT", None)
            else:
                os.environ["VBEE_ENDPOINT"] = saved
    return settings, gateway, SpeechSynthesizer(gateway)


async def aclose(tts) -> None:
    close = getattr(tts, "aclose", None)
    if close is not None:
        await close()


async def run(args) -> dict:
    settings, gateway, tts = build_synthesizer()
    meta = base_meta(args.label, args.image)
    meta.update(
        provider=settings.tts_provider,
        fallback=settings.tts_fallback_provider,
        model=tts.model,
        sample_rate=tts.stream_sample_rate,
        # Bản cũ: Vbee chưa có synthesize_stream -> SpeechSynthesizer gom cả câu
        provider_streams=hasattr(gateway.provider, "synthesize_stream"),
        reps=args.reps,
        gap_s=args.gap,
        kinds=args.kinds,
    )
    log(f"[tts {args.label}] provider={meta['provider']} stream={meta['provider_streams']}")
    samples, cancels, fallbacks = [], [], []
    try:
        await measure(tts, SENTENCES[WARMUP], WARMUP, 0)  # mở kết nối, không tính
        for rep in range(1, args.reps + 1):
            # Đổi thứ tự mỗi vòng để một lúc mạng chậm không dồn vào một loại câu
            shift = (rep - 1) % len(args.kinds)
            for kind in args.kinds[shift:] + args.kinds[:shift]:
                await asyncio.sleep(args.gap)
                sample = await measure(tts, SENTENCES[kind], kind, rep)
                samples.append(sample)
                log(
                    f"  {kind:<4} #{rep}: đầu {fmt(sample['first_ms'])} ms, xong "
                    f"{fmt(sample['last_ms'])} ms, {sample['chunks']} chunk {sample.get('error', '')}"
                )
        for rep in range(1, args.cancel_reps + 1):
            await asyncio.sleep(args.gap)
            sample = await measure_cancel(tts, rep)
            cancels.append(sample)
            log(
                f"  cancel #{rep}: dừng sau {fmt(sample.get('stop_ms'))} ms {sample.get('error', '')}"
            )
    finally:
        await aclose(tts)

    if args.fallback_reps and settings.tts_fallback_provider:
        _, _, broken = build_synthesizer(dead_primary=True)
        try:
            for rep in range(1, args.fallback_reps + 1):
                await asyncio.sleep(args.gap)
                sample = await measure(broken, SENTENCES[FALLBACK_KIND], FALLBACK_KIND, rep)
                fallbacks.append(sample)
                log(
                    f"  fallback #{rep}: đầu {fmt(sample['first_ms'])} ms {sample.get('error', '')}"
                )
        finally:
            await aclose(broken)
    elif args.fallback_reps:
        log("  bỏ qua fallback: TTS_FALLBACK_PROVIDER chưa cấu hình")

    return result("tts", meta, samples, cancel=cancels, fallback=fallbacks)


# --- tóm tắt (chỉ thư viện chuẩn: compare.py dùng lại) -----------------------------------------


def summarize(data: dict) -> dict:
    rows = {}
    for kind in SENTENCES:
        group = [s for s in data["samples"] if s["kind"] == kind]
        if not group:
            continue
        ok = [s for s in group if "error" not in s and s["first_ms"] is not None]
        rows[kind] = {
            "chars": group[0]["chars"],
            "n": len(group),
            "first": stats(s["first_ms"] for s in ok),
            "last": stats(s["last_ms"] for s in ok),
            "rtf": median(s["rtf"] for s in ok),
            "stall": median(s["stall_ms"] for s in ok),
            "chunks": median(s["chunks"] for s in ok),
            "fallback": sum(s["fallback_used"] for s in group),
            "errors": sum("error" in s for s in group),
        }
    return {
        "rows": rows,
        "cancel_stop": stats(s.get("stop_ms") for s in data.get("cancel", [])),
        "cancel_leak": sum(s.get("chunks_after_cancel", 0) for s in data.get("cancel", [])),
        "fallback_first": stats(s["first_ms"] for s in data.get("fallback", [])),
        "fallback_last": stats(s["last_ms"] for s in data.get("fallback", [])),
    }


def report(data: dict) -> str:
    meta, summary = data["meta"], summarize(data)
    lines = [
        f"### TTS — {meta['label']} ({meta['started_at']}, {meta['provider']}, "
        f"stream={meta['provider_streams']}, {meta['reps']} lần/loại)",
        "",
        "| Câu | Ký tự | n | TTFA p50 (min–max) ms | TTFA p95 ms | TTS total p50 ms | RTF | Stall ms "
        "| Chunk | Fallback | Lỗi |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for kind, row in summary["rows"].items():
        first = row["first"]
        lines.append(
            f"| {kind} | {row['chars']} | {row['n']} | {fmt(first['median'])} "
            f"({fmt(first['min'])}–{fmt(first['max'])}) | {fmt(first['p95'])} "
            f"| {fmt(row['last']['median'])} "
            f"| {fmt(row['rtf'], 1)} | {fmt(row['stall'])} | {fmt(row['chunks'])} "
            f"| {row['fallback']} | {row['errors']} |"
        )
    if data.get("cancel"):
        lines.append(
            f"\nCancel → stream dừng: p50 {fmt(summary['cancel_stop']['median'])} ms "
            f"(n={summary['cancel_stop']['n']}), chunk lọt sau cancel: {summary['cancel_leak']}"
        )
    if data.get("fallback"):
        lines.append(
            f"\nFallback (Vbee lỗi → dự phòng): TTFA p50 {fmt(summary['fallback_first']['median'])} ms, "
            f"TTS total p50 {fmt(summary['fallback_last']['median'])} ms (n={summary['fallback_first']['n']})"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--label", default="run")
    parser.add_argument("--image", default="", help="tag image đang chạy (run.sh tự điền)")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="quick")
    parser.add_argument("--reps", type=int, help="số lần mỗi loại câu (ghi đè profile)")
    parser.add_argument("--cancel-reps", type=int)
    parser.add_argument("--fallback-reps", type=int)
    parser.add_argument("--gap", type=float, default=2.0, help="giây nghỉ giữa hai câu")
    parser.add_argument("--kinds", default="ngan,vua,dai")
    parser.add_argument("--dry-run", action="store_true", help="chỉ in số ký tự quota sẽ tốn")
    args = parser.parse_args()
    for key, value in PROFILES[args.profile].items():
        if getattr(args, key) is None:
            setattr(args, key, value)
    args.kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]
    unknown = [k for k in args.kinds if k not in SENTENCES]
    if unknown:
        parser.error(f"loại câu không có: {unknown}; chọn trong {list(SENTENCES)}")

    cost = quota(args.kinds, args.reps, args.cancel_reps, args.fallback_reps)
    log(f"[tts] dự kiến: Vbee {cost['vbee']} ký tự, dự phòng {cost['fallback']} ký tự")
    if args.dry_run:
        return 0
    data = asyncio.run(run(args))
    log()
    log(report(data))
    emit(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
