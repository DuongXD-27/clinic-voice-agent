"""Đo pipeline LiveKit khi ồn CHỈ trên câu có nhãn người — không dùng chữ ASR làm nhãn.

Bộ `web` của bench.py lấy chữ decode bản sạch làm tham chiếu: nó không thấy được lỗi mà cả hai
lần decode đều mắc, ví dụ chữ đầu câu bị VAD cắt mất. Ở đây:
- câu: golden STT (bỏ câu rỗng và câu có chữ số trong nhãn, vì không biết người đọc nói "một
  nghìn chín trăm bảy mươi tám" hay "một chín bảy tám") + câu sạch 16 kHz của bộ PM Hà Nội;
- mỗi câu đặt giữa 1,2 s nhiễu trước và 2 s nhiễu sau, trộn nhiễu thật ở SNR định trước:
  `office` (đoạn không có giọng cắt từ dump cuộc gọi LiveKit, như bench.py), `tv` và `street`
  (temp/PM_Public_Eval_STT/noise/);
- thêm 30 đoạn 6 s chỉ có nhiễu cho mỗi loại để đếm lượt giả.

Chỉ số:
- `wer`: WER các lượt gửi lên core so với nhãn (chữ hoa, bỏ dấu câu, thống nhất kiểu đặt dấu
  thanh "HOÀ"/"HÒA");
- `meaning`: số câu có ít nhất một lỗi chạm từ quyết định nghĩa — phủ định, ý định (có/vâng/
  hủy/đổi/xác nhận/khám/lịch…), số/giờ/ngày;
- `lost`: câu không thành lượt nào;
- `false_turns`: đoạn chỉ có nhiễu mà vẫn ra lượt;
- `--oracle`: thêm WER khi model decode đúng đoạn có câu (±0,3 s) — phần chênh là lỗi do
  pipeline (VAD, cắt câu, chốt lượt), sửa được mà không cần model tốt hơn.

Chạy từ gốc repo có `.env` như bench.py (bundle dựng cả TTS), cần temp/PM_Public_Eval_STT và
các dump cho nhiễu văn phòng:
    python3 eval/noise-bench/labeled_eval.py --label base
    python3 eval/noise-bench/labeled_eval.py --label thr --set asr_pre_speech_ms=300
    python3 eval/noise-bench/labeled_eval.py --compare base thr
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
import unicodedata
from multiprocessing import get_context
from pathlib import Path
from typing import Optional

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench  # noqa: E402  (đưa src/ vào sys.path; helper trộn nhiễu, pipeline)

ROOT = bench.ROOT
RATE = bench.RATE
PM_DIR = ROOT / "temp" / "PM_Public_Eval_STT"
OUT_DIR = bench.WORK_DIR / "labeled"
LEAD_S, TAIL_S, ORACLE_PAD_S = 1.2, 2.0, 0.3
NOISE_ONLY_S, NOISE_ONLY_PER_KIND = 6.0, 30
DEFAULT_CONDITIONS = "clean,office@10,office@5,street@10,street@5,tv@10"

NEGATION = {"KHÔNG", "CHƯA", "ĐỪNG", "CHẲNG"}
INTENT = {
    "CÓ",
    "ĐƯỢC",
    "VÂNG",
    "ĐỒNG",
    "Ý",
    "HỦY",
    "ĐỔI",
    "DỜI",
    "XÁC",
    "NHẬN",
    "ĐẶT",
    "GIỮ",
    "KHÁM",
    "LỊCH",
    "ĐẾN",
    "KHOAN",
    "SAI",
    "ĐÚNG",
}
NUMBER = {
    "MỘT",
    "HAI",
    "BA",
    "BỐN",
    "NĂM",
    "SÁU",
    "BẢY",
    "TÁM",
    "CHÍN",
    "MƯỜI",
    "MƯƠI",
    "MỐT",
    "LĂM",
    "TƯ",
    "TRĂM",
    "NGHÌN",
    "LINH",
    "LẺ",
    "GIỜ",
    "RƯỠI",
    "SÁNG",
    "CHIỀU",
    "TỐI",
    "NGÀY",
    "THÁNG",
    "MAI",
    "THỨ",
}
CRITICAL = NEGATION | INTENT | NUMBER
_TONES = "̣̀́̃̉"


def normalize(text: str) -> list[str]:
    """Chữ hoa, bỏ dấu câu; vần mở OA/OE/UY đặt dấu thanh ở nguyên âm đầu như GipFormer
    ("HÒA", "THÙY") để nhãn kiểu cũ ("hoà", "thuỳ") không thành lỗi giả."""
    upper = unicodedata.normalize("NFC", text).upper()
    upper = "".join(" " if unicodedata.category(c).startswith("P") else c for c in upper)
    words = []
    for syllable in upper.split():
        groups: list[list[str]] = []
        for char in unicodedata.normalize("NFD", syllable):
            if unicodedata.combining(char) and groups:
                groups[-1].append(char)
            else:
                groups.append([char])
        base = "".join(g[0] for g in groups)
        tone = [c for g in groups for c in g if c in _TONES]
        if tone and re.search(r"(OA|OE|UY)$", base) and not base.startswith("QU"):
            groups = [[c for c in g if c not in _TONES] for g in groups]
            groups[-2].append(tone[0])
            syllable = unicodedata.normalize("NFC", "".join("".join(g) for g in groups))
        words.append(syllable)
    return words


def score(reference: str, prediction: str) -> dict:
    """Levenshtein theo từ có truy ngược: tổng lỗi và số lỗi chạm từ quyết định nghĩa."""
    ref, hyp = normalize(reference), normalize(prediction)
    d = np.zeros((len(ref) + 1, len(hyp) + 1), dtype=np.int32)
    d[:, 0] = np.arange(len(ref) + 1)
    d[0, :] = np.arange(len(hyp) + 1)
    for i in range(1, len(ref) + 1):
        for j in range(1, len(hyp) + 1):
            d[i, j] = min(
                d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + (ref[i - 1] != hyp[j - 1])
            )
    i, j, critical = len(ref), len(hyp), 0
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i, j] == d[i - 1, j - 1] + (ref[i - 1] != hyp[j - 1]):
            if ref[i - 1] != hyp[j - 1] and (ref[i - 1] in CRITICAL or hyp[j - 1] in CRITICAL):
                critical += 1
            i, j = i - 1, j - 1
        elif i > 0 and d[i, j] == d[i - 1, j] + 1:
            critical += ref[i - 1] in CRITICAL
            i -= 1
        else:
            critical += hyp[j - 1] in CRITICAL
            j -= 1
    return {"errors": int(d[-1, -1]), "words": len(ref), "critical": critical}


def load_sentences() -> list[dict]:
    golden = yaml.safe_load(bench.GOLDEN.read_text(encoding="utf-8"))
    sentences = []
    for case in golden["cases"]:
        reference = case.get("reference") or ""
        if not reference.strip() or re.search(r"\d", reference):
            continue
        samples, rate = bench._read_wav(bench.GOLDEN.parent / case["audio"])
        sentences.append(
            {"id": case["id"], "reference": reference, "speech": bench._to_16k(samples, rate)}
        )
    with open(PM_DIR / "manifest.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["dieu_kien"] != "sach" or not row["cau_chuan"].strip().strip("[]"):
                continue
            if row["cau_chuan"].startswith("["):
                continue  # mô tả, không phải lời (vd. B-SIL-01)
            path = PM_DIR / "01_audio_goc" / "Ha_Noi" / "S01" / row["file"]
            samples, rate = bench._read_wav(path)
            sentences.append(
                {
                    "id": f"pm:{row['file'][:-4]}",
                    "reference": row["cau_chuan"],
                    "speech": bench._to_16k(samples, rate),
                }
            )
    return sentences


def load_noises(silero_model_path: str) -> dict[str, np.ndarray]:
    noises = {"office": bench.build_office_noise(silero_model_path)}
    for label, name in (("tv", "tv.wav"), ("street", "duong.wav")):
        samples, rate = bench._read_wav(PM_DIR / "noise" / name)
        noises[label] = bench._to_16k(samples, rate)
    return noises


def build_trials(conditions: list[str], silero_model_path: str) -> list[dict]:
    sentences = load_sentences()
    noises = load_noises(silero_model_path)
    rng = np.random.default_rng(99)
    lead, tail = int(LEAD_S * RATE), int(TAIL_S * RATE)
    trials = []
    for sentence in sentences:
        speech = sentence["speech"].astype(np.float64)
        level = bench._active_rms(speech)
        total = lead + len(speech) + tail
        for condition in conditions:
            mix = np.zeros(total)
            mix[lead : lead + len(speech)] = speech
            if condition == "clean":
                mix += rng.normal(0.0, 1.0, total)
            else:
                label, _, snr = condition.partition("@")
                noise = noises[label]
                start = int(rng.integers(0, len(noise) - total))
                segment = noise[start : start + total].astype(np.float64)
                mix += segment * (
                    level / (max(bench._rms(segment), 1e-6) * 10 ** (float(snr) / 20))
                )
            trials.append(
                {
                    "id": f"{sentence['id']}~{condition}",
                    "condition": condition,
                    "reference": sentence["reference"],
                    "span": (lead, lead + len(speech)),
                    "pcm": np.clip(np.round(mix), -32768, 32767).astype(np.int16),
                }
            )
    length = int(NOISE_ONLY_S * RATE)
    for label, noise in noises.items():
        for k in range(NOISE_ONLY_PER_KIND):
            start = int(rng.integers(0, len(noise) - length))
            segment = noise[start : start + length].astype(np.float64)
            segment *= 1500.0 / max(bench._rms(segment), 1e-6)
            trials.append(
                {
                    "id": f"{label}-only-{k:02d}",
                    "condition": f"{label}-only",
                    "reference": None,
                    "span": None,
                    "pcm": np.clip(np.round(segment), -32768, 32767).astype(np.int16),
                }
            )
    return trials


_TRIALS: list[dict] = []
_CONTEXT = None


def _setup(overrides: dict):
    from inference.asr import create_asr_gateway
    from speech.asr.recognizer import SpeechRecognizer
    from speech.settings import SpeechSettings

    settings = SpeechSettings(**{**bench.PROFILES["production"], **overrides})
    return settings, SpeechRecognizer(create_asr_gateway(settings.asr_provider))


def _work(args: tuple[dict, bool, list[int]]) -> list[dict]:
    global _CONTEXT
    overrides, oracle, indices = args
    if _CONTEXT is None:
        _CONTEXT = _setup(overrides)
    settings, asr = _CONTEXT
    from speech.types import AudioSegment

    rows = []
    pad = int(ORACLE_PAD_S * RATE)
    for index in indices:
        trial = _TRIALS[index]
        out = asyncio.run(bench.run_pipeline(trial["pcm"], settings, asr))
        row = {"id": trial["id"], "turns": out["turns"], "finals": out["finals"]}
        if oracle and trial["span"] is not None:
            a, b = trial["span"]
            segment = AudioSegment(pcm=trial["pcm"][a - pad : b + pad].tobytes(), sample_rate=RATE)
            row["oracle"] = asr.transcribe(segment).text
        rows.append(row)
    return rows


def run(label: str, conditions: list[str], overrides: dict, oracle: bool, workers: int) -> dict:
    global _TRIALS
    from speech.settings import SpeechSettings

    settings = SpeechSettings(**{**bench.PROFILES["production"], **overrides})
    _TRIALS = build_trials(conditions, settings.silero_vad_model_path)
    indices = list(range(len(_TRIALS)))
    chunks = [(overrides, oracle, indices[k::workers]) for k in range(workers)]
    with get_context("fork").Pool(workers) as pool:
        rows = {r["id"]: r for part in pool.map(_work, chunks) for r in part}
    summary = summarize(_TRIALS, rows, conditions, oracle)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{label}.json"
    out.write_text(
        json.dumps(
            {
                "label": label,
                "overrides": overrides,
                "summary": summary,
                "rows": list(rows.values()),
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print_summary(label, summary)
    print(f"-> {out.relative_to(ROOT)}")
    return summary


def summarize(trials: list[dict], rows: dict, conditions: list[str], oracle: bool) -> dict:
    summary: dict = {}
    for condition in conditions:
        picked = [t for t in trials if t["condition"] == condition]
        errors = words = meaning = lost = 0
        oracle_errors = oracle_meaning = 0
        for trial in picked:
            row = rows[trial["id"]]
            s = score(trial["reference"], " ".join(row["turns"]))
            errors += s["errors"]
            words += s["words"]
            meaning += s["critical"] > 0
            lost += not row["turns"]
            if oracle and "oracle" in row:
                so = score(trial["reference"], row["oracle"])
                oracle_errors += so["errors"]
                oracle_meaning += so["critical"] > 0
        entry = {
            "sentences": len(picked),
            "wer": round(errors / max(words, 1), 4),
            "meaning": meaning,
            "lost": lost,
        }
        if oracle:
            entry["oracle_wer"] = round(oracle_errors / max(words, 1), 4)
            entry["oracle_meaning"] = oracle_meaning
        summary[condition] = entry
    for kind in sorted({t["condition"] for t in trials if t["span"] is None}):
        picked = [t for t in trials if t["condition"] == kind]
        summary[kind] = {
            "clips": len(picked),
            "false_turns": sum(bool(rows[t["id"]]["turns"]) for t in picked),
        }
    return summary


def print_summary(label: str, summary: dict) -> None:
    for condition, entry in summary.items():
        print(f"[{label}] {condition:11} {entry}", flush=True)


def compare(labels: list[str]) -> None:
    loaded = [
        json.loads((OUT_DIR / f"{label}.json").read_text(encoding="utf-8")) for label in labels
    ]
    conditions = list(loaded[0]["summary"])
    print(f"{'điều kiện':12} " + " ".join(f"{label[:24]:>26}" for label in labels))
    for condition in conditions:
        cells = []
        for data in loaded:
            entry: Optional[dict] = data["summary"].get(condition)
            if entry is None:
                cells.append(f"{'-':>26}")
            elif "false_turns" in entry:
                cells.append(f"{entry['false_turns']:>20} giả/{entry['clips']}")
            else:
                cells.append(
                    f"{100 * entry['wer']:>8.1f}% {entry['meaning']:>4} nghĩa {entry['lost']:>3} mất"
                )
        print(f"{condition:12} " + " ".join(cells))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label")
    parser.add_argument("--conditions", default=DEFAULT_CONDITIONS)
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KHOÁ=GIÁ_TRỊ",
        help="ghi đè SpeechSettings, vd. --set asr_pre_speech_ms=300",
    )
    parser.add_argument("--oracle", action="store_true", help="thêm decode đúng đoạn có câu")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--compare", nargs="+")
    args = parser.parse_args()
    if args.compare:
        compare(args.compare)
        return
    if not args.label:
        parser.error("--label hoặc --compare là bắt buộc")
    overrides = dict(item.split("=", 1) for item in args.set)
    run(args.label, args.conditions.split(","), overrides, args.oracle, args.workers)


if __name__ == "__main__":
    main()
