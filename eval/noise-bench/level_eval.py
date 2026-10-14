"""Đo người gọi nói nhỏ / nói xa mic qua đúng pipeline LiveKit (Silero, GipFormer, TurnController,
Validator — `bench.run_pipeline`), bật/tắt `quiet_speech_gain_enabled` bằng `--set`.

Mô hình mức âm (`--level-model`):
- `whole`: nhân cả cuộc gọi (giọng + nhiễu) với `--levels` dB — mic để gain nhỏ, đường điện thoại
  nhỏ tiếng, trình duyệt tắt/không theo kịp AGC.
- `far`: chỉ giọng người gọi nhỏ đi, nhiễu phòng giữ nguyên mức (cầm máy xa): SNR cũng xấu đi.

Mỗi trial là một đoạn cuộc gọi: `--warmup` câu khác của cùng bộ dữ liệu (cùng mức, cùng nhiễu) rồi
mới tới câu được đo — như giữa cuộc gọi, khi các lượt trước đã cho biết mức giọng người gọi.
`--warmup 0` là câu đầu tiên của cuộc gọi. Chỉ chấm lượt chốt sau khi câu được đo bắt đầu.

Ảo giác: cùng phần khởi động có giọng người gọi, rồi `--noise-seconds` giây CHỈ có nhiễu / giọng
người khác (`babble`, `voice2`) — đúng lúc bộ tăng âm (nếu bật) đã tăng hệ số theo giọng người gọi
nhỏ. `false_turns`: số trial có lượt chốt trong đoạn đó; `hallucinated_turns`: chỉ đếm lượt mà phần
lớn chữ không thuộc các câu khởi động — lượt còn lại là câu khởi động chốt muộn (đuôi Silero kéo
dài qua mốc), không phải ảo giác.

Chỉ số: `wer_turn_drift` (lượt so với decode câu sạch), `wer_turn` (so với nhãn, chỉ golden, câu
không chữ số), `no_turn` (câu thật không thành lượt nào), `false_turns`, `hallucinated_turns`.

Chạy (từ gốc repo). Profile `production` theo config/speech.yaml, nơi tăng âm mặc định BẬT cho
web: luôn ghi rõ `quiet_speech_gain_enabled` cho cả hai lần chạy.
    PYTHONPATH=src python eval/noise-bench/level_eval.py --label off --dataset golden \\
        --set quiet_speech_gain_enabled=false
    PYTHONPATH=src python eval/noise-bench/level_eval.py --label gain --dataset golden \\
        --set quiet_speech_gain_enabled=true
Kết quả: temp/noise-bench/results/level_<label>.json
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

RATE = bench.RATE
DEFAULT_CONDITIONS = "clean,office@8,babble@6,voice2@6"
DEFAULT_LEVELS = "0,-15,-25"
# Nền là giọng người có khoảng nghỉ: đo mức trên đoạn có giọng, như câu người gọi.
_SPEECH_LIKE = frozenset({"voice2"})
# Lượt chốt trong chừng này giây đầu đoạn chỉ nhiễu có thể là lượt của câu khởi động trước đó (đuôi
# 2 s của noise-bench + 2 s này: câu khởi động được tăng âm có đuôi Silero dài hơn, 11/10 một lượt
# "CHÍN GIỜ SÁNG" của câu khởi động chốt sau 1 s và bị tính nhầm là ảo giác).
_FALSE_TURN_GRACE_S = 2.0
_FILLERS = frozenset({"Ừ", "À", "Ờ", "DẠ"})


def _from_warmup(turn: str, warmup_words: set[str]) -> bool:
    """Lượt trên đoạn chỉ có nhiễu mà >= 60% chữ (trừ từ đệm) thuộc các câu khởi động."""
    words = [w for w in turn.split() if w not in _FILLERS]
    return bool(words) and sum(w in warmup_words for w in words) >= 0.6 * len(words)


def _scaled(pcm: np.ndarray, level_db: float) -> np.ndarray:
    return pcm.astype(np.float64) * 10 ** (level_db / 20)


class _Mixer:
    """Dựng từng đoạn của cuộc gọi ở một điều kiện nhiễu và một mức âm."""

    def __init__(self, noise, snr_db, level_db, model, speech_like, median_rms, rng) -> None:
        self.noise, self.snr_db, self.level_db, self.model = noise, snr_db, level_db, model
        self.speech_like = speech_like
        self.rng = rng
        # Mức nhiễu của đoạn chỉ nhiễu: theo giọng trung vị ở mức bình thường, như noise-bench.
        self.noise_rms = median_rms / 10 ** (snr_db / 20) if snr_db is not None else 0.0

    def speech(self, speech: np.ndarray) -> np.ndarray:
        """Một câu có đệm trước/sau."""
        if self.model == "whole" or self.noise is None:
            trial = bench.make_trial(
                speech, self.noise, self.snr_db, self.rng, speech_like_noise=self.speech_like
            )
            return _scaled(trial, self.level_db)
        # far: giọng nhỏ đi, nhiễu giữ mức tính theo giọng ở mức bình thường
        target = bench._active_rms(speech) / 10 ** (self.snr_db / 20)
        trial = bench.make_trial(
            _scaled(speech, self.level_db),
            self.noise,
            None,
            self.rng,
            noise_rms_target=target,
            speech_like_noise=self.speech_like,
        )
        return trial.astype(np.float64)

    def noise_only(self, seconds: float) -> np.ndarray:
        pieces, total = [], 0
        while total < seconds * RATE:
            piece = bench.make_trial(
                None,
                self.noise,
                None,
                self.rng,
                noise_rms_target=self.noise_rms,
                speech_like_noise=self.speech_like,
            )
            pieces.append(_scaled(piece, self.level_db) if self.model == "whole" else piece)
            total += len(piece)
        return np.concatenate(pieces).astype(np.float64)


def run(
    label: str,
    dataset: str,
    channel: str,
    conditions: list[str],
    levels: list[float],
    model: str,
    warmup: int,
    noise_trials: int,
    noise_seconds: float,
    overrides: dict,
) -> dict:
    settings = bench.SpeechSettings(**{**bench.PROFILES["production"], **overrides})
    asr = bench.SpeechRecognizer(bench.create_asr_gateway(settings.asr_provider))
    golden = bench.load_golden()
    web = bench.build_web_set(asr, settings.silero_vad_model_path)
    if dataset == "golden":
        cases = golden
    elif dataset == "short":
        cases = bench.build_short_set(asr, settings.silero_vad_model_path)
    else:
        cases = web
    to_channel = bench.phone_channel if channel == "phone" else (lambda x: x)
    clean_ref = {}
    for case in cases:
        clean = to_channel(case["speech"]).astype(np.int16).tobytes()
        clean_ref[case["id"]] = asr.transcribe(bench.AudioSegment(pcm=clean, sample_rate=RATE)).text
    others = web if dataset == "golden" else golden
    noises = {
        "office": bench.build_office_noise(settings.silero_vad_model_path),
        "babble": bench.build_babble([c["speech"] for c in golden]),
        "voice2": bench.build_voice2([c["speech"] for c in others]),
    }
    median_rms = float(np.median([bench._active_rms(c["speech"]) for c in cases]))
    # Câu khởi động lấy từ bộ golden (có lời): câu trả lời 1-3 từ của bộ short quá ngắn để cho biết
    # mức giọng như các lượt trước của một cuộc gọi thật.
    warm_pool = [
        c
        for c in (golden if dataset == "short" else cases)
        if bench._active_rms(c["speech"]) >= 1.0
    ]

    def call(pieces: list[np.ndarray]) -> tuple[dict, float]:
        """Ghép các đoạn thành một cuộc gọi; trả kết quả pipeline và lúc đoạn cuối bắt đầu."""
        audio = np.concatenate(pieces)
        pcm = to_channel(np.clip(np.round(audio), -32768, 32767).astype(np.int16))
        out = asyncio.run(bench.run_pipeline(pcm, settings, asr))
        return out, (len(audio) - len(pieces[-1])) / RATE

    def turns_after(out: dict, at_s: float) -> list[str]:
        return [t for t, when in zip(out["turns"], out["turn_times"], strict=True) if when >= at_s]

    results: dict = {
        "label": label,
        "dataset": dataset,
        "channel": channel,
        "level_model": model,
        "warmup": warmup,
        "settings": overrides,
        "conditions": {},
    }
    for condition in conditions:
        name, _, snr_text = condition.partition("@")
        noise = noises.get(name)
        snr_db = float(snr_text) if snr_text else None
        for level_db in levels:
            mix = _Mixer(
                noise,
                snr_db,
                level_db,
                model,
                name in _SPEECH_LIKE,
                median_rms,
                np.random.default_rng(1234),
            )
            rows = []
            for index, case in enumerate(cases):
                pieces = [
                    mix.speech(warm_pool[(index + k + 1) % len(warm_pool)]["speech"])
                    for k in range(warmup)
                ]
                pieces.append(mix.speech(case["speech"]))
                out, start_s = call(pieces)
                turns = turns_after(out, start_s + bench.LEAD_S)
                err, n = bench._wer(clean_ref[case["id"]], " ".join(turns))
                row = {
                    "id": case["id"],
                    "reference": case["reference"],
                    "clean_batch": clean_ref[case["id"]],
                    "turns": turns,
                    "drift_errors": err,
                    "drift_words": n,
                }
                if case["reference"] and not bench._has_digit(case["reference"]):
                    gold_err, gold_n = bench._wer(case["reference"], " ".join(turns))
                    row.update(golden_errors=gold_err, golden_words=gold_n)
                rows.append(row)
            false_rows, halluc_rows = [], []
            if noise is not None:
                for k in range(noise_trials):
                    warm = [warm_pool[(k * 3 + j) % len(warm_pool)] for j in range(warmup)]
                    pieces = [mix.speech(c["speech"]) for c in warm]
                    pieces.append(mix.noise_only(noise_seconds))
                    out, start_s = call(pieces)
                    turns = [
                        t for t in turns_after(out, start_s + _FALSE_TURN_GRACE_S) if t.strip()
                    ]
                    warm_words = {
                        w
                        for c in warm
                        for w in f"{c['reference']} {clean_ref.get(c['id'], '')}".split()
                    }
                    false_rows.append(turns)
                    halluc_rows.append([t for t in turns if not _from_warmup(t, warm_words)])
            drift_n = sum(r["drift_words"] for r in rows)
            gold_n = sum(r.get("golden_words", 0) for r in rows)
            summary = {
                "trials": len(rows),
                "wer_turn_drift": round(sum(r["drift_errors"] for r in rows) / drift_n, 3)
                if drift_n
                else None,
                "wer_turn": round(sum(r.get("golden_errors", 0) for r in rows) / gold_n, 3)
                if gold_n
                else None,
                "no_turn": sum(1 for r in rows if not r["turns"]),
                "false_turns": sum(1 for turns in false_rows if turns)
                if noise is not None
                else None,
                "hallucinated_turns": sum(1 for turns in halluc_rows if turns)
                if noise is not None
                else None,
                "noise_trials": len(false_rows),
            }
            key = f"{condition}/{level_db:g}dB"
            results["conditions"][key] = {
                "summary": summary,
                "rows": rows,
                "false": false_rows,
                "hallucinated": halluc_rows,
            }
            print(f"[{label}] {key:18} {json.dumps(summary)}", flush=True)
    out_path = bench.WORK_DIR / "results" / f"level_{label}.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"-> {out_path.relative_to(bench.ROOT)}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--dataset", choices=("golden", "web", "short"), default="golden")
    parser.add_argument("--channel", choices=bench.CHANNELS, default="web")
    parser.add_argument("--conditions", default=DEFAULT_CONDITIONS)
    parser.add_argument("--levels", default=DEFAULT_LEVELS)
    parser.add_argument("--level-model", choices=("whole", "far"), default="whole")
    parser.add_argument("--warmup", type=int, default=2, help="số câu trước câu được đo")
    parser.add_argument("--noise-trials", type=int, default=bench.NOISE_ONLY_TRIALS)
    parser.add_argument("--noise-seconds", type=float, default=8.0)
    parser.add_argument("--set", action="append", default=[], metavar="KHOÁ=GIÁ_TRỊ")
    args = parser.parse_args()
    run(
        args.label,
        args.dataset,
        args.channel,
        args.conditions.split(","),
        [float(x) for x in args.levels.split(",")],
        args.level_model,
        args.warmup,
        args.noise_trials,
        args.noise_seconds,
        dict(item.split("=", 1) for item in args.set),
    )


if __name__ == "__main__":
    main()
