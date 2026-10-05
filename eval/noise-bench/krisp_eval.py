"""So sánh Krisp VIVA (voice_isolation) vs không lọc, cùng phương pháp đo với bench.py
(mixing nhiễu số học + đẩy qua STTPipeline.stream() thật), khác NC/BVC cũ ở chỗ Krisp
KHÔNG cần dựng room/publish LiveKit Cloud thật — filter chạy offline sau khi DRM auth
qua JWT (xem smoke.py). Không tốn phút kết nối thật, không có nguồn méo do network jitter.

Chạy (từ venv riêng đã cài, KHÔNG phải venv dự án):
    KRISP_VENV/bin/python krisp_eval.py --profile production --conditions clean,office@8,babble@6
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.environ.get("NOISE_BENCH_SRC", str(ROOT / "src")))
sys.path.insert(0, str(ROOT / "eval" / "stt-bench"))
sys.path.insert(0, str(ROOT / "eval" / "noise-bench"))

import bench  # noqa: E402
from dotenv import dotenv_values  # noqa: E402
from livekit import api, rtc  # noqa: E402
from livekit.plugins import krisp  # noqa: E402

from inference.asr import create_asr_gateway  # noqa: E402
from speech.asr.recognizer import SpeechRecognizer  # noqa: E402
from speech.settings import SpeechSettings  # noqa: E402

RATE = bench.RATE
KRISP_FRAME = 160  # 10ms @ 16kHz, bắt buộc theo docs krisp_internal
_ENV = dotenv_values(ROOT / ".env")


def _make_processor(mode_name: str, level: float) -> krisp.KrispVivaFilterFrameProcessor:
    api_key = _ENV["LIVEKIT_API_KEY"]
    api_secret = _ENV["LIVEKIT_API_SECRET"]
    url = _ENV["LIVEKIT_URL"]
    token = (
        api.AccessToken(api_key, api_secret)
        .with_identity("krisp-bench")
        .with_ttl(timedelta(minutes=30))
        .with_grants(api.VideoGrants(room_join=True, room="krisp-bench", can_publish=True))
        .to_jwt()
    )
    mode = getattr(krisp.viva_filter.VivaMode, mode_name)
    proc = krisp.KrispVivaFilterFrameProcessor(mode=mode, noise_suppression_level=level)
    proc._on_credentials_updated(token=token, url=url)
    proc._on_stream_info_updated(
        room_name="krisp-bench", participant_identity="krisp-bench", publication_sid="TR_krispbench"
    )
    return proc


def apply_krisp(pcm: np.ndarray, proc: krisp.KrispVivaFilterFrameProcessor) -> np.ndarray:
    """Lọc toàn bộ pcm (int16, 16kHz mono) qua Krisp, frame 10ms cố định. Phần dư cuối
    (không đủ 1 frame) giữ nguyên không lọc."""
    out = np.empty_like(pcm)
    n = len(pcm)
    i = 0
    while i + KRISP_FRAME <= n:
        chunk = pcm[i : i + KRISP_FRAME]
        frame = rtc.AudioFrame(
            data=chunk.tobytes(), sample_rate=RATE, num_channels=1, samples_per_channel=KRISP_FRAME
        )
        result = proc._process(frame)
        out[i : i + KRISP_FRAME] = np.frombuffer(result.data, dtype=np.int16)
        i += KRISP_FRAME
    if i < n:
        out[i:] = pcm[i:]
    return out


async def run_condition(
    condition: str,
    cases: list[dict],
    clean_ref: dict[str, str],
    noises: dict[str, np.ndarray],
    median_speech_rms: float,
    golden_cases: list[dict],
    settings: SpeechSettings,
    asr: SpeechRecognizer,
    proc: krisp.KrispVivaFilterFrameProcessor | None,
) -> dict:
    noise_name, _, snr = condition.partition("@")
    noise = None if noise_name == "clean" else noises[noise_name]
    snr_db = float(snr) if snr else None
    rng = np.random.default_rng(1234)
    rows = []
    for case in cases:
        pcm = bench.make_trial(case["speech"], noise, snr_db, rng)
        if proc is not None:
            pcm = apply_krisp(pcm, proc)
        out = await bench.run_pipeline(pcm, settings, asr)
        finals, turns = out["finals"], out["turns"]
        prediction = " ".join(finals)
        drift_err, drift_n = bench._wer(clean_ref[case["id"]], prediction)
        turn_drift_err, _ = bench._wer(clean_ref[case["id"]], " ".join(turns))
        row = {
            "id": case["id"],
            "drift_errors": drift_err,
            "turn_drift_errors": turn_drift_err,
            "drift_words": drift_n,
            "finals": finals,
            "turns": turns,
        }
        if case["reference"] and not bench._has_digit(case["reference"]):
            gold_err, gold_n = bench._wer(case["reference"], prediction)
            turn_err, _ = bench._wer(case["reference"], " ".join(turns))
            row.update(golden_errors=gold_err, golden_words=gold_n, turn_errors=turn_err)
        rows.append(row)

    false_finals = false_turns = 0
    noise_only_n = 0
    if noise is not None:
        noise_rms = median_speech_rms / 10 ** (snr_db / 20)
        for _ in range(bench.NOISE_ONLY_TRIALS):
            pcm = bench.make_trial(None, noise, None, rng, noise_rms_target=noise_rms)
            if proc is not None:
                pcm = apply_krisp(pcm, proc)
            out = await bench.run_pipeline(pcm, settings, asr)
            false_finals += bool(out["finals"])
            false_turns += bool(out["turns"])
            noise_only_n += 1

    gold_n = sum(r.get("golden_words", 0) for r in rows)
    drift_n = sum(r["drift_words"] for r in rows)
    return {
        "wer_golden": sum(r.get("golden_errors", 0) for r in rows) / gold_n if gold_n else None,
        "wer_turn": sum(r.get("turn_errors", 0) for r in rows) / gold_n if gold_n else None,
        "wer_drift": sum(r["drift_errors"] for r in rows) / drift_n if drift_n else None,
        "trials": len(rows),
        "no_turn": sum(1 for r in rows if not r["turns"]),
        "dropped_turns": sum(1 for r in rows if r["finals"] and not r["turns"]),
        "false_finals": false_finals if noise is not None else None,
        "false_turns": false_turns if noise is not None else None,
        "noise_only_trials": noise_only_n,
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="production", choices=list(bench.PROFILES))
    ap.add_argument("--conditions", default="clean,office@8,babble@6")
    ap.add_argument("--mode", default="VOICE_ISOLATION")
    ap.add_argument("--level", type=float, default=90.0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    overrides = dict(bench.PROFILES[args.profile])
    settings = SpeechSettings(**overrides)
    asr = SpeechRecognizer(create_asr_gateway(settings.asr_provider))

    golden_cases = bench.load_golden()
    cases = bench.build_web_set(asr, settings.silero_vad_model_path)
    clean_ref = {}
    from speech.types import AudioSegment

    for case in cases:
        segment = AudioSegment(pcm=case["speech"].astype(np.int16).tobytes(), sample_rate=RATE)
        clean_ref[case["id"]] = asr.transcribe(segment).text

    noises = {
        "office": bench.build_office_noise(settings.silero_vad_model_path),
        "babble": bench.build_babble([c["speech"] for c in golden_cases]),
    }
    median_speech_rms = float(np.median([bench._active_rms(c["speech"]) for c in cases]))

    conditions = args.conditions.split(",")
    results: dict = {
        "profile": args.profile,
        "mode": args.mode,
        "level": args.level,
        "conditions": {},
    }

    for variant_name, proc in [
        ("plain", None),
        ("krisp", _make_processor(args.mode, args.level)),
    ]:
        results["conditions"].setdefault(variant_name, {})
        for condition in conditions:
            summary = await run_condition(
                condition,
                cases,
                clean_ref,
                noises,
                median_speech_rms,
                golden_cases,
                settings,
                asr,
                proc,
            )
            results["conditions"][variant_name][condition] = summary
            shown = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in summary.items()}
            print(f"[{variant_name}] {condition}: {shown}")

    out_path = (
        Path(args.out) if args.out else ROOT / "temp" / "noise-bench" / "krisp_eval_result.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print("Saved:", out_path)


if __name__ == "__main__":
    asyncio.run(main())
