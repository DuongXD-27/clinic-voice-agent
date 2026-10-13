"""So tiền xử lý của /v1/stt/turn trên bộ eval PM (`temp/PM_Public_Eval_STT`), từng file.

B0/B1 chạy `speech.asr.offline.transcribe_turn` của API. D1 và các biến thể có cổng im lặng
chỉ chạy trong `processors.py`, cùng các bộ xử lý D2–D8, theo thứ tự của `_prepare`.
Mỗi file x cấu hình lưu lại audio ASR đã nghe. Plan và tiêu chí: temp/docs/plan-preprocess-pm-eval.md;
kết quả: docs/evidence/pm-preprocess-2026-10-02.md.

    pip install noisereduce==3.0.3 nara_wpe==0.0.11  # chỉ cần cho D2–D8
    python eval/pm-preprocess/run.py --self-check    # processors.py không thêm bước = giống hệt API
    python eval/pm-preprocess/run.py --golden D1 D2  # bộ PM + kiểm chứng 40 câu golden của stt-bench
    python eval/pm-preprocess/run.py --suite neural --golden all  # khử nhiễu neural (temp/docs/thamkhao3.md)
    python eval/pm-preprocess/run.py --suite opt --golden all     # O0–O8: dùng lại kết quả đã đo + O1, O2

Đầu ra (chứa giọng thật, không commit): temp/pm-preprocess/<ngày>/
  report.html   bảng tổng hợp + từng file: nghe audio, đáp án, kết quả từng cấu hình tô màu theo từ
  results.csv   một dòng / file x cấu hình
  summary.json  số tổng hợp (và golden nếu có)
  audio/        audio sau xử lý, đúng thứ ASR đã nghe
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import sys
import time
import wave
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval" / "stt-bench"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
for _line in (ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []:
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        _key, _value = _line.split("=", 1)
        os.environ.setdefault(_key.strip(), _value.strip().strip('"').strip("'"))

from adapters.base import STTResult  # noqa: E402
from evaluate import evaluate_case, load_dataset, normalize_for_wer  # noqa: E402
from processors import ENHANCERS, enhancer_unavailable, prepare_experiment  # noqa: E402

from inference.asr import create_asr_gateway  # noqa: E402
from speech.asr.offline import transcribe_turn  # noqa: E402
from speech.asr.recognizer import SpeechRecognizer  # noqa: E402
from speech.asr.vad.silero import SileroVadClassifier  # noqa: E402
from speech.settings import SpeechSettings  # noqa: E402
from speech.types import AudioSegment  # noqa: E402

PM_DIR = ROOT / "temp" / "PM_Public_Eval_STT"
GOLDEN = ROOT / "eval" / "stt-bench" / "golden-cases.yaml"
RATES = {"16k": "01_audio_goc", "8k": "01_audio_8k"}
CONDITIONS = ["sach", "onnhe", "nhieumanh", "xa", "nhanh", "chong", "chongtieng", "matdau", "im"]
# Đáp án nghi sai: cả Zipformer-68M, PhoWhisper-medium (soat_lai.csv) và gipformer đều nghe thêm
# chữ "ngày" nhưng công cụ soát của PM vẫn ghi khớp 100%. Vẫn chấm theo đáp án hiện có, chỉ đánh dấu.
SUSPECT_REFERENCE = {"B-TIME-02"}

# Vòng 1 (02/10, chuỗi cộng dồn theo plan mục 5, kết quả ở temp/pm-preprocess/2026-10-02-vong1):
# cổng VAD chỉ dựa vào Silero bỏ cả câu thật trong ồn mạnh, kéo theo mọi cấu hình sau nó.
# Vòng 2: cổng an toàn (Silero không thấy giọng VÀ file dưới −55 dBFS), mỗi bộ xử lý đo riêng,
# có và không có lọc thông cao. Tham số giữ nguyên như plan. Giá trị = tham số của
# `prepare_experiment`; None = trường `production` (không tiền xử lý, như /v1/calls).
_API = ({},)  # chỉ baseline đi qua transcribe_turn của API
DSP_CONFIGS: dict[str, Optional[dict]] = {
    "B0": None,
    "B1": {},
    "D1": {"gate": True},
    "D2": {"gate": True, "highpass_hz": 100},
    "D3": {"gate": True, "denoise": 0.5},
    "D4": {"gate": True, "denoise": 0.8},
    "D5": {"gate": True, "dereverb": True},
    "D6": {"gate": True, "highpass_hz": 100, "denoise": 0.5},
    "D7": {"gate": True, "highpass_hz": 100, "denoise": 0.8},
    "D8": {"gate": True, "highpass_hz": 100, "dereverb": True},
}
DSP_LABELS = {
    "B0": "production (không xử lý)",
    "B1": "text hiện tại",
    "D1": "B1 + cổng im lặng thử nghiệm trong eval",
    "D2": "D1 + lọc thông cao 100 Hz",
    "D3": "D1 + khử nhiễu 0,5",
    "D4": "D1 + khử nhiễu 0,8",
    "D5": "D1 + khử vang WPE",
    "D6": "D2 + khử nhiễu 0,5",
    "D7": "D2 + khử nhiễu 0,8",
    "D8": "D2 + khử vang WPE",
}

# Suite neural (02/10, theo temp/docs/thamkhao3.md): từng model khử nhiễu neural so với cổng im lặng
# hiện tại (N0), không chồng thêm khử nhiễu cổ điển/khử vang. Model 8 kHz chỉ chạy trên file 8 kHz
# ("rates"). N7 = lọc thông cao + DPDFNet tốt nhất của từng tần số (chọn sau khi chạy N3–N6).
NEURAL_CONFIGS: dict[str, Optional[dict]] = {
    "B0": None,
    "B1": {},
    "N0": {"gate": True},
    "N1": {"gate": True, "highpass_hz": 100, "denoise": 0.8},
    "N2": {"gate": True, "enhancer": "gtcrn"},
    "N3": {"gate": True, "enhancer": "dpdfnet_baseline"},
    "N4": {"gate": True, "enhancer": "dpdfnet2"},
    "N5": {"gate": True, "enhancer": "dpdfnet4"},
    "N6": {"gate": True, "enhancer": "dpdfnet8"},
    "N4-8k": {"gate": True, "enhancer": "dpdfnet2_8khz", "rates": ["8k"]},
    "N6-8k": {"gate": True, "enhancer": "dpdfnet8_8khz", "rates": ["8k"]},
    "N8": {"gate": True, "enhancer": "deepfilternet3"},
    "N9": {"gate": True, "enhancer": "rnnoise"},
    "N7": {"gate": True, "highpass_hz": 100, "enhancer": "best-dpdfnet"},
}
NEURAL_LABELS = {
    "B0": "production (không xử lý)",
    "B1": "text hiện tại",
    "N0": "B1 + cổng im lặng thử nghiệm trong eval",
    "N1": "N0 + lọc thông cao + khử nhiễu 0,8 (= D7)",
    "N2": "N0 + GTCRN (16k)",
    "N3": "N0 + DPDFNet baseline (16k)",
    "N4": "N0 + DPDFNet2 (16k)",
    "N5": "N0 + DPDFNet4 (16k)",
    "N6": "N0 + DPDFNet8 (16k)",
    "N4-8k": "N0 + DPDFNet2 8 kHz (chỉ file 8k)",
    "N6-8k": "N0 + DPDFNet8 8 kHz (chỉ file 8k)",
    "N8": "N0 + DeepFilterNet3 (48k)",
    "N9": "N0 + RNNoise (48k)",
    "N7": "N0 + lọc thông cao → DPDFNet tốt nhất của tần số đó",
}
# Giới hạn mức nén của DPDFNet (attenuation_limit_db): giữ lại một phần nhiễu để bớt xoá giọng.
LIMIT_CONFIGS: dict[str, Optional[dict]] = {
    "B0": None,
    "B1": {},
    "N0": {"gate": True},
    "N4": {"gate": True, "enhancer": "dpdfnet2"},
    "N4-l12": {"gate": True, "enhancer": "dpdfnet2@12"},
    "N4-l6": {"gate": True, "enhancer": "dpdfnet2@6"},
    "N4-8k": {"gate": True, "enhancer": "dpdfnet2_8khz", "rates": ["8k"]},
    "N4-8k-l12": {"gate": True, "enhancer": "dpdfnet2_8khz@12", "rates": ["8k"]},
    "N4-8k-l6": {"gate": True, "enhancer": "dpdfnet2_8khz@6", "rates": ["8k"]},
}
LIMIT_LABELS = {
    "B0": "production (không xử lý)",
    "B1": "text hiện tại",
    "N0": "B1 + cổng im lặng thử nghiệm trong eval",
    "N4": "N0 + DPDFNet2 (16k), nén không giới hạn",
    "N4-l12": "N0 + DPDFNet2 (16k), nén tối đa 12 dB",
    "N4-l6": "N0 + DPDFNet2 (16k), nén tối đa 6 dB",
    "N4-8k": "N0 + DPDFNet2 8 kHz, nén không giới hạn",
    "N4-8k-l12": "N0 + DPDFNet2 8 kHz, nén tối đa 12 dB",
    "N4-8k-l6": "N0 + DPDFNet2 8 kHz, nén tối đa 6 dB",
}
# Suite opt (02/10): so tất cả lựa chọn trên cùng một bảng. Cấu hình đã đo ở lần chạy trước thì DÙNG
# LẠI kết quả ("reuse": thư mục kết quả, mã cấu hình nguồn — cùng code, kết quả xác định), chỉ chạy
# mới O1 (WebRTC NS) và O2 (SpeexDSP). O5 = DPDFNet bản gốc theo tần số, chọn bằng đúng quy tắc của
# N7 ở suite neural (16k: DPDFNet8, 8k: DPDFNet2 8 kHz).
_DSP_DIR, _NEURAL_DIR = "2026-10-02", "2026-10-02-neural"
OPT_CONFIGS: dict[str, Optional[dict]] = {
    "B0": {"reuse": (_NEURAL_DIR, "B0")},
    "B1": {"reuse": (_NEURAL_DIR, "B1")},
    "O0": {"reuse": (_NEURAL_DIR, "N0")},
    "O1": {"gate": True, "enhancer": "webrtc_ns"},
    "O2": {"gate": True, "enhancer": "speex_ns"},
    "O3": {"reuse": (_NEURAL_DIR, "N9")},
    "O4": {"reuse": (_NEURAL_DIR, "N2")},
    "O5": {"reuse": {"16k": (_NEURAL_DIR, "N6"), "8k": (_NEURAL_DIR, "N4-8k")}},
    "O6": {"reuse": (_NEURAL_DIR, "N8")},
    "O7": {"reuse": (_DSP_DIR, "D2")},
    "O8": {"reuse": (_DSP_DIR, "D7")},
}
OPT_LABELS = {
    "B0": "production (không xử lý)",
    "B1": "text hiện tại",
    "O0": "cổng im lặng thử nghiệm — baseline eval",
    "O1": "O0 + WebRTC NS",
    "O2": "O0 + SpeexDSP denoise",
    "O3": "O0 + RNNoise [lấy lại N9]",
    "O4": "O0 + GTCRN [lấy lại N2]",
    "O5": "O0 + DPDFNet bản gốc: 16k DPDFNet8, 8k DPDFNet2 8 kHz [lấy lại N6 / N4-8k]",
    "O6": "O0 + DeepFilterNet3 [lấy lại N8]",
    "O7": "O0 + lọc thông cao 100 Hz [lấy lại D2]",
    "O8": "O0 + lọc thông cao + khử nhiễu 0,8 [lấy lại D7]",
}
SUITES = {
    "dsp": (DSP_CONFIGS, DSP_LABELS),
    "opt": (OPT_CONFIGS, OPT_LABELS),
    "enhancer": (NEURAL_CONFIGS, NEURAL_LABELS),
    "neural-limit": (LIMIT_CONFIGS, LIMIT_LABELS),
}
# Suite đang chạy (main() gán); các hàm bên dưới đọc hai biến này.
CONFIGS: dict[str, Optional[dict]] = dict(DSP_CONFIGS)
LABELS: dict[str, str] = dict(DSP_LABELS)
_BEST_DPDFNET: dict[str, str] = {}  # tần số -> tên model, cho N7


@dataclass
class Case:
    id: str
    file: str
    condition: str
    critical: bool
    reference: str


def load_cases() -> list[Case]:
    def rows(name: str) -> list[dict]:
        with open(PM_DIR / name, encoding="utf-8-sig") as handle:
            return list(csv.DictReader(handle))

    plan = {row["id"]: row for row in rows("plan.csv")}
    answers = {
        row["ID (cột A)"]: row["LỜI NÓI THỰC TẾ (cột J)"] for row in rows("tab2_dan_vao.csv")
    }
    cases = []
    for row in rows("manifest.csv"):
        reference = "" if row["id"] == "B-SIL-01" else answers.get(row["id"], "")
        if row["id"] != "B-SIL-01" and (not reference or reference.startswith("CHƯA NGHE")):
            continue  # đáp án chưa chốt: không chấm
        critical = plan.get(row["id"], {}).get("muc_do") == "critical"
        cases.append(Case(row["id"], row["file"], row["dieu_kien"], critical, reference))
    return cases


def align(reference: str, hypothesis: str) -> list[tuple[str, str, str]]:
    """Căn từ (Levenshtein + truy vết): ("ok"|"sub"|"del"|"ins", từ đáp án, từ model)."""
    ref, hyp = normalize_for_wer(reference).split(), normalize_for_wer(hypothesis).split()
    rows, cols = len(ref) + 1, len(hyp) + 1
    cost = [[0] * cols for _ in range(rows)]
    for i in range(rows):
        cost[i][0] = i
    for j in range(cols):
        cost[0][j] = j
    for i in range(1, rows):
        for j in range(1, cols):
            same = ref[i - 1] == hyp[j - 1]
            cost[i][j] = min(
                cost[i - 1][j - 1] + (not same), cost[i - 1][j] + 1, cost[i][j - 1] + 1
            )
    ops: list[tuple[str, str, str]] = []
    i, j = rows - 1, cols - 1
    while i or j:
        if i and j and cost[i][j] == cost[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            ops.append(("ok" if ref[i - 1] == hyp[j - 1] else "sub", ref[i - 1], hyp[j - 1]))
            i, j = i - 1, j - 1
        elif i and cost[i][j] == cost[i - 1][j] + 1:
            ops.append(("del", ref[i - 1], ""))
            i -= 1
        else:
            ops.append(("ins", "", hyp[j - 1]))
            j -= 1
    return ops[::-1]


def _write_wav(path: Path, pcm: bytes, rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm)


def _vad_factory(model_path: str):
    return lambda rate: SileroVadClassifier(model_path, sample_rate=rate)


@dataclass
class Outcome:
    text: str
    steps: list[str]
    gain_db: float
    pcm: Optional[bytes]  # audio ASR đã nghe; None khi cổng im lặng chặn
    preprocess_ms: float
    production: Optional[str] = None


def _applies(params: dict, rate: str) -> bool:
    return rate in params.get("rates", RATES)


def _resolve(params: dict, rate: str) -> dict:
    """Bỏ khoá chỉ dùng cho harness; "best-dpdfnet" -> model DPDFNet thắng ở tần số này."""
    params = {k: v for k, v in params.items() if k != "rates"}
    if params.get("enhancer") == "best-dpdfnet":
        params["enhancer"] = _BEST_DPDFNET[rate]
    return params


def run_config(params: dict, data: bytes, asr, vad, *, compare: bool = False) -> Outcome:
    if params in _API:

        class Capture:
            input_sample_rate = asr.input_sample_rate

            def __init__(self):
                self.audio = []

            def transcribe(self, segment):
                self.audio.append(segment)
                return asr.transcribe(segment)

        capture = Capture()
        result = transcribe_turn(
            data,
            recognizer=capture,
            compare=compare,
        )
        return Outcome(
            result.text,
            result.steps,
            result.gain_db,
            capture.audio[0].pcm,
            result.timings.preprocess_ms,
            result.production.text if result.production else None,
        )
    started = time.perf_counter()
    pcm, steps, gain_db = prepare_experiment(data, asr.input_sample_rate, vad, **params)
    preprocess_ms = (time.perf_counter() - started) * 1000
    text = ""
    if pcm is not None:
        text = asr.transcribe(AudioSegment(pcm=pcm, sample_rate=asr.input_sample_rate)).text
    return Outcome(text, steps, gain_db, pcm, preprocess_ms)


def self_check(asr, vad) -> None:
    """`prepare_experiment` không thêm bước nào phải cho ra đúng audio và các bước của API."""
    mismatches = 0
    for folder in RATES.values():
        for case in load_cases():
            data = (PM_DIR / folder / "Ha_Noi" / "S01" / case.file).read_bytes()
            api = run_config({}, data, asr, vad)
            pcm, steps, _ = prepare_experiment(data, asr.input_sample_rate, vad)
            if pcm != api.pcm or steps != api.steps:
                mismatches += 1
                print(f"KHÁC: {folder} {case.file} {steps} vs {api.steps}")
    print(f"self-check: {mismatches} file khác API")
    if mismatches:
        raise SystemExit(1)


def score(reference: str, hypothesis: str) -> dict:
    ops = align(reference, hypothesis)
    counts = {kind: sum(1 for op in ops if op[0] == kind) for kind in ("sub", "del", "ins")}
    words = len(normalize_for_wer(reference).split())
    exact = not hypothesis.strip() if not words else sum(counts.values()) == 0
    return {"ops": ops, "words": words, "errors": sum(counts.values()), "exact": exact, **counts}


def _pick_best_dpdfnet(rows: list[dict]) -> None:
    """N7: DPDFNet có nhiều câu đúng hoàn toàn nhất ở điều kiện có nhiễu/xa của từng tần số; hoà thì
    ít lỗi hơn; vẫn hoà thì model nhỏ hơn (thứ tự trong CONFIGS)."""
    noisy = {"onnhe", "nhieumanh", "xa"}
    for rate in RATES:
        candidates = []
        for order, (config, params) in enumerate(CONFIGS.items()):
            name = (params or {}).get("enhancer", "")
            if (
                not name.startswith("dpdfnet")
                or not _applies(params, rate)
                or params.get("highpass_hz")
            ):
                continue
            mine = [r for r in rows if r["config"] == config and r["rate"] == rate]
            if not mine:
                continue
            exact = sum(r["exact"] for r in mine if r["condition"] in noisy)
            errors = sum(r["errors"] for r in mine)
            candidates.append((-exact, errors, order, name))
        if candidates:
            _BEST_DPDFNET[rate] = min(candidates)[3]
    print(f"N7 dùng: {_BEST_DPDFNET}", flush=True)


RESULTS_ROOT = ROOT / "temp" / "pm-preprocess"


def _reuse_source(spec, rate: str) -> tuple[str, str]:
    return tuple(spec[rate]) if isinstance(spec, dict) else tuple(spec)


def _reuse_rows(config: str, spec) -> list[dict]:
    """Dòng kết quả của cấu hình đã đo ở lần chạy trước, đổi tên thành `config`. Chấm lại từ đáp án
    và text (cùng hàm `score`); đường dẫn audio trỏ sang thư mục của lần chạy đó."""
    rows = []
    for rate in RATES:
        folder, source = _reuse_source(spec, rate)
        with open(RESULTS_ROOT / folder / "results.csv", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row["config"] != source or row["rate"] != rate:
                    continue
                audio = row["audio"]
                if audio.startswith("audio/"):
                    audio = f"../{folder}/{audio}"
                rows.append(
                    {
                        "rate": rate,
                        "config": config,
                        "id": row["id"],
                        "file": row["file"],
                        "condition": row["condition"],
                        "critical": row["critical"] == "True",
                        "reference": row["reference"],
                        "text": row["text"],
                        "steps": row["steps"].replace("NEURAL:", "ENHANCE:"),
                        "gain_db": float(row["gain_db"]),
                        "preprocess_ms": float(row["preprocess_ms"]),
                        "audio": audio,
                        **score(row["reference"], row["text"]),
                    }
                )
    if not rows:
        raise SystemExit(f"{config}: không tìm thấy kết quả để dùng lại ({spec})")
    return rows


def run_pm(out: Path, asr, vad) -> list[dict]:
    cases = load_cases()
    rows: list[dict] = []
    for config, params in CONFIGS.items():
        if params is None:
            continue  # B0 lấy từ trường production khi chạy B1
        if "reuse" in params:
            rows.extend(_reuse_rows(config, params["reuse"]))
            print(f"{config} lấy lại từ {params['reuse']}", flush=True)
            continue
        if params.get("enhancer") == "best-dpdfnet":
            _pick_best_dpdfnet(rows)
            LABELS[config] += f" ({', '.join(f'{r}: {m}' for r, m in _BEST_DPDFNET.items())})"
        for rate, folder in RATES.items():
            if not _applies(params, rate):
                continue
            resolved = _resolve(params, rate)
            for case in cases:
                data = (PM_DIR / folder / "Ha_Noi" / "S01" / case.file).read_bytes()
                outcome = run_config(resolved, data, asr, vad, compare=config == "B1")
                outputs = [(config, outcome)]
                if config == "B1":
                    outputs.insert(0, ("B0", Outcome(outcome.production, [], 0.0, None, 0.0)))
                for name, item in outputs:
                    if name == "B0":
                        audio_rel = f"../../PM_Public_Eval_STT/{folder}/Ha_Noi/S01/{case.file}"
                    elif item.pcm is None:
                        audio_rel = ""  # cổng im lặng chặn: ASR không nghe gì
                    else:
                        audio_rel = f"audio/{rate}/{name}/{case.file}"
                        _write_wav(out / audio_rel, item.pcm, asr.input_sample_rate)
                    rows.append(
                        {
                            "rate": rate,
                            "config": name,
                            "id": case.id,
                            "file": case.file,
                            "condition": case.condition,
                            "critical": case.critical,
                            "reference": case.reference,
                            "text": item.text,
                            "steps": " ".join(item.steps),
                            "gain_db": round(item.gain_db, 1),
                            "preprocess_ms": round(item.preprocess_ms, 1),
                            "audio": audio_rel,
                            **score(case.reference, item.text),
                        }
                    )
        print(f"{config} xong", flush=True)
    return rows


def summarize(rows: list[dict]) -> dict:
    table: dict = defaultdict(
        lambda: {"files": 0, "words": 0, "errors": 0, "exact": 0, "crit": 0, "crit_ok": 0}
    )
    timing: dict = defaultdict(list)
    for row in rows:
        for condition in (row["condition"], "ALL"):
            cell = table[(row["rate"], row["config"], condition)]
            cell["files"] += 1
            cell["words"] += row["words"]
            cell["errors"] += row["errors"]
            cell["exact"] += row["exact"]
            cell["crit"] += row["critical"]
            cell["crit_ok"] += row["critical"] and row["exact"]
        timing[(row["rate"], row["config"])].append(row["preprocess_ms"])
    summary = {}
    for (rate, config, condition), cell in table.items():
        cell["wer"] = round(cell["errors"] / cell["words"], 4) if cell["words"] else None
        summary.setdefault(rate, {}).setdefault(config, {})[condition] = cell
    for (rate, config), values in timing.items():
        ordered = sorted(values)
        summary[rate][config]["preprocess_ms"] = {
            "p50": ordered[len(ordered) // 2],
            "p95": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
        }
    return summary


def changes(rows: list[dict]) -> dict:
    """So với B1: file nào sai -> đúng (tốt lên) hoặc đúng -> sai (tệ đi), theo cấu hình."""
    base = {(r["rate"], r["file"]): r for r in rows if r["config"] == "B1"}
    result: dict = defaultdict(lambda: {"better": [], "worse": []})
    for row in rows:
        if row["config"] in ("B1",):
            continue
        before = base[(row["rate"], row["file"])]
        if row["exact"] and not before["exact"]:
            result[row["config"]]["better"].append(f"{row['rate']} {row['file']}")
        elif before["exact"] and not row["exact"]:
            result[row["config"]]["worse"].append(f"{row['rate']} {row['file']}")
    return result


def run_golden(configs: list[str], asr, vad) -> dict:
    """Kiểm chứng ngoài bộ PM: 40 câu golden của stt-bench (audio điện thoại thật, có nhãn)."""
    dataset = load_dataset(GOLDEN)
    results = {}
    names = [c for c in CONFIGS if CONFIGS[c] is not None] if configs == ["all"] else configs
    configs = [
        c
        for c in names
        if c not in ("B0", "B1") and CONFIGS.get(c) is not None and _applies(CONFIGS[c], "8k")
    ]
    for config in ["B1", *configs]:
        if config != "B1" and "reuse" in CONFIGS[config]:
            # golden là audio 8 kHz: lấy kết quả của cấu hình nguồn (đã so với cùng B1 ở lần đó)
            folder, source = _reuse_source(CONFIGS[config]["reuse"], "8k")
            previous = json.loads((RESULTS_ROOT / folder / "summary.json").read_text())["golden"]
            results[config] = dict(previous[source])
            continue
        scores = []
        # B1 luôn chạy lại (40 câu, vài giây) để có từng câu làm mốc cho cấu hình chạy mới
        params = {} if config == "B1" else _resolve(CONFIGS[config], "8k")
        for case in dataset.cases:
            outcome = run_config(params, case.audio_path.read_bytes(), asr, vad)
            scores.append(evaluate_case(case, STTResult(text=outcome.text)))
        errors = sum(s.wer.substitutions + s.wer.deletions + s.wer.insertions for s in scores)
        results[config] = {
            "passed": sum(s.passed for s in scores),
            "cases": len(scores),
            "hallucinations": sum(s.hallucination for s in scores),
            "errors": errors,
            "words": sum(s.wer.reference_word_count for s in scores),
            "changed": [
                {"id": s.case.id, "text": s.prediction, "passed": s.passed} for s in scores
            ],
        }
        print(
            f"golden {config}: {results[config]['passed']}/{len(scores)} pass, {errors} lỗi",
            flush=True,
        )
    base = {c["id"]: c for c in results["B1"]["changed"]}
    for config in configs:
        if "reuse" in CONFIGS[config]:
            continue
        results[config]["changed"] = [
            {**c, "before": base[c["id"]]["text"]}
            for c in results[config]["changed"]
            if c["text"] != base[c["id"]]["text"]
        ]
    results["B1"].pop("changed")
    return results


# --- báo cáo HTML --------------------------------------------------------------------------------


def _ops_html(ops: list[tuple[str, str, str]]) -> str:
    parts = []
    for kind, ref, hyp in ops:
        if kind == "ok":
            parts.append(html.escape(hyp))
        elif kind == "sub":
            parts.append(
                f'<span class="sub" title="đáp án: {html.escape(ref)}">{html.escape(hyp)}</span>'
            )
        elif kind == "del":
            parts.append(f'<span class="del" title="model bỏ mất">{html.escape(ref)}</span>')
        else:
            parts.append(f'<span class="ins" title="model thêm">{html.escape(hyp)}</span>')
    return " ".join(parts) or '<span class="empty">(rỗng)</span>'


def write_report(
    out: Path, rows: list[dict], summary: dict, delta: dict, golden: dict | None
) -> None:
    configs = list(CONFIGS)
    conds = [c for c in CONDITIONS if any(r["condition"] == c for r in rows)]
    head = []
    for rate in RATES:
        head.append(f"<h3>{rate}</h3><table class='sum'><tr><th>Cấu hình</th>")
        head.extend(f"<th>{c}</th>" for c in [*conds, "ALL"])
        head.append("<th>Tốt lên / tệ đi so với B1</th><th>Xử lý thêm p50 / p95 (ms)</th></tr>")
        for config in configs:
            cells = summary[rate].get(config)
            if cells is None:
                continue  # cấu hình không áp cho tần số này (model 8 kHz)
            head.append(f"<tr><td><b>{config}</b> {LABELS[config]}</td>")
            for cond in [*conds, "ALL"]:
                cell = cells.get(cond)
                if not cell:
                    head.append("<td></td>")
                    continue
                wer = f"{cell['wer'] * 100:.1f}%" if cell["wer"] is not None else "—"
                head.append(f"<td>{cell['exact']}/{cell['files']}<br><small>WER {wer}</small></td>")
            d = delta.get(config, {"better": [], "worse": []})
            better = sum(1 for x in d["better"] if x.startswith(rate))
            worse = sum(1 for x in d["worse"] if x.startswith(rate))
            ms = cells.get("preprocess_ms", {"p50": 0, "p95": 0})
            head.append(
                f"<td>{'' if config in ('B1',) else f'+{better} / −{worse}'}</td>"
                f"<td>{ms['p50']:.0f} / {ms['p95']:.0f}</td></tr>"
            )
        head.append("</table>")

    golden_html = ""
    if golden:
        golden_html = "<h2>Kiểm chứng: 40 câu golden (stt-bench, audio điện thoại thật)</h2><table class='sum'><tr><th>Cấu hình</th><th>Pass</th><th>Bịa chữ</th><th>Tổng lỗi / từ</th><th>Câu đổi so với B1</th></tr>"
        for config, g in golden.items():
            changed = "".join(
                f"<div><b>{html.escape(c['id'])}</b>: {html.escape(c['before'])} → {html.escape(c['text'])} ({'pass' if c['passed'] else 'fail'})</div>"
                for c in g.get("changed", [])
            )
            golden_html += f"<tr><td><b>{config}</b> {LABELS[config]}</td><td>{g['passed']}/{g['cases']}</td><td>{g['hallucinations']}</td><td>{g['errors']} / {g['words']}</td><td>{changed}</td></tr>"
        golden_html += "</table>"

    by_file: dict = defaultdict(dict)
    for row in rows:
        by_file[(row["rate"], row["file"])][row["config"]] = row
    cards = []
    for (rate, file), per in sorted(
        by_file.items(), key=lambda kv: (kv[0][0], kv[1]["B1"]["condition"], kv[0][1])
    ):
        b1 = per["B1"]
        here = [c for c in configs if c in per]
        statuses = {c: ("ok" if per[c]["exact"] else "bad") for c in here}
        changed = any(per[c]["exact"] != b1["exact"] or per[c]["text"] != b1["text"] for c in here)
        flags = []
        if b1["id"] in SUSPECT_REFERENCE:
            flags.append("<span class='flag'>đáp án nghi sai</span>")
        if b1["critical"]:
            flags.append("<span class='crit'>critical</span>")
        lines = []
        for config in here:
            row = per[config]
            player = (
                f"<audio controls preload='none' src='{html.escape(row['audio'])}'></audio>"
                if row["audio"]
                else "<small>ASR không nghe (cổng VAD chặn)</small>"
            )
            meta = f"gain {row['gain_db']} dB · {row['steps']}" if config != "B0" else ""
            lines.append(
                f"<tr class='{statuses[config]}'><td><b>{config}</b></td><td>{_ops_html(row['ops'])}</td>"
                f"<td>{row['errors']}</td><td>{player}</td><td><small>{html.escape(meta)}</small></td></tr>"
            )
        cards.append(
            f"<section class='card' data-rate='{rate}' data-cond='{b1['condition']}' "
            f"data-changed='{int(changed)}' data-wrong='{int(not all(per[c]['exact'] for c in here))}'>"
            f"<h4>{html.escape(file)} <small>{rate} · {b1['condition']}</small> {' '.join(flags)}</h4>"
            f"<div class='ref'>Đáp án: <b>{html.escape(b1['reference']) or '(im lặng — phải ra rỗng)'}</b></div>"
            f"<table class='lines'><tr><th>Cấu hình</th><th>Model trả ra</th><th>Lỗi</th><th>Audio ASR nghe</th><th>Bước</th></tr>{''.join(lines)}</table></section>"
        )

    options = "".join(f"<option>{c}</option>" for c in conds)
    page = f"""<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tiền xử lý STT — bộ PM</title><style>
:root{{--bg:#fff;--fg:#1d1d1f;--muted:#666;--line:#ddd;--bad:#fdecec;--ok:#eef8ee;--sub:#c62828;--ins:#2e7d32}}
@media (prefers-color-scheme:dark){{:root{{--bg:#141414;--fg:#eee;--muted:#aaa;--line:#333;--bad:#3a1f1f;--ok:#1d2e1d;--sub:#ff8a80;--ins:#81c784}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:16px;max-width:1300px}}
table{{border-collapse:collapse;width:100%;margin:6px 0 14px}}td,th{{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}}
.sum td,.sum th{{font-size:13px}}small{{color:var(--muted)}}.card{{border:1px solid var(--line);border-radius:8px;padding:8px 12px;margin:10px 0}}
tr.bad td:nth-child(2){{background:var(--bad)}}tr.ok td:nth-child(2){{background:var(--ok)}}
.sub{{color:var(--sub);font-weight:600;text-decoration:underline wavy}}.del{{color:var(--sub);text-decoration:line-through}}.ins{{color:var(--ins);font-weight:600}}
.empty{{color:var(--muted)}}.flag{{background:#f9a825;color:#000;border-radius:4px;padding:0 6px;font-size:12px}}.crit{{border:1px solid var(--muted);border-radius:4px;padding:0 6px;font-size:12px}}
audio{{height:28px;max-width:260px}}.ref{{margin:2px 0 4px}}.bar{{position:sticky;top:0;background:var(--bg);padding:8px 0;border-bottom:1px solid var(--line)}}
</style></head><body>
<h1>Tiền xử lý trước ASR — bộ eval PM (Hà Nội, S01)</h1>
<p>Chạy đúng <code>transcribe_turn</code> của <code>/v1/stt/turn</code>, model gipformer1.5. Mỗi ô tổng hợp: <b>số câu đúng hoàn toàn / số file</b>, dưới là WER.
Tô màu: <span class="sub">sai</span>, <span class="del">mất</span>, <span class="ins">thừa</span> (rê chuột xem đáp án). <span class="flag">đáp án nghi sai</span>: B-TIME-02 — ba model đều nghe thêm chữ "ngày".</p>
<h2>Tổng hợp</h2>{"".join(head)}{golden_html}
<h2>Từng file</h2>
<div class="bar">Tần số <select id="rate"><option value="">tất cả</option><option>16k</option><option>8k</option></select>
Điều kiện <select id="cond"><option value="">tất cả</option>{options}</select>
<label><input type="checkbox" id="changed"> chỉ file có cấu hình cho kết quả khác B1</label>
<label><input type="checkbox" id="wrong"> chỉ file còn sai ở ít nhất một cấu hình</label></div>
{"".join(cards)}
<script>
const f=()=>{{const r=rate.value,c=cond.value,ch=changed.checked,w=wrong.checked;
document.querySelectorAll('.card').forEach(e=>{{e.style.display=(!r||e.dataset.rate==r)&&(!c||e.dataset.cond==c)&&(!ch||e.dataset.changed=='1')&&(!w||e.dataset.wrong=='1')?'':'none'}})}};
[rate,cond,changed,wrong].forEach(e=>e.addEventListener('change',f));
</script></body></html>"""
    (out / "report.html").write_text(page, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--out", type=Path, default=ROOT / "temp" / "pm-preprocess" / time.strftime("%Y-%m-%d")
    )
    parser.add_argument(
        "--golden", nargs="*", default=None, help="cấu hình chạy thêm trên 40 câu golden"
    )
    parser.add_argument("--self-check", action="store_true", help="chỉ kiểm processors.py = API")
    parser.add_argument("--suite", choices=sorted(SUITES), default="dsp")
    args = parser.parse_args()
    CONFIGS.clear()
    CONFIGS.update(SUITES[args.suite][0])
    LABELS.clear()
    LABELS.update(SUITES[args.suite][1])
    if args.suite != "dsp" and args.out.name == time.strftime("%Y-%m-%d"):
        args.out = args.out.with_name(f"{args.out.name}-{args.suite}")
    skipped = {}
    for config, params in list(CONFIGS.items()):
        name = (params or {}).get("enhancer")
        if name and name.split("@")[0] in ENHANCERS and (reason := enhancer_unavailable(name)):
            skipped[config] = reason  # cũng nạp sẵn model để thời gian đo không gồm lần nạp đầu
            del CONFIGS[config]
            print(f"BỎ QUA {config} ({name}): {reason}", flush=True)

    settings = SpeechSettings()
    asr = SpeechRecognizer(create_asr_gateway("zipformer"))
    vad = _vad_factory(settings.silero_vad_model_path)
    if args.self_check:
        self_check(asr, vad)
        return
    args.out.mkdir(parents=True, exist_ok=True)
    rows = run_pm(args.out, asr, vad)
    summary = summarize(rows)
    delta = changes(rows)
    golden = run_golden(args.golden, asr, vad) if args.golden else None

    with open(args.out / "results.csv", "w", newline="", encoding="utf-8") as handle:
        fields = [k for k in rows[0] if k != "ops"]
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    payload = {
        "suite": args.suite,
        "configs": CONFIGS,
        "best_dpdfnet": _BEST_DPDFNET,
        "skipped": skipped,
        "summary": summary,
        "changes": delta,
        "golden": golden,
    }
    (args.out / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    write_report(args.out, rows, summary, delta, golden)
    print(f"-> {args.out / 'report.html'}")


if __name__ == "__main__":
    main()
