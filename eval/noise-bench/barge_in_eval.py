"""Đo ngắt lời (barge-in) khi bot đang nói, có tiếng bot vọng lại (echo), qua đúng STTPipeline +
TurnController + InterruptionController (bench.run_pipeline với `BotTurn`).

Câu bot: 12 câu mẫu TTS đã sinh sẵn (`temp/noise-bench/bot_tts.wav`, đo Quail 30/09), cắt theo
khoảng lặng 0,3 s chèn giữa các câu; text khớp theo thứ tự `_BOT_TEMPLATES`.

Echo: kênh `phone` = câu bot qua G.711 xuống máy người gọi, trễ `ECHO_DELAY_S`, vọng lại qua
G.711 lên (AEC của máy/nhà mạng không khử hết); kênh `web` = trễ + suy giảm, không codec. Mức
`echo@-20` = echo nhỏ hơn giọng người gọi (trung vị bộ câu) 20 dB.

Ba loại trial, bot bắt đầu nói ở `BOT_START_S`:
- `echo_only`: người gọi im lặng. Ngắt lời được xác nhận = ngắt lời GIẢ (bot bị cắt vì chính
  tiếng mình); ứng viên = lần bot sẽ bị tạm dừng nếu có cơ chế tạm dừng -> phát tiếp.
- `caller`: người gọi (bộ short + web) chen vào sau `BARGE_AFTER_S`. Cần được xác nhận; đo trễ
  từ lúc người gọi bắt đầu nói tới lúc ứng viên / xác nhận.
- `other`: người KHÁC (bộ golden) chen vào cùng lúc. Lý tưởng là không xác nhận (cổng giọng
  người gọi); hiện tại đo để làm mốc.

Chạy (từ gốc repo):
    PYTHONPATH=src python eval/noise-bench/barge_in_eval.py --label base
Kết quả: temp/noise-bench/results/barge_<label>.json
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("bench", HERE / "bench.py")
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)

from callbot.engine.dialogue import templates as t  # noqa: E402

RATE = bench.RATE
BOT_START_S = 0.5
BARGE_AFTER_S = 1.0
TAIL_S = 3.0
ECHO_DELAY_S = 0.08
# Thứ tự câu trong bot_tts.wav (sinh bởi script đo Quail, commit c01feec).
_BOT_TEMPLATES = (
    t.GREETING_INBOUND, t.ASK_DOB, t.ASK_NAME_AGAIN, t.ASK_DOB_AGAIN, t.ASK_INTENT_INBOUND,
    t.ASK_CHANGE_OR_CANCEL, t.ASK_ATTENDANCE, t.NOT_UNDERSTOOD, t.SILENCE,
    t.CANCEL_RECONFIRM, t.TRANSFER, t.GOODBYE_UNREACHABLE,
)  # fmt: skip


def load_bot_sentences() -> list[tuple[str, np.ndarray]]:
    samples, _ = bench._read_wav(bench.WORK_DIR / "bot_tts.wav")
    gap = int(0.25 * RATE)
    pieces, start, zeros = [], 0, 0
    for i, value in enumerate(samples):
        zeros = zeros + 1 if value == 0 else 0
        if zeros == gap:
            piece = samples[start : i - gap + 1]
            if len(piece) > RATE // 2:
                pieces.append(piece.astype(np.float64))
            start = i + 1
        elif zeros > gap:
            start = i + 1
    if len(samples) - start > RATE // 2:
        pieces.append(samples[start:].astype(np.float64))
    if len(pieces) != len(_BOT_TEMPLATES):
        raise RuntimeError(f"bot_tts.wav cắt ra {len(pieces)} câu, cần {len(_BOT_TEMPLATES)}")
    return list(zip(_BOT_TEMPLATES, pieces, strict=True))


def make_echo(bot: np.ndarray, total: int, level_rms: float, channel: str) -> np.ndarray:
    echo = np.zeros(total, dtype=np.float64)
    start = int((BOT_START_S + ECHO_DELAY_S) * RATE)
    downlink = bench.phone_channel(bot) if channel == "phone" else bot
    end = min(total, start + len(downlink))
    echo[start:end] = downlink[: end - start]
    echo *= level_rms / max(bench._active_rms(downlink.astype(np.float64)), 1.0)
    return bench.phone_channel(echo).astype(np.float64) if channel == "phone" else echo


def trial(speech: np.ndarray | None, bot_len: int, channel: str, rng) -> np.ndarray:
    total = int(BOT_START_S * RATE) + bot_len + int(TAIL_S * RATE)
    mix = rng.normal(0.0, 1.0, total)
    if speech is not None:
        at = int((BOT_START_S + BARGE_AFTER_S) * RATE)
        end = min(total, at + len(speech))
        mix[at:end] += speech[: end - at]
    pcm = np.clip(np.round(mix), -32768, 32767).astype(np.int16)
    return bench.phone_channel(pcm) if channel == "phone" else pcm


def _p(values: list[float], q: float) -> float | None:
    return round(float(np.percentile(values, q)), 3) if values else None


def run(label: str, channels: list[str], echo_levels: list[float], overrides: dict) -> dict:
    settings = bench.SpeechSettings(**{**bench.PROFILES["production"], **overrides})
    asr = bench.SpeechRecognizer(bench.create_asr_gateway(settings.asr_provider))
    bots = load_bot_sentences()
    model_path = settings.silero_vad_model_path
    callers = bench.build_short_set(asr, model_path) + bench.build_web_set(asr, model_path)[:20]
    others = bench.load_golden()[:20]
    caller_rms = float(np.median([bench._active_rms(c["speech"]) for c in callers]))
    results: dict = {"label": label, "settings": overrides, "conditions": {}}
    for channel in channels:
        for level_db in echo_levels:
            rng = np.random.default_rng(7)
            level_rms = caller_rms * 10 ** (level_db / 20)
            rows: dict[str, list[dict]] = {"echo_only": [], "caller": [], "other": []}
            jobs = [("echo_only", None)] * len(bots)
            jobs += [("caller", c["speech"]) for c in callers]
            jobs += [("other", c["speech"]) for c in others]
            for idx, (kind, speech) in enumerate(jobs):
                text, bot_audio = bots[idx % len(bots)]
                pcm = trial(speech, len(bot_audio), channel, rng)
                echo = make_echo(bot_audio, len(pcm), level_rms, channel)
                end_s = BOT_START_S + len(bot_audio) / RATE + ECHO_DELAY_S
                bot = bench.BotTurn(BOT_START_S, end_s, text, echo)
                out = asyncio.run(bench.run_pipeline(pcm, settings, asr, bot=bot))
                onset = BOT_START_S + BARGE_AFTER_S
                candidates = [c for c in out["barge_in_candidates"] if c >= onset]
                rows[kind].append(
                    {
                        "bot": text[:40],
                        "candidates": out["barge_in_candidates"],
                        "barge_in_at": out["barge_in_at"],
                        "candidate_delay": round(candidates[0] - onset, 3) if candidates else None,
                        "confirm_delay": round(out["barge_in_at"] - onset, 3)
                        if out["barge_in_at"] is not None and speech is not None
                        else None,
                        "turns": out["turns"],
                    }
                )
            summary = {}
            for kind, items in rows.items():
                confirm = [r["confirm_delay"] for r in items if r["confirm_delay"] is not None]
                pause = [r["candidate_delay"] for r in items if r["candidate_delay"] is not None]
                summary[kind] = {
                    "trials": len(items),
                    "with_candidate": sum(bool(r["candidates"]) for r in items),
                    "confirmed": sum(r["barge_in_at"] is not None for r in items),
                    "candidate_delay_p50": _p(pause, 50),
                    "confirm_delay_p50": _p(confirm, 50),
                    "confirm_delay_p90": _p(confirm, 90),
                }
            key = f"{channel}/echo@{level_db:g}"
            results["conditions"][key] = {"summary": summary, "rows": rows}
            print(f"[{label}] {key:16} {json.dumps(summary, ensure_ascii=False)}", flush=True)
    out_path = bench.WORK_DIR / "results" / f"barge_{label}.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"-> {out_path.relative_to(bench.ROOT)}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--channels", default="phone,web")
    parser.add_argument("--echo-levels", default="-30,-20,-10")
    parser.add_argument("--set", action="append", default=[], metavar="KHOÁ=GIÁ_TRỊ")
    args = parser.parse_args()
    overrides = dict(item.split("=", 1) for item in args.set)
    levels = [float(x) for x in args.echo_levels.split(",")]
    run(args.label, args.channels.split(","), levels, overrides)


if __name__ == "__main__":
    main()
