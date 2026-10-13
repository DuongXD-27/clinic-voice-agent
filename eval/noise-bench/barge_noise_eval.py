"""Đo ngắt lời GIẢ do âm thanh nền khi bot đang nói (người gọi không nói gì), qua đúng STTPipeline +
TurnController + InterruptionController như `barge_in_eval.py`.

Nền: `office` (đoạn không có giọng nói cắt từ dump LiveKit thật), `babble` (3 giọng người khác cộng
lại), `voice2` (một người khác nói từng câu, nghỉ 0,3-1,5 s). Mức `office@-8` = nhiễu nhỏ hơn giọng
người gọi (trung vị bộ câu của `barge_in_eval`) 8 dB. Không có tiếng bot vọng lại. Mỗi điều kiện:
12 câu bot x `--repeats` lần, mỗi lần một đoạn nền khác.

Số liệu: `false_barge` (bot bị ngắt), `with_candidate` (VAD mở ứng viên), `turns` (trial có lượt
gửi engine — đo của luồng chốt lượt, không phải ngắt lời).

Chạy (từ gốc repo):
    PYTHONPATH=src python eval/noise-bench/barge_noise_eval.py --label base
Kết quả: temp/noise-bench/results/barge_noise_<label>.json
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("barge_in_eval", HERE / "barge_in_eval.py")
barge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(barge)
bench = barge.bench

DEFAULT_CONDITIONS = (
    "office@-15,office@-8,office@-3,babble@-12,babble@-6,voice2@-12,voice2@-6,voice2@0"
)
# Nền là giọng người có khoảng nghỉ: đo mức trên đoạn có giọng, như câu người gọi.
_SPEECH_LIKE = frozenset({"voice2"})


def run(label: str, conditions: list[str], repeats: int, overrides: dict) -> dict:
    settings = bench.SpeechSettings(**{**bench.PROFILES["production"], **overrides})
    asr = bench.SpeechRecognizer(bench.create_asr_gateway(settings.asr_provider))
    bots = barge.load_bot_sentences()
    model = settings.silero_vad_model_path
    callers = bench.build_short_set(asr, model) + bench.build_web_set(asr, model)[:20]
    caller_rms = float(np.median([bench._active_rms(c["speech"]) for c in callers]))
    golden = bench.load_golden()
    noises = {
        "office": bench.build_office_noise(model),
        "babble": bench.build_babble([c["speech"] for c in golden]),
        "voice2": bench.build_voice2([c["speech"] for c in golden]),
    }
    results: dict = {"label": label, "settings": overrides, "conditions": {}}
    for condition in conditions:
        name, _, level = condition.partition("@")
        noise, level_db = noises[name], float(level)
        level_of = bench._active_rms if name in _SPEECH_LIKE else bench._rms
        rng = np.random.default_rng(99)
        rows = []
        for _ in range(repeats):
            for text, bot_audio in bots:
                total = int(barge.BOT_START_S * barge.RATE) + len(bot_audio)
                total += int(barge.TAIL_S * barge.RATE)
                start = int(rng.integers(0, len(noise) - total))
                segment = noise[start : start + total].astype(np.float64)
                gain = caller_rms * 10 ** (level_db / 20) / max(level_of(segment), 1e-6)
                mix = segment * gain + rng.normal(0.0, 1.0, total)
                pcm = np.clip(np.round(mix), -32768, 32767).astype(np.int16)
                turn = bench.BotTurn(
                    barge.BOT_START_S,
                    barge.BOT_START_S + len(bot_audio) / barge.RATE + barge.ECHO_DELAY_S,
                    text,
                    np.zeros(len(pcm)),
                    bot_audio,
                )
                out = asyncio.run(bench.run_pipeline(pcm, settings, asr, bot=[turn]))
                rows.append(
                    {
                        "bot": text[:40],
                        "barge_in_at": out["barge_in_at"],
                        "candidates": out["barge_in_candidates"],
                        "turns": out["turns"],
                    }
                )
        summary = {
            "trials": len(rows),
            "false_barge": sum(r["barge_in_at"] is not None for r in rows),
            "with_candidate": sum(bool(r["candidates"]) for r in rows),
            "turns": sum(any(t.strip() for t in r["turns"]) for r in rows),
        }
        results["conditions"][condition] = {"summary": summary, "rows": rows}
        print(f"[{label}] {condition:12} {json.dumps(summary)}", flush=True)
    out_path = bench.WORK_DIR / "results" / f"barge_noise_{label}.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"-> {out_path.relative_to(bench.ROOT)}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--conditions", default=DEFAULT_CONDITIONS)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--set", action="append", default=[], metavar="KHOÁ=GIÁ_TRỊ")
    args = parser.parse_args()
    overrides = dict(item.split("=", 1) for item in args.set)
    run(args.label, args.conditions.split(","), args.repeats, overrides)


if __name__ == "__main__":
    main()
