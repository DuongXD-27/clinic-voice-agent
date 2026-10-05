"""Phần 3 — Đường B (LiveKit) đo phía người gọi: khách nói xong bao lâu thì nghe tiếng bot.

Một client đóng vai người gọi: xin token như trang demo (/livekit/token, outbound + appointment),
vào phòng, publish mic (câu người gọi sinh bằng TTS rồi cache, im lặng giữa các câu như mic thật),
subscribe track của bot và đo năng lượng từng frame 10 ms. Data channel `callbot.transcript` của
bot cho thêm hai mốc phía server, nên mỗi lượt có 4 mốc:

    khách nói xong ─stt_ms─> bot chốt lượt ─engine_ms─> Engine trả câu ─tts_ms─> bot có tiếng
    └──────────────────────────── e2e_ms ─────────────────────────────────────────┘

- tts_ms (Engine trả câu → bot có tiếng) là phần streaming thay đổi; e2e_ms là cái khách cảm nhận.
- Câu chào: vào phòng → bot có tiếng (gồm dispatch worker), và Engine trả câu → bot có tiếng.
- --barge-in: nói chen 1,5 s sau khi bot bắt đầu câu trả lời cuối; đo từ lúc bắt đầu nói chen tới
  lúc bot im (≥ 500 ms không tiếng).

Mốc "có tiếng" là frame đầu vượt ngưỡng năng lượng (--rms), nên gồm cả đoạn lặng đầu câu của
provider và độ trễ mạng — như nhau giữa hai lần chạy cùng provider, nên so trước / sau vẫn đúng.
Không ghi text: chỉ số ký tự câu bot nói. Chạy trong container bot (xem run.sh).

--wav nhận file WAV thay câu TTS, mỗi file một lượt, phát theo thời gian thực.
--include-transcripts lưu thêm text để so với nhãn; --out ghi JSON sạch vào file.
"""

from __future__ import annotations

import argparse
import asyncio
import bisect
import json
import math
import sys
import time
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    BARGE_IN_LINE,
    BOT_CHARS_PER_TURN,
    CALLER_LINES,
    base_meta,
    caller_clip,
    caller_quota,
    emit,
    fmt,
    log,
    result,
    stats,
)

TRANSCRIPT_TOPIC = "callbot.transcript"
RATE = 16_000
FRAME_MS = 10
FRAME_SAMPLES = RATE * FRAME_MS // 1000
SPEECH_END_HOLD_MS = 700  # bot im ≥ 700 ms = nói xong câu (khoảng nghỉ giữa vế ngắn hơn)
BARGE_STOP_HOLD_MS = 500
BARGE_AFTER_MS = 1500
REPLY_DELAY_S = 0.6  # người thật chờ một nhịp rồi mới đáp
PROFILES = {"quick": {"calls": 1, "barge_in": False}, "full": {"calls": 3, "barge_in": True}}


def now_ms() -> float:
    return time.perf_counter() * 1000


class BotAudio:
    """Dòng thời gian năng lượng audio của bot (frame 10 ms) để tìm lúc bắt đầu / dứt tiếng."""

    def __init__(self, threshold: float) -> None:
        self.threshold = threshold
        self.times: list[float] = []
        self.rms: list[float] = []
        self.subscribed_at: float | None = None

    def add(self, at: float, pcm: bytes) -> None:
        samples = array("h", pcm)
        energy = math.sqrt(sum(s * s for s in samples) / len(samples)) if samples else 0.0
        self.times.append(at)
        self.rms.append(energy)

    def onset_after(self, since: float) -> float | None:
        start = bisect.bisect_left(self.times, since)
        for index in range(start, len(self.times)):
            if self.rms[index] > self.threshold:
                return self.times[index]
        return None

    def silence_after(self, since: float, hold_ms: float, now: float) -> float | None:
        """Đầu đoạn im ≥ hold_ms đầu tiên kể từ `since`; frame ngừng về cũng tính là im."""
        start = bisect.bisect_left(self.times, since)
        run_start = None
        for index in range(start, len(self.times)):
            at = self.times[index]
            if self.rms[index] > self.threshold:
                run_start = None
                continue
            run_start = at if run_start is None else run_start
            if at - run_start >= hold_ms:
                return run_start
        last = self.times[-1] if self.times else since
        if now - last >= hold_ms:
            return run_start if run_start is not None else max(since, last)
        return None


class Mic:
    """Phát PCM 16 kHz theo nhịp thời gian thực; không có câu thì phát im lặng như mic thật."""

    def __init__(self, source) -> None:
        self._source = source
        self._pending = b""
        self._done: asyncio.Future | None = None
        self._started_at: float | None = None
        self._running = True

    async def run(self) -> None:
        from livekit import rtc

        silence = b"\x00\x00" * FRAME_SAMPLES
        frame_bytes = FRAME_SAMPLES * 2
        deadline = time.perf_counter()
        while self._running:
            if self._pending:
                if self._started_at is None:
                    self._started_at = now_ms()
                chunk, self._pending = self._pending[:frame_bytes], self._pending[frame_bytes:]
                chunk = chunk.ljust(frame_bytes, b"\x00")
                if not self._pending and self._done is not None and not self._done.done():
                    self._done.set_result((self._started_at, now_ms()))
            else:
                chunk = silence
            frame = rtc.AudioFrame(
                data=chunk, sample_rate=RATE, num_channels=1, samples_per_channel=FRAME_SAMPLES
            )
            await self._source.capture_frame(frame)
            deadline += FRAME_MS / 1000
            await asyncio.sleep(max(0.0, deadline - time.perf_counter()))

    def say(self, pcm: bytes) -> asyncio.Future:
        """Bắt đầu phát một câu; future trả (lúc bắt đầu, lúc phát xong) theo ms."""
        self._done = asyncio.get_running_loop().create_future()
        self._started_at = None
        self._pending = pcm
        return self._done

    def stop(self) -> None:
        self._running = False


class Call:
    def __init__(self, threshold: float, *, include_transcripts: bool = False) -> None:
        self.audio = BotAudio(threshold)
        self.messages: list[dict] = []
        self._tasks: list[asyncio.Task] = []
        self._include_transcripts = include_transcripts

    def on_data(self, packet) -> None:
        if getattr(packet, "topic", None) != TRANSCRIPT_TOPIC:
            return
        try:
            message = json.loads(bytes(packet.data).decode("utf-8"))
        except ValueError:
            return
        self.messages.append(
            {
                "at": now_ms(),
                "role": message.get("role"),
                "turn": message.get("turn"),
                "chars": len(message.get("text") or ""),
                "ended": bool(message.get("ended")),
            }
        )
        if self._include_transcripts:
            self.messages[-1]["text"] = message.get("text") or ""

    def on_track(self, track, publication, participant) -> None:
        from livekit import rtc

        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        self.audio.subscribed_at = now_ms()
        self._tasks.append(asyncio.ensure_future(self._consume(track)))

    async def _consume(self, track) -> None:
        from livekit import rtc

        stream = rtc.AudioStream.from_track(track=track, sample_rate=RATE, num_channels=1)
        try:
            async for event in stream:
                self.audio.add(now_ms(), bytes(event.frame.data))
        finally:
            await stream.aclose()

    def message(self, role: str, turn: int) -> dict | None:
        return next((m for m in self.messages if m["role"] == role and m["turn"] == turn), None)

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)


async def wait_for(check, timeout_s: float, what: str):
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        value = check()
        if value is not None:
            return value
        await asyncio.sleep(0.01)
    raise TimeoutError(what)


def token(base_url: str, appointment: str) -> dict:
    import httpx

    response = httpx.post(
        f"{base_url}/livekit/token",
        json={"direction": "outbound", "appointment_id": appointment},
        timeout=15.0,
    )
    response.raise_for_status()
    return response.json()


async def one_call(
    index: int, args, clips: list[bytes], barge_clip: bytes | None
) -> tuple[str, list[dict]]:
    from livekit import rtc

    grant = token(args.base_url, args.appointment)
    room_name = grant["room_name"]
    call = Call(args.rms, include_transcripts=args.include_transcripts)
    room = rtc.Room()
    room.on("data_received", call.on_data)
    room.on("track_subscribed", call.on_track)
    rows: list[dict] = []
    source = rtc.AudioSource(RATE, 1, queue_size_ms=100)
    mic = Mic(source)
    mic_task = None
    started = now_ms()
    try:
        await room.connect(
            grant["url"], grant["token"], options=rtc.RoomOptions(auto_subscribe=True)
        )
        joined = now_ms()
        track = rtc.LocalAudioTrack.create_audio_track("bench-mic", source)
        await room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )
        mic_task = asyncio.create_task(mic.run())

        # Câu chào
        row = {
            "call_id": room_name,
            "turn": 0,
            "kind": "opening",
            "connect_ms": round(joined - started),
        }
        rows.append(row)
        bot = await wait_for(lambda: call.message("bot", 0), args.timeout, "bot_text_0")
        onset = await wait_for(
            lambda: call.audio.onset_after(max(joined, bot["at"])), args.timeout, "bot_audio_0"
        )
        row.update(
            engine_ms=round(bot["at"] - joined),  # gồm dispatch worker + Clinic + Engine
            tts_ms=round(onset - bot["at"]),
            e2e_ms=round(onset - joined),
            bot_chars=bot["chars"],
            onset_clipped=call.audio.subscribed_at is not None
            and onset - call.audio.subscribed_at < 30,
        )
        end = await wait_for(
            lambda: call.audio.silence_after(onset, SPEECH_END_HOLD_MS, now_ms()), 90, "bot_end_0"
        )
        row["bot_speech_ms"] = round(end - onset)
        ended = bot["ended"]

        turn = 0
        for position, clip in enumerate(clips):
            if ended:
                break
            turn += 1
            await asyncio.sleep(REPLY_DELAY_S)
            said_from, said_to = await mic.say(clip)
            row = {
                "call_id": room_name,
                "turn": turn,
                "kind": "turn",
                "caller_ms": round(said_to - said_from),
            }
            rows.append(row)
            bot = await wait_for(
                lambda t=turn: call.message("bot", t), args.timeout, f"bot_text_{turn}"
            )
            caller = call.message("caller", turn)
            response_since = max(said_to, bot["at"])
            onset = await wait_for(
                lambda since=response_since: call.audio.onset_after(since),
                args.timeout,
                f"bot_audio_{turn}",
            )
            row.update(
                stt_ms=round(caller["at"] - said_to) if caller else None,
                engine_ms=round(bot["at"] - caller["at"]) if caller else None,
                tts_ms=round(onset - bot["at"]),
                e2e_ms=round(onset - said_to),
                bot_chars=bot["chars"],
                # Không có dòng caller: ASR không ra chữ, đây là lượt im lặng (silence timeout)
                valid=caller is not None,
            )
            ended = bot["ended"]
            is_last = position == len(clips) - 1
            if barge_clip is not None and is_last and not ended:
                await barge_in(call, mic, barge_clip, onset, room_name, turn, rows, args)
                break
            end = await wait_for(
                lambda since=onset: call.audio.silence_after(since, SPEECH_END_HOLD_MS, now_ms()),
                90,
                f"bot_end_{turn}",
            )
            row["bot_speech_ms"] = round(end - onset)
    except Exception as exc:  # noqa: BLE001 — bộ đo: ghi bước hỏng rồi sang cuộc sau
        rows.append(
            {"call_id": room_name, "kind": "error", "error": f"{type(exc).__name__}:{exc}"[:120]}
        )
    finally:
        mic.stop()
        if mic_task is not None:
            await asyncio.gather(mic_task, return_exceptions=True)
        await call.close()
        await room.disconnect()
        await source.aclose()
    if args.include_transcripts:
        args.transcripts.extend({"call_id": room_name, **message} for message in call.messages)
    return room_name, rows


async def barge_in(
    call: Call, mic: Mic, clip: bytes, onset: float, room_name: str, turn: int, rows, args
) -> None:
    """Nói chen khi bot đang trả lời; đo bao lâu bot im, rồi đo lượt bot đáp câu nói chen."""
    await asyncio.sleep(max(0.0, (onset + BARGE_AFTER_MS - now_ms()) / 1000))
    row = {"call_id": room_name, "turn": turn + 1, "kind": "barge_in"}
    rows.append(row)
    if call.audio.silence_after(onset, SPEECH_END_HOLD_MS, now_ms()) is not None:
        row["error"] = "bot_done_before_barge_in"  # câu trả lời ngắn hơn 1,5 s
        return
    future = mic.say(clip)
    barge_from = await wait_for(lambda: mic._started_at, 5, "barge_start")
    stop = await wait_for(
        lambda: call.audio.silence_after(barge_from, BARGE_STOP_HOLD_MS, now_ms()), 30, "bot_stop"
    )
    said_from, said_to = await future
    row.update(stop_ms=round(stop - barge_from), caller_ms=round(said_to - said_from))
    try:
        bot = await wait_for(lambda: call.message("bot", turn + 1), args.timeout, "bot_text_barge")
        onset = await wait_for(
            lambda: call.audio.onset_after(max(said_to, bot["at"])),
            args.timeout,
            "bot_audio_barge",
        )
        caller = call.message("caller", turn + 1)
        row.update(
            stt_ms=round(caller["at"] - said_to) if caller else None,
            tts_ms=round(onset - bot["at"]),
            e2e_ms=round(onset - said_to),
            bot_chars=bot["chars"],
        )
    except TimeoutError:
        row["note"] = "không thấy lượt bot đáp câu nói chen"


def wav_clip(path: str) -> bytes:
    from speech.audio.codec import decode_wav

    pcm = decode_wav(Path(path).read_bytes(), target_rate=RATE).pcm
    if not pcm:
        raise ValueError(f"WAV không có audio: {path}")
    return pcm


async def run(args) -> dict:
    cache = Path(args.cache_dir)
    log(f"[livekit {args.label}] nạp audio người gọi...")
    clips = (
        [wav_clip(path) for path in args.wav]
        if args.wav
        else [caller_clip(text, RATE, cache) for text in args.lines]
    )
    barge_clip = None
    if args.barge_in:
        barge_clip = (
            wav_clip(args.barge_in_wav)
            if args.barge_in_wav
            else caller_clip(BARGE_IN_LINE, RATE, cache)
        )
    meta = base_meta(args.label, args.image)
    meta.update(
        base_url=args.base_url,
        appointment=args.appointment,
        calls=args.calls,
        caller_turns=len(clips),
        barge_in=args.barge_in,
        rms_threshold=args.rms,
        caller_source="wav" if args.wav else "tts",
        caller_audio_ms=[round(len(pcm) / 2 / RATE * 1000) for pcm in clips],
    )
    samples, call_ids = [], []
    for index in range(1, args.calls + 1):
        room_name, rows = await one_call(index, args, clips, barge_clip)
        call_ids.append(room_name)
        samples.extend(rows)
        for row in rows:
            log(
                f"  {room_name} {row.get('kind')} {row.get('turn', '')}: e2e {fmt(row.get('e2e_ms'))} ms "
                f"(stt {fmt(row.get('stt_ms'))}, engine {fmt(row.get('engine_ms'))}, tts {fmt(row.get('tts_ms'))})"
                f"{' dừng sau ' + fmt(row.get('stop_ms')) + ' ms' if row.get('kind') == 'barge_in' else ''}"
                f" {row.get('error', '')}"
            )
        if index < args.calls:
            await asyncio.sleep(args.gap)
    meta["call_ids"] = call_ids
    extra = {"transcripts": args.transcripts} if args.include_transcripts else {}
    return result("livekit", meta, samples, **extra)


def summarize(data: dict) -> dict:
    rows = [r for r in data["samples"] if "error" not in r]
    opening = [r for r in rows if r["kind"] == "opening"]
    turns = [r for r in rows if r["kind"] == "turn" and r.get("valid")]
    barge = [r for r in rows if r["kind"] == "barge_in"]
    return {
        "opening": {
            key: stats(r.get(key) for r in opening)
            for key in ("e2e_ms", "engine_ms", "tts_ms", "bot_chars")
        },
        "turn": {
            key: stats(r.get(key) for r in turns)
            for key in ("e2e_ms", "stt_ms", "engine_ms", "tts_ms", "bot_chars")
        },
        "barge_stop": stats(r.get("stop_ms") for r in barge),
        "errors": sum("error" in r for r in data["samples"]),
        "invalid_turns": sum(r["kind"] == "turn" and not r.get("valid") for r in rows),
    }


def report(data: dict) -> str:
    meta, summary = data["meta"], summarize(data)
    lines = [
        f"### LiveKit — {meta['label']} ({meta['started_at']}, {meta['calls']} cuộc, phía người gọi)",
        "",
        "| Lượt | n | E2E latency p50 / p95 (ms) | STT (endpointing + ASR) p50 | Engine p50 "
        "| TTFA p50 (Engine trả câu → có tiếng) | Ký tự bot |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, label in (("opening", "câu chào*"), ("turn", "lượt")):
        row = summary[name]
        lines.append(
            f"| {label} | {row['e2e_ms']['n']} | {fmt(row['e2e_ms']['median'])} / "
            f"{fmt(row['e2e_ms']['p95'])} | {fmt(row.get('stt_ms', {}).get('median'))} "
            f"| {fmt(row['engine_ms']['median'])} | {fmt(row['tts_ms']['median'])} "
            f"| {fmt(row['bot_chars']['median'])} |"
        )
    lines.append(
        "\n*Câu chào: E2E tính từ lúc vào phòng; 'Engine' gồm dispatch worker + Clinic. "
        "p95 cần ≥ 10 mẫu."
    )
    if summary["barge_stop"]["n"]:
        lines.append(
            f"Barge-in stop latency (nói chen → bot im): p50 {fmt(summary['barge_stop']['median'])} ms "
            f"(n={summary['barge_stop']['n']})"
        )
    lines.append(f"Lỗi: {summary['errors']} · lượt ASR không ra chữ: {summary['invalid_turns']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--label", default="run")
    parser.add_argument("--image", default="")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="quick")
    parser.add_argument("--calls", type=int)
    parser.add_argument("--barge-in", action="store_true", default=None)
    parser.add_argument(
        "--base-url", default="http://localhost:8000", help="nơi xin token /livekit/token"
    )
    parser.add_argument("--appointment", default="apt_00427")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--say", action="append", default=None)
    source.add_argument("--wav", action="append", help="WAV người gọi; lặp flag cho mỗi lượt")
    parser.add_argument("--barge-in-wav", help="WAV ngắt lời, tự bật --barge-in")
    parser.add_argument("--include-transcripts", action="store_true", help="lưu text tới engine")
    parser.add_argument(
        "--out", type=Path, help="ghi JSON vào file, tránh stdout của thư viện native"
    )
    parser.add_argument(
        "--rms", type=float, default=300.0, help="ngưỡng năng lượng coi là bot có tiếng"
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="giây chờ tối đa mỗi mốc")
    parser.add_argument("--gap", type=float, default=3.0)
    parser.add_argument("--cache-dir", default="/tmp/bench-cache")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    profile = PROFILES[args.profile]
    args.calls = args.calls if args.calls is not None else profile["calls"]
    args.barge_in = args.barge_in if args.barge_in is not None else profile["barge_in"]
    if args.barge_in_wav:
        args.barge_in = True
    if args.wav and args.barge_in and not args.barge_in_wav:
        parser.error("Dùng WAV và barge-in cần --barge-in-wav; profile quick chỉ phát WAV đã chọn.")
    args.lines = [] if args.wav else args.say or CALLER_LINES
    args.transcripts = []
    args.base_url = args.base_url.rstrip("/")
    if args.calls < 1 or args.timeout <= 0:
        parser.error("--calls và --timeout phải lớn hơn 0")
    for path in (args.wav or []) + ([args.barge_in_wav] if args.barge_in_wav else []):
        try:
            wav_clip(path)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))

    turns = 1 + len(args.wav or args.lines) + (1 if args.barge_in else 0)
    bot = args.calls * turns * BOT_CHARS_PER_TURN
    lines = args.lines + ([BARGE_IN_LINE] if args.barge_in and not args.barge_in_wav else [])
    caller = caller_quota(lines, Path(args.cache_dir))
    log(f"[livekit] dự kiến: bot ~{bot} ký tự (ước lượng), câu người gọi {caller} ký tự")
    if args.dry_run:
        return 0
    data = asyncio.run(run(args))
    log()
    log(report(data))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        log(f"Kết quả: {args.out}")
    else:
        emit(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
