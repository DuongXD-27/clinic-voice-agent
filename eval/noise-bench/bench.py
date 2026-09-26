"""Đo độ chính xác pipeline streaming LiveKit (VAD -> Admission -> ASR -> Turn) dưới nhiễu.

Khác `eval/stt-bench` (gọi `transcribe()` batch trên audio sạch): mỗi câu được đặt giữa đoạn
đệm trước/sau, trộn nhiễu ở SNR xác định, rồi đẩy TỪNG FRAME 30 ms qua đúng
`STTPipeline.stream()` mà worker LiveKit dùng (Silero VAD, Admission, ZipFormer chunked-offline,
TurnController + Validator). Đo cả text ASR final lẫn turn thực sự gửi lên core.

Bộ dữ liệu (`--dataset`):
- `web` (mặc định): câu thật của người thử nghiệm, 16 kHz đầy đủ dải, cắt từ dump
  `temp/audio/livekit_debug_web-*.wav` của cuộc gọi yên tĩnh. Không có nhãn — tham chiếu là
  chính model decode đoạn sạch đó.
- `golden`: 40 câu có nhãn của `eval/stt-bench` (8 kHz điện thoại, nâng lên 16 kHz).

Nguồn nhiễu:
- `office`: đoạn không có giọng nói (theo Silero) cắt tự động từ các bản dump — nhiễu thật
  qua mic + trình duyệt + LiveKit.
- `babble`: 3 luồng giọng người khác (bộ golden) cộng lại — người nói xung quanh.

Chỉ số chính:
- `wer_turn_drift`/`wer_turn`: WER của turn gửi lên core so với decode sạch / so với nhãn.
- `wer_drift`/`wer_golden`: như trên nhưng ở mức ASR final. `wer_golden` chỉ tính câu không
  có chữ số (nhãn "14" vs model "mười bốn" sai lệch có hệ thống).
- `dropped_turns`: ASR có chữ nhưng không thành turn. `false_turns`: trial chỉ có nhiễu mà
  vẫn thành turn.

Chạy (từ gốc repo; dữ liệu và kết quả nằm trong temp/noise-bench/, không commit):
    PYTHONPATH=src .venv/bin/python eval/noise-bench/bench.py --label moi
    PYTHONPATH=src .venv/bin/python eval/noise-bench/bench.py --label moi --dataset golden
    PYTHONPATH=src .venv/bin/python eval/noise-bench/bench.py --label x --set speech_admission_enabled=false
    PYTHONPATH=src .venv/bin/python eval/noise-bench/bench.py --compare cu moi
So với code cũ: tạo git worktree của commit cũ rồi chạy với NOISE_BENCH_SRC=<worktree>/src.
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import json
import os
import re
import sys
import time
import wave
from pathlib import Path
from typing import AsyncIterator

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[2]
# NOISE_BENCH_SRC: chạy bộ đo trên mã nguồn khác (vd. một git worktree của commit cũ) để so
# sánh A/B trên cùng dữ liệu; dữ liệu/model vẫn đọc từ repo hiện tại.
sys.path.insert(0, os.environ.get("NOISE_BENCH_SRC", str(ROOT / "src")))
sys.path.insert(0, str(ROOT / "eval" / "stt-bench"))

from evaluate import calculate_wer  # noqa: E402

from inference.asr import create_asr_gateway  # noqa: E402
from speech.asr.recognizer import SpeechRecognizer  # noqa: E402
from speech.audio.codec import resample  # noqa: E402
from speech.bundle import build_streaming_bundle  # noqa: E402
from speech.settings import SpeechSettings  # noqa: E402
from speech.turn.controller import TurnController  # noqa: E402
from speech.types import AudioSegment  # noqa: E402

RATE = 16_000
FRAME = RATE * 30 // 1000
LEAD_S = 1.2
TAIL_S = 2.0
WORK_DIR = ROOT / "temp" / "noise-bench"
GOLDEN = ROOT / "eval" / "stt-bench" / "golden-cases.yaml"
DEFAULT_CONDITIONS = "clean,office@15,office@8,office@3,babble@12,babble@6"
NOISE_ONLY_TRIALS = 12


def _read_wav(path: Path | str) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
        pcm = w.readframes(w.getnframes())
        channels = w.getnchannels()
    samples = np.frombuffer(pcm, dtype=np.int16)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1).astype(np.int16)
    return samples, rate


def _write_wav(path: Path, samples: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(samples.astype(np.int16).tobytes())


def _to_16k(samples: np.ndarray, rate: int) -> np.ndarray:
    if rate == RATE:
        return samples.astype(np.float32)
    pcm = resample(samples.astype(np.int16).tobytes(), rate, RATE)
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32)


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if x.size else 0.0


def _active_rms(x: np.ndarray) -> float:
    """RMS chỉ trên các frame có giọng (trong vòng 30 dB so với frame to nhất)."""
    frames = [x[i : i + FRAME] for i in range(0, len(x) - FRAME + 1, FRAME)]
    levels = np.array([_rms(f) for f in frames])
    if not levels.size or levels.max() == 0:
        return 0.0
    active = levels[levels >= levels.max() * 10 ** (-30 / 20)]
    return float(np.sqrt(np.mean(active**2)))


def build_office_noise(model_path: str, max_seconds: float = 180.0) -> np.ndarray:
    """Cắt đoạn không có giọng nói (Silero) >= 1.5 s, bỏ 300 ms mỗi biên để tránh dính đầu/đuôi
    câu, chỉ giữ đoạn có nhiễu nghe được (RMS >= 10, tức >= 20 dB) — đoạn gần như im lặng số
    (trình duyệt đã khử nhiễu) không mang thông tin gì để đo."""
    cache = WORK_DIR / "office_noise.wav"
    if cache.exists():
        samples, _ = _read_wav(cache)
        return samples.astype(np.float32)

    from speech.asr.vad.silero import SileroVadClassifier

    pieces: list[np.ndarray] = []
    total = 0
    paths = sorted(glob.glob(str(ROOT / "temp" / "audio" / "livekit_debug_web-*.wav")))
    for path in paths:
        if os.path.getsize(path) < 200_000:
            continue
        samples, rate = _read_wav(path)
        if rate != RATE:
            continue
        vad = SileroVadClassifier(model_path, sample_rate=RATE)
        flags = [
            vad.is_speech(samples[i : i + FRAME].tobytes())
            for i in range(0, len(samples) - FRAME + 1, FRAME)
        ]
        run_start = None
        per_file = 0
        for idx, is_speech in enumerate([*flags, True]):
            if not is_speech and run_start is None:
                run_start = idx
            elif is_speech and run_start is not None:
                start, end = (run_start + 10) * FRAME, (idx - 10) * FRAME
                run_start = None
                if end - start < int(1.5 * RATE):
                    continue
                segment = samples[start:end].astype(np.float32)
                if _rms(segment) < 10 or per_file > 20 * RATE:
                    continue
                pieces.append(segment)
                per_file += len(segment)
                total += len(segment)
        if total >= max_seconds * RATE:
            break
    if not pieces:
        raise RuntimeError("Không tìm được đoạn nhiễu nào trong temp/audio/livekit_debug_web-*.wav")
    noise = np.concatenate(pieces)
    _write_wav(cache, noise)
    return noise


def build_babble(speech_clips: list[np.ndarray], seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    streams = []
    for _ in range(3):
        order = rng.permutation(len(speech_clips))
        stream = np.concatenate(
            [speech_clips[i] / max(_active_rms(speech_clips[i]), 1.0) for i in order]
        )
        streams.append(stream)
    length = min(len(s) for s in streams)
    babble = sum(s[:length] for s in streams)
    return babble * (1000.0 / _rms(babble))


def make_trial(
    speech: np.ndarray | None,
    noise: np.ndarray | None,
    snr_db: float | None,
    rng: np.random.Generator,
    *,
    noise_rms_target: float | None = None,
) -> np.ndarray:
    speech_len = 0 if speech is None else len(speech)
    total = int(LEAD_S * RATE) + speech_len + int(TAIL_S * RATE)
    mix = np.zeros(total, dtype=np.float64)
    if speech is not None:
        lead = int(LEAD_S * RATE)
        mix[lead : lead + speech_len] = speech
    if noise is None:
        mix += rng.normal(0.0, 1.0, total)  # dither nhẹ, tương đương "im lặng" sau khử nhiễu
    else:
        start = int(rng.integers(0, len(noise) - total))
        segment = noise[start : start + total].astype(np.float64)
        if noise_rms_target is not None:
            gain = noise_rms_target / max(_rms(segment), 1e-6)
        else:
            gain = _active_rms(speech) / (max(_rms(segment), 1e-6) * 10 ** (snr_db / 20))
        mix += gain * segment
    return np.clip(np.round(mix), -32768, 32767).astype(np.int16)


class _CapturingRecognizer:
    """Bọc recognizer thật, ghi lại mọi TranscriptEvent final mà ASR phát ra."""

    def __init__(self, inner: SpeechRecognizer) -> None:
        self._inner = inner
        self.name = inner.name
        self.input_sample_rate = inner.input_sample_rate
        self.finals: list[str] = []

    def transcribe(self, segment):
        return self._inner.transcribe(segment)

    async def stream(self, frames: AsyncIterator[bytes], **kwargs):
        async for event in self._inner.stream(frames, **kwargs):
            if event.is_final:
                self.finals.append(event.text)
            yield event


async def run_pipeline(
    pcm: np.ndarray, settings: SpeechSettings, asr: SpeechRecognizer
) -> tuple[list[str], list[str]]:
    """Trả (ASR finals, turn mà TurnController chốt gửi lên core).

    TurnController đo thời lượng bằng đồng hồ ảo tăng 30 ms mỗi frame, nên ngưỡng
    min_speech_ms/post_bot_guard giữ đúng ý nghĩa dù frame được đẩy nhanh hơn thời gian
    thực. Timeout sau speech_end dùng asyncio.sleep thật — cuối luồng chờ thêm để nó kịp chạy.
    """
    recognizer = _CapturingRecognizer(asr)
    bundle = build_streaming_bundle(settings, asr=recognizer, frame_ms=30)
    virtual_now = [0.0]
    controller = TurnController(
        min_speech_ms=settings.turn_min_speech_ms,
        max_wait_after_vad_end_ms=settings.turn_max_wait_after_vad_end_ms,
        post_bot_guard_ms=settings.turn_post_bot_guard_ms,
        validator=bundle.validator,
        clock=lambda: virtual_now[0],
    )

    async def frames() -> AsyncIterator[bytes]:
        for i in range(0, len(pcm) - FRAME + 1, FRAME):
            virtual_now[0] += FRAME / RATE
            yield pcm[i : i + FRAME].tobytes()
            # Như live (frame cách nhau 30 ms): cho task VAD kịp xử lý frame vừa gửi.
            for _ in range(3):
                await asyncio.sleep(0)
        await asyncio.sleep(settings.turn_max_wait_after_vad_end_ms / 1000 + 0.2)

    turns = []
    async for turn in bundle.stt_pipeline.stream(
        frames(),
        turn_controller=controller,
        evidence_tracker=bundle.evidence_tracker,
        noise_tracker=bundle.noise_tracker,
        noise_classifier=bundle.noise_classifier,
    ):
        turns.append(turn.text)
    return recognizer.finals, turns


def _has_digit(text: str) -> bool:
    return bool(re.search(r"\d", text))


def _wer(reference: str, prediction: str) -> tuple[int, int]:
    metrics = calculate_wer(reference, prediction)
    errors = metrics.substitutions + metrics.deletions + metrics.insertions
    return errors, metrics.reference_word_count


# Câu theo kịch bản thử nghiệm (tên, ngày sinh, xác nhận) — phân biệt với tiếng người khác
# hoặc câu nói ngoài lề cũng lọt vào mic trong cùng cuộc gọi.
_SCRIPT_RE = re.compile(
    r"^(TÔI (LÀ|TÊN|SINH|KHÔNG ĐẾN|ĐỒNG Ý)|(SINH )?NGÀY|MƯỜI BỐN|NGUYỄN VĂN A$|A LÔ|ĐÚNG|CÓ TÔI|KHÔNG ĐƯỢC$)"
)


def build_web_set(asr: SpeechRecognizer, model_path: str) -> list[dict]:
    """Câu thật của người thử nghiệm, đầy đủ dải 16 kHz, cắt từ dump LiveKit của các cuộc gọi
    yên tĩnh (nhiễu nền < 10 dB). Tham chiếu = chính model decode đoạn sạch đó."""
    cache = WORK_DIR / "web_set.json"
    if not cache.exists():
        from speech.asr.vad.silero import SileroVadClassifier

        found = []
        for path in sorted(glob.glob(str(ROOT / "temp" / "audio" / "livekit_debug_web-*.wav"))):
            if os.path.getsize(path) < 200_000:
                continue
            samples, rate = _read_wav(path)
            if rate != RATE:
                continue
            vad = SileroVadClassifier(model_path, sample_rate=RATE)
            flags = [
                vad.is_speech(samples[i : i + FRAME].tobytes())
                for i in range(0, len(samples) - FRAME + 1, FRAME)
            ]
            quiet = [
                _rms(samples[i * FRAME : (i + 1) * FRAME]) for i, f in enumerate(flags) if not f
            ]
            if not quiet or 20 * np.log10(np.median(quiet) + 1e-6) > 10:
                continue
            i = 0
            while i < len(flags):
                if not flags[i]:
                    i += 1
                    continue
                j = i
                while j < len(flags) and flags[j]:
                    j += 1
                # lùi 450 ms: Silero nhận speech trễ, không cắt mất âm đầu
                start, end = max(0, (i - 15) * FRAME), min(len(samples), (j + 5) * FRAME)
                if 0.8 <= (end - start) / RATE <= 8:
                    pcm = samples[start:end].astype(np.int16).tobytes()
                    text = asr.transcribe(AudioSegment(pcm=pcm, sample_rate=RATE)).text
                    if _SCRIPT_RE.match(text):
                        found.append({"file": os.path.basename(path), "start": start, "end": end})
                i = j
        cache.write_text(json.dumps(found, indent=1), encoding="utf-8")
    cases = []
    loaded: dict[str, np.ndarray] = {}
    for idx, item in enumerate(json.loads(cache.read_text(encoding="utf-8"))):
        if item["file"] not in loaded:
            loaded[item["file"]] = _read_wav(ROOT / "temp" / "audio" / item["file"])[0]
        speech = loaded[item["file"]][item["start"] : item["end"]].astype(np.float32)
        cases.append({"id": f"WEB_{idx:02d}", "reference": None, "speech": speech})
    return cases


def load_golden() -> list[dict]:
    golden = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))
    cases = []
    for case in golden["cases"]:
        if not case.get("should_produce_text", True):
            continue
        samples, rate = _read_wav(GOLDEN.parent / case["audio"])
        cases.append(
            {"id": case["id"], "reference": case["reference"], "speech": _to_16k(samples, rate)}
        )
    return cases


def run(label: str, dataset: str, conditions: list[str], repeats: int, overrides: dict) -> dict:
    overrides = {"sample_rate": RATE, "vad_provider": "silero", **overrides}
    settings = SpeechSettings(**overrides)
    asr = SpeechRecognizer(create_asr_gateway(settings.asr_provider))

    golden_cases = load_golden()
    cases = (
        golden_cases if dataset == "golden" else build_web_set(asr, settings.silero_vad_model_path)
    )
    clean_ref: dict[str, str] = {}
    for case in cases:
        segment = AudioSegment(pcm=case["speech"].astype(np.int16).tobytes(), sample_rate=RATE)
        clean_ref[case["id"]] = asr.transcribe(segment).text

    noises = {
        "office": build_office_noise(settings.silero_vad_model_path),
        # Giọng nền lấy từ bộ nhãn (người khác, không phải người thử nghiệm của bộ web).
        "babble": build_babble([c["speech"] for c in golden_cases]),
    }
    median_speech_rms = float(np.median([_active_rms(c["speech"]) for c in cases]))

    results: dict = {
        "label": label,
        "dataset": dataset,
        "repeats": repeats,
        "settings": {k: getattr(settings, k) for k in sorted(overrides)}
        | {
            "speech_admission_enabled": settings.speech_admission_enabled,
            "turn_validator_enabled": settings.turn_validator_enabled,
        },
        "conditions": {},
    }
    for condition in conditions:
        noise_name, _, snr = condition.partition("@")
        noise = None if noise_name == "clean" else noises[noise_name]
        snr_db = float(snr) if snr else None
        rng = np.random.default_rng(1234)
        started = time.monotonic()
        rows = []
        for repeat in range(repeats if noise is not None else 1):
            for case in cases:
                pcm = make_trial(case["speech"], noise, snr_db, rng)
                finals, turns = asyncio.run(run_pipeline(pcm, settings, asr))
                prediction = " ".join(finals)
                drift_err, drift_n = _wer(clean_ref[case["id"]], prediction)
                turn_drift_err, _ = _wer(clean_ref[case["id"]], " ".join(turns))
                row = {
                    "id": case["id"],
                    "repeat": repeat,
                    "reference": case["reference"],
                    "clean_batch": clean_ref[case["id"]],
                    "finals": finals,
                    "turns": turns,
                    "drift_errors": drift_err,
                    "turn_drift_errors": turn_drift_err,
                    "drift_words": drift_n,
                }
                if case["reference"] and not _has_digit(case["reference"]):
                    gold_err, gold_n = _wer(case["reference"], prediction)
                    turn_err, _ = _wer(case["reference"], " ".join(turns))
                    row.update(golden_errors=gold_err, golden_words=gold_n, turn_errors=turn_err)
                rows.append(row)

        false_finals = false_turns = 0
        noise_only_rows = []
        if noise is not None:
            noise_rms = median_speech_rms / 10 ** (snr_db / 20)
            for _ in range(NOISE_ONLY_TRIALS):
                pcm = make_trial(None, noise, None, rng, noise_rms_target=noise_rms)
                finals, turns = asyncio.run(run_pipeline(pcm, settings, asr))
                noise_only_rows.append({"finals": finals, "turns": turns})
                false_finals += bool(finals)
                false_turns += bool(turns)

        gold_n = sum(r.get("golden_words", 0) for r in rows)
        drift_n = sum(r["drift_words"] for r in rows)
        summary = {
            "wer_golden": sum(r.get("golden_errors", 0) for r in rows) / gold_n if gold_n else None,
            "wer_turn": sum(r.get("turn_errors", 0) for r in rows) / gold_n if gold_n else None,
            "wer_drift": sum(r["drift_errors"] for r in rows) / drift_n if drift_n else None,
            "wer_turn_drift": sum(r["turn_drift_errors"] for r in rows) / drift_n
            if drift_n
            else None,
            "trials": len(rows),
            "empty_output": sum(1 for r in rows if not r["finals"]),
            "dropped_turns": sum(1 for r in rows if r["finals"] and not r["turns"]),
            "false_finals": false_finals if noise is not None else None,
            "false_turns": false_turns if noise is not None else None,
            "noise_only_trials": len(noise_only_rows),
            "seconds": round(time.monotonic() - started, 1),
        }
        results["conditions"][condition] = {
            "summary": summary,
            "cases": rows,
            "noise_only": noise_only_rows,
        }
        shown = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in summary.items()}
        print(f"[{label}] {condition:11} {shown}", flush=True)

    out = WORK_DIR / "results" / f"{label}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"-> {out.relative_to(ROOT)}")
    return results


_METRICS = (
    ("wer_golden", "WER ASR so với nhãn (câu không chữ số)"),
    ("wer_turn", "WER của turn gửi lên core, so với nhãn"),
    ("wer_drift", "WER ASR lệch so với decode audio sạch"),
    ("wer_turn_drift", "WER của turn gửi lên core, so với decode audio sạch"),
    ("dropped_turns", "câu ASR có chữ nhưng không thành turn"),
    ("false_finals", "trial chỉ có nhiễu mà ASR vẫn ra chữ"),
    ("false_turns", "trial chỉ có nhiễu mà vẫn thành turn"),
)


def compare(labels: list[str]) -> None:
    loaded = [json.loads((WORK_DIR / "results" / f"{label}.json").read_text()) for label in labels]
    conditions = list(loaded[0]["conditions"])
    for key, title in _METRICS:
        print(f"\n## {title} ({key})")
        print(f"{'điều kiện':11} " + " ".join(f"{label[:18]:>18}" for label in labels))
        for condition in conditions:
            cells = []
            for result in loaded:
                s = result["conditions"].get(condition, {}).get("summary") or {}
                value = s.get(key)
                if value is None:
                    cells.append(f"{'-':>18}")
                elif isinstance(value, float):
                    cells.append(f"{value:18.3f}")
                else:
                    cells.append(f"{value:>18}")
            print(f"{condition:11} " + " ".join(cells))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label")
    parser.add_argument("--dataset", choices=("web", "golden"), default="web")
    parser.add_argument("--conditions", default=DEFAULT_CONDITIONS)
    parser.add_argument(
        "--repeats", type=int, default=2, help="số đoạn nhiễu khác nhau cho mỗi câu"
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KHOÁ=GIÁ_TRỊ",
        help="ghi đè SpeechSettings, vd. --set speech_foreground_gate_enabled=true",
    )
    parser.add_argument("--compare", nargs="+")
    args = parser.parse_args()
    if args.compare:
        compare(args.compare)
        return
    if not args.label:
        parser.error("--label hoặc --compare là bắt buộc")
    overrides = dict(item.split("=", 1) for item in args.set)
    run(args.label, args.dataset, args.conditions.split(","), args.repeats, overrides)


if __name__ == "__main__":
    main()
