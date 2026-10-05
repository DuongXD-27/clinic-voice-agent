"""Đánh giá cách đo SNR mà TurnValidator dùng cho luật "câu <= 2 từ và SNR < 3 dB -> DROP".

Dùng dữ liệu biết chắc thật/giả, không cần gán nhãn tay:
- THẬT: câu có nhãn (eval/stt-bench) + câu cắt từ cuộc gọi LiveKit (bộ web của bench.py),
  bản đầy đủ và bản cắt còn ~0,7 s (giống câu trả lời 1-2 từ), sạch và trộn nhiễu văn phòng.
- GIẢ: trial chỉ có nhiễu (văn phòng, giọng nền) — mọi đoạn Silero báo speech ở đây đều không
  phải người gọi, chữ ASR ra từ đó là ảo giác.

Với mỗi đoạn Silero, lấy SNR mà validator thấy ở frame speech cuối + 20 (~lúc ASR final tới).
Cách đo tốt: đoạn THẬT >= 3 dB, đoạn GIẢ < 3 dB. Deterministic: không có ASR, không có timer.

    set -a; . ./.env; set +a
    .venv/bin/python eval/noise-bench/validator_snr_eval.py
"""

from __future__ import annotations

import importlib.util
import json
from collections import deque
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("bench", HERE / "bench.py")
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)

from speech.audio.noise_tracker import NoiseTracker, UtteranceEvidenceTracker  # noqa: E402
from speech.bundle import _build_silero  # noqa: E402

FRAME = bench.FRAME
GAP, HOLD, READ_AT = 20, 100, 20  # 600 ms, 3 s, 600 ms — như UtteranceEvidenceTracker
ONSET = 10  # 300 ms: min_speech_duration 0,25 s của Silero (sherpa-onnx) + 1 cửa sổ
FLOOR_WINDOW, FLOOR_PCT = 100, 20  # phân vị 20 của 100 frame không-speech gần nhất (3 s)
SHORT_S = 0.7
THRESHOLD_DB = 3.0


def _db(level: float, floor: float) -> float:
    return float(20 * np.log10(max(level, 1e-6) / max(floor, 1e-6)))


class _Before:
    """Cách đo trước 26/09: nền = EMA của NoiseTracker (cập nhật mọi frame Silero gọi là
    không-speech), năng lượng câu = chỉ các frame Silero gọi là speech."""

    def __init__(self) -> None:
        self.tracker = NoiseTracker()
        self.power, self.count, self.since = 0.0, 0, HOLD + 1

    def observe(self, frame: bytes, rms: float, speech: bool) -> float:
        evidence = self.tracker.observe(frame, speech)
        if speech:
            if self.since >= GAP:
                self.power, self.count = 0.0, 0
            self.power += rms * rms
            self.count += 1
            self.since = 0
        else:
            self.since += 1
        if not self.count or self.since > HOLD:
            return evidence.snr_db
        return _db(np.sqrt(self.power / self.count), evidence.noise_floor)


class _Code:
    """Đúng code đang chạy: NoiseTracker -> UtteranceEvidenceTracker (như pipeline)."""

    def __init__(self) -> None:
        self.tracker, self.utt = NoiseTracker(), UtteranceEvidenceTracker()

    def observe(self, frame: bytes, rms: float, speech: bool) -> float:
        return self.utt.observe(self.tracker.observe(frame, speech), speech).snr_db


class _Variant:
    """`floor`: "ema_delayed" (EMA, hoãn ONSET frame) hoặc "percentile".
    `onset`: True thì ONSET frame ngay trước lúc Silero báo speech được tính vào câu."""

    def __init__(self, floor: str, onset: bool, pct: int = FLOOR_PCT) -> None:
        self.floor_kind, self.onset, self.pct = floor, onset, pct
        self.ema = 50.0
        self.history: deque[float] = deque(maxlen=FLOOR_WINDOW)
        self.pending: deque[float] = deque()
        self.power, self.count, self.since = 0.0, 0, HOLD + 1

    def floor(self) -> float:
        if self.floor_kind == "percentile":
            return float(np.percentile(self.history, self.pct)) if self.history else 50.0
        return self.ema

    def observe(self, frame: bytes, rms: float, speech: bool) -> float:
        if speech:
            if self.since >= GAP:
                onset = list(self.pending) if self.onset else []
                self.power, self.count = sum(r * r for r in onset), len(onset)
            self.pending.clear()
            self.power += rms * rms
            self.count += 1
            self.since = 0
        else:
            self.pending.append(rms)
            if len(self.pending) > ONSET:
                old = self.pending.popleft()
                self.ema = 0.05 * old + 0.95 * self.ema
                self.history.append(old)
            self.since += 1
        if not self.count or self.since > HOLD:
            return _db(rms, self.floor())
        return _db(np.sqrt(self.power / self.count), self.floor())


VARIANTS = {
    "cũ (trước 26/09)": _Before,
    "B: EMA hoãn + onset": lambda: _Variant("ema_delayed", onset=True),
    "C: phân vị": lambda: _Variant("percentile", onset=False),
    "C+B: phân vị + onset": lambda: _Variant("percentile", onset=True),
    "D: trung vị + onset": lambda: _Variant("percentile", onset=True, pct=50),
    "mới (code)": _Code,
}


def _segments(flags: list[bool]) -> list[tuple[int, int]]:
    segs, start, last = [], None, None
    for i, f in enumerate(flags):
        if f:
            if last is None or i - last >= GAP:
                if last is not None:
                    segs.append((start, last))
                start = i
            last = i
    if last is not None:
        segs.append((start, last))
    return segs


def measure(pcm: np.ndarray, classifier_factory) -> tuple[list[tuple[int, int]], dict]:
    classifier = classifier_factory()
    variants = {name: make() for name, make in VARIANTS.items()}
    flags, snrs = [], {name: [] for name in variants}
    for i in range(0, len(pcm) - FRAME + 1, FRAME):
        frame = pcm[i : i + FRAME].tobytes()
        speech = classifier.is_speech(frame)
        rms = float(np.sqrt(np.mean(pcm[i : i + FRAME].astype(np.float64) ** 2)))
        flags.append(speech)
        for name, v in variants.items():
            snrs[name].append(v.observe(frame, rms, speech))
    return _segments(flags), snrs


def _read(snrs: dict, end: int) -> dict:
    return {name: values[min(end + READ_AT, len(values) - 1)] for name, values in snrs.items()}


def _shorten(speech: np.ndarray) -> np.ndarray:
    """Giữ ~0,7 s kể từ lúc có tiếng (clip đã có 450 ms đệm trước), fade-out 30 ms."""
    rms = np.sqrt(np.convolve(speech.astype(np.float64) ** 2, np.ones(FRAME) / FRAME, "valid"))
    start = int(np.argmax(rms > max(4 * np.median(rms), 200)))
    out = speech[: start + int(SHORT_S * bench.RATE)].astype(np.float64).copy()
    fade = min(len(out), int(0.03 * bench.RATE))
    out[-fade:] *= np.linspace(1, 0, fade)
    return out.astype(np.int16)


def main() -> None:
    settings = bench.SpeechSettings(vad_provider="silero")
    asr = bench.SpeechRecognizer(bench.create_asr_gateway(settings.asr_provider))
    golden = bench.load_golden()
    web = bench.build_web_set(asr, settings.silero_vad_model_path)
    cases = [("golden", c) for c in golden] + [("web", c) for c in web]
    office = bench.build_office_noise(settings.silero_vad_model_path)
    babble = bench.build_babble([c["speech"] for c in golden])
    median_rms = float(np.median([bench._active_rms(c["speech"]) for _, c in cases]))

    def factory():
        return _build_silero(settings, bench.RATE)

    rows: list[dict] = []
    rng = np.random.default_rng(2026)
    for condition in ("clean", "office@15", "office@8", "office@3"):
        noise_name, _, snr = condition.partition("@")
        noise = office if noise_name == "office" else None
        for length in ("full", "short"):
            for dataset, case in cases:
                speech = case["speech"] if length == "full" else _shorten(case["speech"])
                pcm = bench.make_trial(speech, noise, float(snr) if snr else None, rng)
                segs, snrs = measure(pcm, factory)
                lead = int(bench.LEAD_S * bench.RATE) // FRAME
                end = lead + len(speech) // FRAME
                hit = [s for s in segs if s[0] <= end + 5 and s[1] >= lead - 5]
                row = {
                    "kind": "real",
                    "condition": condition,
                    "length": length,
                    "dataset": dataset,
                    "id": case["id"],
                    "detected": bool(hit),
                }
                if hit:
                    row["snr"] = _read(snrs, max(e for _, e in hit))
                rows.append(row)
    for condition, noise, snr in (
        ("office@15", office, 15),
        ("office@8", office, 8),
        ("office@3", office, 3),
        ("babble@12", babble, 12),
        ("babble@6", babble, 6),
    ):
        target = median_rms / 10 ** (snr / 20)
        for trial in range(40):
            pcm = bench.make_trial(None, noise, None, rng, noise_rms_target=target)
            segs, snrs = measure(pcm, factory)
            for _, e in segs:
                rows.append(
                    {"kind": "fake", "condition": condition, "trial": trial, "snr": _read(snrs, e)}
                )

    out = bench.WORK_DIR / "results" / "validator_snr_eval.json"
    out.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    report(rows)
    print(f"-> {out}")


def report(rows: list[dict]) -> None:
    names = list(VARIANTS)
    print(f"\nĐoạn THẬT bị tính < {THRESHOLD_DB:g} dB (câu <= 2 từ sẽ bị DROP) — thấp là tốt")
    print(f"{'điều kiện':12s} {'độ dài':6s} {'n':>4s}  " + "  ".join(f"{n:>20s}" for n in names))
    for condition in ("clean", "office@15", "office@8", "office@3"):
        for length in ("full", "short"):
            sel = [
                r
                for r in rows
                if r["kind"] == "real"
                and r["condition"] == condition
                and r["length"] == length
                and r["detected"]
            ]
            cells = [
                f"{sum(r['snr'][n] < THRESHOLD_DB for r in sel):>4d} "
                f"({np.median([r['snr'][n] for r in sel]):5.1f} dB)"
                for n in names
            ]
            print(
                f"{condition:12s} {length:6s} {len(sel):>4d}  "
                + "  ".join(f"{c:>20s}" for c in cells)
            )
    print(
        f"\nĐoạn GIẢ (chỉ có nhiễu) bị tính >= {THRESHOLD_DB:g} dB (ảo giác <= 2 từ LỌT) — thấp là tốt"
    )
    print(f"{'điều kiện':12s} {'n':>4s}  " + "  ".join(f"{n:>20s}" for n in names))
    for condition in ("office@15", "office@8", "office@3", "babble@12", "babble@6"):
        sel = [r for r in rows if r["kind"] == "fake" and r["condition"] == condition]
        if not sel:
            print(f"{condition:12s} {0:>4d}")
            continue
        cells = [
            f"{sum(r['snr'][n] >= THRESHOLD_DB for r in sel):>4d} "
            f"({np.median([r['snr'][n] for r in sel]):5.1f} dB)"
            for n in names
        ]
        print(f"{condition:12s} {len(sel):>4d}  " + "  ".join(f"{c:>20s}" for c in cells))


if __name__ == "__main__":
    main()
