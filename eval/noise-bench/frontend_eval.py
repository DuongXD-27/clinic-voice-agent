"""Đo tiền xử lý đầu vào STT LiveKit trên nhiều bộ có nhãn và nhiều tình huống âm thanh.

Hai chế độ:
- `vad`: chỉ Silero (nhanh) — với mỗi front-end của bộ phân loại (`speech.audio.vad_frontend`):
  tỉ lệ frame giọng được nhận ra, câu bị bỏ sót hẳn, độ trễ nhận ra đầu câu / nhả cuối câu, báo
  nhầm trên đoạn chỉ có nhiễu. Dùng để lọc cấu hình trước khi chạy pipeline đầy đủ.
- `pipeline`: đúng `STTPipeline.stream()` của worker LiveKit (như bench.py: Silero, GipFormer,
  TurnController + Validator, đồng hồ ảo) — WER lượt so với nhãn, mất lượt, lượt giả trên đoạn
  chỉ có nhiễu, độ trễ chốt lượt. `--set` ghi đè SpeechSettings; `--channel phone` áp
  `phone_overrides` như worker làm với participant SIP (bench.py thì không).

Bộ dữ liệu (`--datasets`, có nhãn trừ web/short):
- `golden`: 37 câu điện thoại thật có lời (eval/stt-bench), 8 kHz.
- `pm`: 31 câu đọc thật 16 kHz của bộ PM Hà Nội (temp/PM_Public_Eval_STT, điều kiện `sach`).
- `vietmed`: VietMed test (huggingface.co/datasets/leduckhai/VietMed, MIT) — hội thoại y khoa
  thật, 8 kHz, nhiều vùng miền; lấy đều theo `rec_condition` (Tel, Consultation, Diagnosis,
  Talkshow, Podcast, Lectures, News), câu 2-10 s. Tải: temp/aq/data/vietmed/test.parquet.
- `vivos`: VIVOS test (temp/datasets/vivos/test.parquet), đọc, 16 kHz.
- `web` / `short`: câu thật của người thử nghiệm qua LiveKit (bench.py) — không nhãn, tham chiếu
  là decode câu sạch.

Nhiễu (`<tên>@<SNR>`): `office` (nền thật cắt từ dump LiveKit), `cafe` (DEMAND PCAFETER — căng tin,
nhiều người nói), `traffic` / `hallway` / `bus` / `station` / `square` / `kitchen` / `living` (DEMAND),
`street` (PM duong.wav), `esc_human` / `esc_house` / `esc_street` (ESC-50: tiếng động rời ghép chuỗi).
Nền là giọng người: `tv` (PM tv.wav), `babble` (3 giọng golden), `voice2` (một người khác nói),
`bcast` (đài / TV thật: VietMed News, Talkshow, Podcast). DEMAND: zenodo.org/records/1227121 (CC BY-SA
3.0), giải nén ch01.wav vào temp/aq/data/demand/<ENV>/.
Biến thể nối bằng `~`: `q25` cả cuộc gọi nhỏ đi 25 dB (mic/đường truyền nhỏ), `far15` chỉ giọng
nhỏ đi 15 dB (nói xa mic, nhiễu phòng giữ nguyên), `rev6` vang phòng RT60 0,6 s, `bns` khử nhiễu
của trình duyệt (WebRTC NS + lọc thông cao, như livekit-client mặc định) trước khi tới worker.
Ví dụ: `clean`, `clean~q25`, `office@20~far15`, `cafe@5`, `clean~rev6`.

    python eval/noise-bench/frontend_eval.py vad --label s1 --datasets golden,pm,vietmed,web
    python eval/noise-bench/frontend_eval.py pipeline --label base --datasets golden,pm,vietmed \\
        --conditions clean,office@8,cafe@5 --set speaker_gate_mode=off
    python eval/noise-bench/frontend_eval.py pipeline --label gtcrn ... --set vad_frontend=gtcrn
    python eval/noise-bench/frontend_eval.py compare base gtcrn
    python eval/noise-bench/frontend_eval.py paired base gtcrn   # từng cặp trial, KTC 95%

Kết quả: temp/aq/results/<label>.json (không commit).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import os
import re
import sys
import time
import unicodedata
from multiprocessing import get_context
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench  # noqa: E402  (đưa src/ vào sys.path, helper trộn nhiễu / kênh điện thoại)

from speech.asr.vad.silero import SileroVadClassifier  # noqa: E402
from speech.audio.vad_frontend import build_vad_frontend  # noqa: E402

ROOT = bench.ROOT
RATE = bench.RATE
FRAME = bench.FRAME
OUT_DIR = ROOT / "temp" / "aq" / "results"
DATA_DIR = ROOT / "temp" / "aq" / "data"
SILERO = str(ROOT / "src" / "speech" / "asr" / "vad" / "assets" / "silero_vad.onnx")
SE_MODELS = ROOT / "temp" / "models" / "speech-enhancement"
NOISE_SECONDS = 8.0
NOISE_TRIALS = 12

# ------------------------------------------------------------------ chuẩn hoá chữ cho WER

_TONE_MARKS = "̣̀́̃̉"
_DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]


def _two(n: int) -> str:
    if n < 10:
        return _DIGITS[n]
    tens, unit = divmod(n, 10)
    head = "mười" if tens == 1 else _DIGITS[tens] + " mươi"
    if unit == 0:
        return head
    tail = "mốt" if unit == 1 and tens > 1 else "lăm" if unit == 5 else _DIGITS[unit]
    return f"{head} {tail}"


def _number(n: int) -> str:
    if n < 100:
        return _two(n)
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        head = _DIGITS[hundreds] + " trăm"
        return (
            head
            if rest == 0
            else f"{head} linh {_DIGITS[rest]}"
            if rest < 10
            else f"{head} {_two(rest)}"
        )
    thousands, rest = divmod(n, 1000)
    head = _number(thousands) + " nghìn"
    return (
        head
        if rest == 0
        else f"{head} {_number(rest) if rest >= 100 else 'không trăm ' + _number(rest)}"
    )


def _read_number(digits: str) -> str:
    """Năm 19xx đọc từng chữ số như người gọi đọc ngày sinh ("một chín bảy tám"), số khác đọc
    thường ("mười bốn", "hai nghìn")."""
    if len(digits) == 4 and digits.startswith("19"):
        return " ".join(_DIGITS[int(d)] for d in digits)
    return _number(int(digits))


def norm_words(text: str) -> str:
    """Chữ hoa NFC, bỏ dấu câu, số đọc thành chữ, dấu thanh kiểu mới như tokens của GipFormer
    ("HÒA", "THÙY"): nhãn VietMed / PM viết kiểu cũ ("hoà") không thành lỗi giả."""
    text = re.sub(r"\d+", lambda m: _read_number(m.group()), unicodedata.normalize("NFC", text))
    text = "".join(" " if unicodedata.category(c).startswith("P") else c for c in text.upper())
    out = []
    for syllable in text.split():
        groups: list[list[str]] = []
        for char in unicodedata.normalize("NFD", syllable):
            if unicodedata.combining(char) and groups:
                groups[-1].append(char)
            else:
                groups.append([char])
        base = "".join(g[0] for g in groups)
        tone = [c for g in groups for c in g if c in _TONE_MARKS]
        if (
            tone
            and len(groups) >= 2
            and re.search(r"(OA|OE|UY)$", base)
            and not base.startswith("QU")
        ):
            groups = [[c for c in g if c not in _TONE_MARKS] for g in groups]
            groups[-2].append(tone[0])
            syllable = "".join("".join(g) for g in groups)
        out.append(unicodedata.normalize("NFC", syllable))
    return " ".join(out)


def word_errors(reference: str, hypothesis: str) -> tuple[int, int]:
    """(số lỗi S+D+I, số từ nhãn) sau `norm_words`."""
    ref, hyp = norm_words(reference).split(), norm_words(hypothesis).split()
    previous = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        current = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (r != h))
        previous = current
    return previous[-1], len(ref)


# ------------------------------------------------------------------ dữ liệu


def _decode_audio(raw: bytes) -> tuple[np.ndarray, int]:
    import soundfile as sf

    samples, rate = sf.read(io.BytesIO(raw), dtype="int16", always_2d=False)
    if samples.ndim > 1:
        samples = samples.mean(axis=1).astype(np.int16)
    return samples, rate


def load_pm() -> list[dict]:
    base = ROOT / "temp" / "PM_Public_Eval_STT"
    folder = base / "01_audio_goc" / "Ha_Noi" / "S01"
    cases = []
    with open(base / "manifest.csv", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["nguon"] != "ghi_that" or row["dieu_kien"] != "sach" or not row["cau_chuan"]:
                continue
            samples, rate = bench._read_wav(folder / row["file"])
            cases.append(
                {
                    "id": f"PM_{row['id']}",
                    "reference": row["cau_chuan"],
                    "speech": bench._to_16k(samples, rate),
                }
            )
    return cases


def load_vietmed(per_condition: int, seed: int = 20261012) -> list[dict]:
    import pyarrow.parquet as pq

    table = pq.read_table(DATA_DIR / "vietmed" / "test.parquet")
    rows = table.to_pylist()
    rng = np.random.default_rng(seed)
    by_condition: dict[str, list[dict]] = {}
    for row in rows:
        words = len(row["text"].split())
        if 2.0 <= row["duration"] <= 10.0 and words >= 4:
            by_condition.setdefault(row["rec_condition"], []).append(row)
    cases = []
    for condition in sorted(by_condition):
        pool = by_condition[condition]
        for index in rng.permutation(len(pool))[:per_condition]:
            row = pool[int(index)]
            samples, rate = _decode_audio(row["audio"]["bytes"])
            cases.append(
                {
                    "id": f"VM_{condition}_{row['utterance_id']}",
                    "reference": row["text"],
                    "speech": bench._to_16k(samples, rate),
                    "group": condition,
                }
            )
    return cases


def load_vivos(count: int, seed: int = 7) -> list[dict]:
    import pyarrow.parquet as pq

    rows = pq.read_table(ROOT / "temp" / "datasets" / "vivos" / "test.parquet").to_pylist()
    rng = np.random.default_rng(seed)
    cases = []
    for index in rng.permutation(len(rows))[:count]:
        row = rows[int(index)]
        audio = row.get("audio")
        text = row.get("sentence") or row.get("text") or row.get("transcription")
        samples, rate = _decode_audio(audio["bytes"])
        cases.append(
            {"id": f"VIVOS_{int(index)}", "reference": text, "speech": bench._to_16k(samples, rate)}
        )
    return cases


def load_dataset(name: str, asr=None) -> list[dict]:
    if name == "golden":
        return bench.load_golden()
    if name == "pm":
        return load_pm()
    if name.startswith("vietmed"):
        per = int(name[len("vietmed") :] or 6)
        return load_vietmed(per)
    if name.startswith("vivos"):
        return load_vivos(int(name[len("vivos") :] or 40))
    if name == "web":
        return bench.build_web_set(asr, SILERO)
    if name == "short":
        return bench.build_short_set(asr, SILERO)
    raise ValueError(f"bộ dữ liệu lạ: {name}")


def _load_wav16(path: Path) -> np.ndarray:
    samples, rate = bench._read_wav(path)
    return bench._to_16k(samples, rate)


def load_noises(golden: list[dict]) -> dict[str, np.ndarray]:
    noises = {
        "office": bench.build_office_noise(SILERO),
        "street": _load_wav16(ROOT / "temp" / "PM_Public_Eval_STT" / "noise" / "duong.wav"),
        "tv": _load_wav16(ROOT / "temp" / "PM_Public_Eval_STT" / "noise" / "tv.wav"),
        "babble": bench.build_babble([c["speech"] for c in golden]),
    }
    noises.update(load_extra_noises())
    # Tiếng người nền: một người khác nói (giọng web, khác người với golden) và phát thanh / truyền hình
    # thật (VietMed News, Talkshow, Podcast — 8 kHz, khác hẳn câu đang đo).
    noises["voice2"] = np.asarray(
        bench.build_voice2([c["speech"] for c in bench.build_web_set(None, SILERO)]),
        dtype=np.float32,
    )
    bcast = _vietmed_broadcast()
    if bcast is not None:
        noises["bcast"] = bcast
    return noises


def _vietmed_broadcast(seconds: float = 300.0) -> np.ndarray | None:
    import pyarrow.parquet as pq

    path = DATA_DIR / "vietmed" / "test.parquet"
    if not path.exists():
        return None
    rows = pq.read_table(path, columns=["audio", "rec_condition"]).to_pylist()
    parts, total = [], 0
    for row in rows:
        if row["rec_condition"] not in ("News", "Talkshow", "Podcast"):
            continue
        samples, rate = _decode_audio(row["audio"]["bytes"])
        parts.append(bench._to_16k(samples, rate))
        total += len(parts[-1])
        if total >= seconds * RATE:
            break
    return np.concatenate(parts).astype(np.float32)


DEMAND_ENVS = {
    "cafe": "PCAFETER",
    "traffic": "STRAFFIC",
    "hallway": "OHALLWAY",
    "living": "DLIVING",
    "bus": "TBUS",
    "station": "PSTATION",
    "square": "SPSQUARE",
    "kitchen": "DKITCHEN",
    "meeting": "OMEETING",
    "park": "NPARK",
}
# ESC-50 (github.com/karoldvl/ESC-50, CC BY-NC 3.0): tiếng động rời ghép thành chuỗi (giữa các tiếng là
# im lặng 0,3–1,5 s), mỗi nhóm một chuỗi. Giải nén vào temp/aq/data/esc50/x/ESC-50-master/.
ESC_GROUPS = {
    "esc_human": ["coughing", "sneezing", "breathing", "laughing", "crying_baby", "snoring",
                  "clapping", "footsteps", "drinking_sipping", "brushing_teeth"],
    "esc_house": ["door_wood_knock", "door_wood_creaks", "keyboard_typing", "mouse_click",
                  "clock_tick", "clock_alarm", "can_opening", "glass_breaking", "pouring_water",
                  "toilet_flush", "vacuum_cleaner", "washing_machine", "water_drops"],
    "esc_street": ["car_horn", "siren", "engine", "train", "airplane", "helicopter", "church_bells",
                   "dog", "rooster", "rain", "wind"],
}  # fmt: skip


def load_extra_noises() -> dict[str, np.ndarray]:
    """Nhiễu DEMAND (zenodo 1227121, ch01) có trên đĩa + chuỗi ESC-50 theo nhóm."""
    import csv

    import soundfile as sf

    out: dict[str, np.ndarray] = {}
    for name, env in DEMAND_ENVS.items():
        path = DATA_DIR / "demand" / env / "ch01.wav"
        if path.exists():
            samples, rate = sf.read(path, dtype="float32")
            out[name] = bench._to_16k(
                np.clip(samples * 32768, -32768, 32767).astype(np.int16), rate
            )
    esc = DATA_DIR / "esc50" / "x" / "ESC-50-master"
    if esc.exists():
        with open(esc / "meta" / "esc50.csv", encoding="utf-8") as handle:
            meta = list(csv.DictReader(handle))
        rng = np.random.default_rng(5)
        for group, cats in ESC_GROUPS.items():
            files = [m["filename"] for m in meta if m["category"] in cats]
            rng.shuffle(files)
            parts = []
            for name in files[:120]:
                clip = _load_wav16(esc / "audio" / name).astype(np.float64)
                nz = np.nonzero(np.abs(clip) > 20)[0]
                if not len(nz):
                    continue
                clip = clip[nz[0] : nz[-1] + 1]
                parts.append(clip * (1000.0 / max(bench._active_rms(clip), 1.0)))
                parts.append(np.zeros(int(rng.uniform(0.3, 1.5) * RATE)))
            out[group] = np.concatenate(parts).astype(np.float32)
    return out


# ------------------------------------------------------------------ dựng trial


def synthetic_rir(rt60: float, rng: np.random.Generator) -> np.ndarray:
    """Đáp ứng phòng tổng hợp: xung trực tiếp + đuôi nhiễu trắng tắt dần theo RT60 (bắt đầu sau
    2,5 ms), năng lượng đuôi ngang năng lượng xung trực tiếp (nói cách mic ~1 m trong phòng nhỏ)."""
    length = int(rt60 * RATE)
    t = np.arange(length) / RATE
    tail = rng.normal(0, 1, length) * np.exp(-6.9 * t / rt60)
    tail[: int(0.0025 * RATE)] = 0
    tail *= 1.0 / max(np.sqrt(np.sum(tail**2)), 1e-9)
    rir = tail
    rir[0] += 1.0
    return rir


def browser_ns(pcm: np.ndarray) -> np.ndarray:
    """Khử nhiễu + lọc thông cao của trình duyệt (livekit-client mặc định noiseSuppression: true —
    cùng WebRTC APM của libwebrtc, qua livekit.rtc), chạy trước khi audio rời máy người gọi."""
    from livekit import rtc

    apm = rtc.AudioProcessingModule(noise_suppression=True, high_pass_filter=True)
    chunk = RATE // 100
    out = pcm.copy()
    for start in range(0, len(out) - chunk + 1, chunk):
        frame = rtc.AudioFrame(
            data=out[start : start + chunk].tobytes(),
            sample_rate=RATE,
            num_channels=1,
            samples_per_channel=chunk,
        )
        apm.process_stream(frame)
        out[start : start + chunk] = np.frombuffer(frame.data, dtype=np.int16)
    return out


def parse_condition(condition: str) -> dict:
    base, *mods = condition.split("~")
    noise, _, snr = base.partition("@")
    spec = {
        "noise": None if noise == "clean" else noise,
        "snr": float(snr) if snr else None,
        "quiet_db": 0.0,
        "far_db": 0.0,
        "rt60": 0.0,
        "browser_ns": False,
    }
    for mod in mods:
        if mod.startswith("q"):
            spec["quiet_db"] = float(mod[1:])
        elif mod.startswith("far"):
            spec["far_db"] = float(mod[3:])
        elif mod.startswith("rev"):
            spec["rt60"] = float(mod[3:]) / 10
        elif mod == "bns":
            spec["browser_ns"] = True
        else:
            raise ValueError(f"biến thể lạ: {mod}")
    if spec["noise"] is not None and spec["snr"] is None:
        raise ValueError(f"thiếu SNR: {condition}")
    return spec


def build_trial(
    speech: np.ndarray | None,
    spec: dict,
    noises: dict,
    rng: np.random.Generator,
    *,
    channel: str,
    noise_rms_target: float | None = None,
    seconds: float | None = None,
) -> np.ndarray:
    """Như bench.make_trial (đệm 1,2 s trước / 2 s sau, SNR tính trên đoạn có giọng của câu GỐC)
    thêm vang phòng, nói xa, cả cuộc gọi nhỏ, kênh điện thoại. `speech=None`: đoạn chỉ có nhiễu
    dài `seconds` ở mức `noise_rms_target`."""
    if speech is not None:
        level = bench._active_rms(speech)
        source = speech.astype(np.float64)
        if spec["rt60"]:
            source = np.convolve(source, synthetic_rir(spec["rt60"], rng))[
                : len(source) + int(0.3 * RATE)
            ]
            source *= level / max(bench._active_rms(source), 1e-6)
        if spec["far_db"]:
            source = source * 10 ** (-spec["far_db"] / 20)
        total = int(bench.LEAD_S * RATE) + len(source) + int(bench.TAIL_S * RATE)
        mix = np.zeros(total)
        lead = int(bench.LEAD_S * RATE)
        mix[lead : lead + len(source)] = source
    else:
        total = int((seconds or NOISE_SECONDS) * RATE)
        mix = np.zeros(total)
    noise_name = spec["noise"]
    if noise_name is None:
        mix += rng.normal(0.0, 1.0, total)  # dither nhẹ như bench.make_trial
    else:
        noise = noises[noise_name]
        start = int(rng.integers(0, len(noise) - total))
        segment = noise[start : start + total].astype(np.float64)
        speech_like = noise_name in ("tv", "babble", "voice2", "bcast") or noise_name.startswith(
            "esc_"
        )
        noise_level = max((bench._active_rms if speech_like else bench._rms)(segment), 1e-6)
        if speech is not None:
            target = level / 10 ** (spec["snr"] / 20)
        else:
            target = noise_rms_target
        mix += segment * (target / noise_level)
    if spec["quiet_db"]:
        mix *= 10 ** (-spec["quiet_db"] / 20)
    pcm = np.clip(np.round(mix), -32768, 32767).astype(np.int16)
    if spec["browser_ns"]:
        pcm = browser_ns(pcm)
    return bench.phone_channel(pcm) if channel == "phone" else pcm


def active_frames(speech: np.ndarray, spec: dict) -> tuple[int, int, np.ndarray]:
    """(frame đầu, frame cuối, mặt nạ) các frame có giọng của câu trong trial — frame trong vòng
    30 dB so với frame to nhất của câu gốc (chưa trộn nhiễu)."""
    lead = int(bench.LEAD_S * RATE) // FRAME
    count = len(speech) // FRAME
    levels = np.array([bench._rms(speech[i * FRAME : (i + 1) * FRAME]) for i in range(count)])
    mask = levels >= levels.max() * 10 ** (-30 / 20) if count else np.zeros(0, bool)
    idx = np.nonzero(mask)[0]
    return lead + int(idx[0]), lead + int(idx[-1]), mask


# ------------------------------------------------------------------ chế độ vad

# Mỗi front-end: (khoá bộ khử nhiễu dùng chung, tham số tăng âm/ngưỡng). Bộ khử nhiễu chạy một lần
# mỗi trial, các biến thể tăng âm / ngưỡng Silero dùng lại đầu ra đó.
VAD_FRONTENDS = {
    "off": ("off", {}),
    "wns": ("wns", {}),
    "wns_agc": ("wns_agc", {}),
    "gtcrn": ("gtcrn", {}),
    "gtcrn_g6": ("gtcrn", {"gain_db": 6}),
    "gtcrn_g12": ("gtcrn", {"gain_db": 12}),
    "gtcrn_t04": ("gtcrn", {"threshold": 0.4}),
    "off_t06": ("off", {"threshold": 0.6}),
    "dpdf": ("dpdf", {}),
    # Nền nhiễu trắng cộng sau khi khử nhiễu (VadFrontend floor_dbfs): Silero không nghe im lặng số.
    "gtcrn_f80": ("gtcrn", {"floor_dbfs": -80}),
    "gtcrn_f70": ("gtcrn", {"floor_dbfs": -70}),
    "gtcrn_f60": ("gtcrn", {"floor_dbfs": -60}),
    "gtcrn_f70_g6": ("gtcrn", {"floor_dbfs": -70, "gain_db": 6}),
    "gtcrn_f70_t06": ("gtcrn", {"floor_dbfs": -70, "threshold": 0.6}),
    "gtcrn_f70_t07": ("gtcrn", {"floor_dbfs": -70, "threshold": 0.7}),
    "gtcrn_f70_t08": ("gtcrn", {"floor_dbfs": -70, "threshold": 0.8}),
    "wns_agc_f70": ("wns_agc", {"floor_dbfs": -70}),
}
_DENOISERS = {
    "off": {"kind": "off"},
    "wns": {"kind": "webrtc"},
    "wns_agc": {"kind": "webrtc", "auto_gain": True},
    "gtcrn": {"kind": "gtcrn", "model_path": str(SE_MODELS / "gtcrn_simple.onnx")},
    "dpdf": {"kind": "dpdfnet", "model_path": str(SE_MODELS / "dpdfnet_baseline.onnx")},
}


def _denoised_chunks(pcm: np.ndarray, key: str) -> tuple[list[bytes], float]:
    """Đầu ra front-end cho từng frame 30 ms (độ dài thay đổi) + giây CPU."""
    frames = [pcm[i : i + FRAME].tobytes() for i in range(0, len(pcm) - FRAME + 1, FRAME)]
    frontend = build_vad_frontend(sample_rate=RATE, **_DENOISERS[key])
    if frontend is None:
        return frames, 0.0
    started = time.process_time()
    out = [frontend.process(frame) for frame in frames]
    return out, time.process_time() - started


def _silero_flags(
    chunks: list[bytes],
    *,
    threshold: float = 0.5,
    gain_db: float = 0.0,
    floor_dbfs: float | None = None,
) -> np.ndarray:
    """Như `VadFrontend.process` sau bộ khử nhiễu: tăng `gain_db`, cộng nền `floor_dbfs`."""
    vad = SileroVadClassifier(SILERO, sample_rate=RATE, threshold=threshold, min_silence_ms=500)
    factor = 10 ** (gain_db / 20)
    sigma = 32768 * 10 ** (floor_dbfs / 20) if floor_dbfs is not None else 0.0
    rng = np.random.default_rng(0)
    flags = []
    for chunk in chunks:
        if (gain_db or sigma) and chunk:
            x = np.frombuffer(chunk, dtype=np.int16).astype(np.float64) * factor
            if sigma:
                x += rng.normal(0.0, sigma, x.size)
            chunk = np.clip(np.round(x), -32768, 32767).astype(np.int16).tobytes()
        flags.append(bool(chunk) and vad.is_speech(chunk))
    return np.array(flags, dtype=bool)


def _runs(flags: np.ndarray, min_len: int) -> list[tuple[int, int]]:
    runs, start = [], None
    for i, flag in enumerate([*flags, False]):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if i - start >= min_len:
                runs.append((start, i))
            start = None
    return runs


def _vad_trial(task: tuple) -> dict:
    kind, dataset, case_index, condition, channel, seed, noise_rms = task
    spec = parse_condition(condition)
    rng = np.random.default_rng(seed)
    if kind == "speech":
        speech = _STATE["cases"][dataset][case_index]["speech"]
        pcm = build_trial(speech, spec, _STATE["noises"], rng, channel=channel)
        first, last, _ = active_frames(speech, spec)
    else:
        pcm = build_trial(
            None, spec, _STATE["noises"], rng, channel=channel, noise_rms_target=noise_rms
        )
    chunks_by_key, cpu = {}, {}
    out = {"kind": kind, "dataset": dataset, "condition": condition, "frontends": {}}
    for name, (key, params) in _STATE["frontends"].items():
        if key not in chunks_by_key:
            chunks_by_key[key], cpu[key] = _denoised_chunks(pcm, key)
        flags = _silero_flags(chunks_by_key[key], **params)
        min_run = 8  # 240 ms ~ turn_min_speech_ms
        if kind == "speech":
            lo, hi = max(0, first - 10), min(len(flags), last + 20)
            window = flags[lo:hi]
            runs = _runs(window, min_run)
            covered = flags[first : last + 1]
            onset = next((i for i in range(lo, hi) if flags[i]), None)
            # Nhả cuối câu: frame đầu tiên sau câu mà Silero đã tắt (hangover 500 ms đã gồm).
            release = next((i for i in range(last + 1, len(flags)) if not flags[i]), len(flags))
            out["frontends"][name] = {
                "recall": float(covered.mean()) if covered.size else 0.0,
                "detected": bool(runs),
                "onset_ms": None if onset is None else (onset - first) * 30,
                "release_ms": (release - last) * 30,
                "cpu_ms_per_frame": cpu[key] / max(len(flags), 1) * 1000,
            }
        else:
            runs = _runs(flags, min_run)
            out["frontends"][name] = {
                "fa_frac": float(flags.mean()),
                "fa_runs": len(runs),
                "cpu_ms_per_frame": cpu[key] / max(len(flags), 1) * 1000,
            }
    return out


_STATE: dict = {}


def _pool(workers: int):
    return get_context("fork").Pool(workers)


def run_vad(args) -> None:
    datasets = args.datasets.split(",")
    conditions = args.conditions.split(",")
    frontends = {n: VAD_FRONTENDS[n] for n in args.frontends.split(",")}
    golden = bench.load_golden()
    # web/short đọc từ cache của bench.py (temp/noise-bench/*_set.json), không cần ASR.
    _STATE.update(
        cases={d: load_dataset(d) for d in datasets},
        noises=load_noises(golden),
        frontends=frontends,
    )
    tasks = []
    seed = 1000
    all_speech = [c["speech"] for d in datasets for c in _STATE["cases"][d]]
    median_level = float(np.median([bench._active_rms(s) for s in all_speech]))
    for condition in conditions:
        spec = parse_condition(condition)
        for dataset in datasets:
            for index in range(len(_STATE["cases"][dataset])):
                seed += 1
                tasks.append(("speech", dataset, index, condition, args.channel, seed, None))
        if spec["noise"] is not None:
            noise_rms = median_level / 10 ** (spec["snr"] / 20)
            for _ in range(args.noise_trials):
                seed += 1
                tasks.append(("noise", "-", 0, condition, args.channel, seed, noise_rms))
    started = time.monotonic()
    with _pool(args.workers) as pool:
        results = []
        for done, res in enumerate(pool.imap(_vad_trial, tasks, chunksize=4), 1):
            results.append(res)
            if done % 200 == 0:
                print(f"  {done}/{len(tasks)} trial", flush=True)
    summary: dict = {}
    for res in results:
        for name, metrics in res["frontends"].items():
            key = (
                res["condition"],
                res["dataset"] if res["kind"] == "speech" else "noise_only",
                name,
            )
            summary.setdefault(key, []).append(metrics)
    table = {}
    for (condition, dataset, name), rows in summary.items():
        if dataset == "noise_only":
            agg = {
                "trials": len(rows),
                "fa_frac": round(float(np.mean([r["fa_frac"] for r in rows])), 4),
                "fa_runs": int(sum(r["fa_runs"] for r in rows)),
                "fa_trials": int(sum(r["fa_runs"] > 0 for r in rows)),
            }
        else:
            onsets = [r["onset_ms"] for r in rows if r["onset_ms"] is not None]
            agg = {
                "trials": len(rows),
                "recall": round(float(np.mean([r["recall"] for r in rows])), 4),
                "missed": int(sum(not r["detected"] for r in rows)),
                "onset_p50": float(np.percentile(onsets, 50)) if onsets else None,
                "onset_p90": float(np.percentile(onsets, 90)) if onsets else None,
                "release_p50": float(np.percentile([r["release_ms"] for r in rows], 50)),
                "release_p90": float(np.percentile([r["release_ms"] for r in rows], 90)),
            }
        agg["cpu_ms_per_frame"] = round(float(np.mean([r["cpu_ms_per_frame"] for r in rows])), 3)
        table.setdefault(condition, {}).setdefault(dataset, {})[name] = agg
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"vad_{args.label}.json"
    out.write_text(json.dumps({"args": vars(args), "table": table}, ensure_ascii=False, indent=1))
    print(f"{len(tasks)} trial, {time.monotonic() - started:.0f} s -> {out.relative_to(ROOT)}")
    print_vad(table, list(frontends))


def print_vad(table: dict, names: list[str]) -> None:
    for condition, by_dataset in table.items():
        print(f"\n### {condition}")
        for dataset, by_frontend in sorted(by_dataset.items()):
            cells = []
            for name in names:
                m = by_frontend.get(name)
                if m is None:
                    continue
                if dataset == "noise_only":
                    cells.append(
                        f"{name}: fa {m['fa_frac']:.3f} runs {m['fa_runs']} ({m['fa_trials']}/{m['trials']})"
                    )
                else:
                    cells.append(
                        f"{name}: rec {m['recall']:.3f} miss {m['missed']}/{m['trials']} "
                        f"on {m['onset_p50']:.0f}/{m['onset_p90']:.0f} rel {m['release_p50']:.0f}/{m['release_p90']:.0f}"
                        if m["onset_p50"] is not None
                        else f"{name}: rec {m['recall']:.3f} miss {m['missed']}/{m['trials']}"
                    )
            print(f"  {dataset:10} " + " | ".join(cells))


# ------------------------------------------------------------------ chế độ pipeline


def _settings(overrides: dict, channel: str):
    from speech.settings import SpeechSettings

    settings = SpeechSettings(**{**bench.PROFILES["production"], **overrides})
    if channel == "phone":
        # Như worker với participant SIP; khoá --set vẫn thắng phone_overrides.
        merged = {**settings.model_dump(), **settings.phone_overrides, **overrides}
        settings = SpeechSettings.model_validate(merged)
    return settings


def _pipeline_worker_init(overrides: dict, channel: str) -> None:
    from inference.asr import create_asr_gateway
    from speech.asr.recognizer import SpeechRecognizer

    settings = _settings(overrides, channel)
    _STATE["settings"] = settings
    _STATE["asr"] = SpeechRecognizer(create_asr_gateway(settings.asr_provider))


def _pipeline_trial(task: tuple) -> dict:
    kind, dataset, case_index, condition, channel, seed, noise_rms = task
    spec = parse_condition(condition)
    rng = np.random.default_rng(seed)
    settings, asr = _STATE["settings"], _STATE["asr"]
    started = time.process_time()
    if kind == "speech":
        case = _STATE["cases"][dataset][case_index]
        pcm = build_trial(case["speech"], spec, _STATE["noises"], rng, channel=channel)
    else:
        pcm = build_trial(
            None, spec, _STATE["noises"], rng, channel=channel, noise_rms_target=noise_rms
        )
    out = asyncio.run(bench.run_pipeline(pcm, settings, asr))
    row = {
        "kind": kind,
        "dataset": dataset,
        "condition": condition,
        "finals": out["finals"],
        "turns": out["turns"],
        "turn_times": out["turn_times"],
        "cpu_s": round(time.process_time() - started, 3),
        "audio_s": round(len(pcm) / RATE, 3),
    }
    if kind == "speech":
        case = _STATE["cases"][dataset][case_index]
        row["id"] = case["id"]
        row["group"] = case.get("group")
        speech_end = bench.LEAD_S + len(case["speech"]) / RATE
        row["latency_s"] = bench._latency(out["turn_times"], speech_end)
        reference = case["reference"] or _STATE["clean_ref"].get((dataset, case_index), "")
        row["reference"] = reference
        row["labelled"] = bool(case["reference"])
        row["turn_errors"], row["words"] = word_errors(reference, " ".join(out["turns"]))
        row["final_errors"], _ = word_errors(reference, " ".join(out["finals"]))
    return row


def _clean_reference(task: tuple) -> tuple:
    dataset, index = task
    from speech.types import AudioSegment

    speech = _STATE["cases"][dataset][index]["speech"]
    pcm = np.clip(np.round(speech), -32768, 32767).astype(np.int16)
    if _STATE["channel"] == "phone":
        pcm = bench.phone_channel(pcm)
    text = _STATE["asr"].transcribe(AudioSegment(pcm=pcm.tobytes(), sample_rate=RATE)).text
    return (dataset, index), text


def run_pipeline_mode(args) -> None:
    datasets = args.datasets.split(",")
    conditions = args.conditions.split(",")
    overrides = dict(item.split("=", 1) for item in args.set)
    golden = bench.load_golden()
    # Process cha không dựng ASR: onnxruntime đang chạy luồng thì fork không an toàn; mỗi worker
    # tự dựng trong `_pipeline_worker_init`.
    _STATE.update(
        settings=_settings(overrides, args.channel),
        cases={d: load_dataset(d) for d in datasets},
        noises=load_noises(golden),
        channel=args.channel,
        clean_ref={},
    )
    print("settings:", {k: getattr(_STATE["settings"], k) for k in sorted(overrides)}, flush=True)
    started = time.monotonic()
    unlabelled = [
        (d, i) for d in datasets for i, c in enumerate(_STATE["cases"][d]) if not c["reference"]
    ]
    with get_context("fork").Pool(
        args.workers, _pipeline_worker_init, (overrides, args.channel)
    ) as pool:
        if unlabelled:
            _STATE["clean_ref"] = dict(pool.map(_clean_reference, unlabelled))
    tasks = []
    seed = 1000
    all_speech = [c["speech"] for d in datasets for c in _STATE["cases"][d]]
    median_level = float(np.median([bench._active_rms(s) for s in all_speech]))
    for condition in conditions:
        spec = parse_condition(condition)
        for dataset in datasets:
            if args.noise_only:
                break
            for index in range(len(_STATE["cases"][dataset])):
                seed += 1
                tasks.append(("speech", dataset, index, condition, args.channel, seed, None))
        if spec["noise"] is not None and args.noise_trials:
            noise_rms = median_level / 10 ** (spec["snr"] / 20)
            for _ in range(args.noise_trials):
                seed += 1
                tasks.append(("noise", "-", 0, condition, args.channel, seed, noise_rms))
    with get_context("fork").Pool(
        args.workers, _pipeline_worker_init, (overrides, args.channel)
    ) as pool:
        rows = []
        partial = OUT_DIR / f"pipe_{args.label}.partial.jsonl"
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        # Ghi dần từng trial: chạy lâu trên máy tải nặng, bị dừng giữa chừng vẫn còn số đo.
        with open(partial, "w", encoding="utf-8") as handle:
            for done, row in enumerate(pool.imap(_pipeline_trial, tasks, chunksize=2), 1):
                rows.append(row)
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                if done % 100 == 0:
                    print(f"  {done}/{len(tasks)} trial", flush=True)
    result = {
        "label": args.label,
        "channel": args.channel,
        "overrides": overrides,
        "datasets": datasets,
        "conditions": conditions,
        "rows": rows,
        "summary": summarize(rows),
        "seconds": round(time.monotonic() - started, 1),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"pipe_{args.label}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(f"{len(tasks)} trial, {result['seconds']:.0f} s -> {out.relative_to(ROOT)}")
    print_summary(result["summary"])


def summarize(rows: list[dict]) -> dict:
    summary: dict = {}
    groups: dict = {}
    for row in rows:
        key = (row["condition"], row["dataset"] if row["kind"] == "speech" else "noise_only")
        groups.setdefault(key, []).append(row)
        if row["kind"] == "speech" and row["labelled"]:
            # ALL: chỉ câu có nhãn người (web/short so với decode câu sạch, không gộp).
            groups.setdefault((row["condition"], "ALL"), []).append(row)
    for (condition, dataset), items in groups.items():
        if dataset == "noise_only":
            agg = {
                "trials": len(items),
                "false_turns": sum(bool(r["turns"]) for r in items),
                "false_finals": sum(bool(r["finals"]) for r in items),
                "false_texts": [" / ".join(r["turns"]) for r in items if r["turns"]],
            }
        else:
            for r in items:
                # Chấm lại từ chữ đã lưu: kết quả cũ theo cách chuẩn hoá hiện tại.
                r["turn_errors"], r["words"] = word_errors(r["reference"], " ".join(r["turns"]))
                r["final_errors"], _ = word_errors(r["reference"], " ".join(r["finals"]))
            words = sum(r["words"] for r in items)
            latencies = [r["latency_s"] for r in items if r["latency_s"] is not None]
            agg = {
                "trials": len(items),
                "wer_turn": round(sum(r["turn_errors"] for r in items) / max(words, 1), 4),
                "wer_final": round(sum(r["final_errors"] for r in items) / max(words, 1), 4),
                "no_turn": sum(not r["turns"] for r in items),
                "split": sum(len(r["turns"]) > 1 for r in items),
                "lat_p50": round(float(np.percentile(latencies, 50)), 3) if latencies else None,
                "lat_p90": round(float(np.percentile(latencies, 90)), 3) if latencies else None,
                "rtf": round(
                    sum(r["cpu_s"] for r in items) / max(sum(r["audio_s"] for r in items), 1e-9), 4
                ),
            }
        summary.setdefault(condition, {})[dataset] = agg
    return summary


def print_summary(summary: dict) -> None:
    for condition, by_dataset in summary.items():
        print(f"\n### {condition}")
        for dataset, m in sorted(by_dataset.items()):
            if dataset == "noise_only":
                print(
                    f"  {dataset:12} false_turns {m['false_turns']}/{m['trials']} {m['false_texts'][:4]}"
                )
            else:
                print(
                    f"  {dataset:12} wer_turn {m['wer_turn']:.3f} wer_final {m['wer_final']:.3f} "
                    f"no_turn {m['no_turn']}/{m['trials']} split {m['split']} lat {m['lat_p50']}/{m['lat_p90']} rtf {m['rtf']}"
                )


def _load_results(labels: list[str]) -> list[dict]:
    loaded = [json.loads((OUT_DIR / f"pipe_{label}.json").read_text()) for label in labels]
    for result in loaded:
        result["summary"] = summarize(result["rows"])
    return loaded


def compare(labels: list[str]) -> None:
    loaded = _load_results(labels)
    conditions = loaded[0]["conditions"]
    datasets = [*loaded[0]["datasets"], "ALL"]
    for metric in ("wer_turn", "no_turn", "lat_p50", "lat_p90", "false_turns"):
        print(f"\n## {metric}")
        print(f"{'điều kiện':18} {'bộ':10} " + " ".join(f"{label[:14]:>14}" for label in labels))
        for condition in conditions:
            for dataset in [*datasets, "noise_only"]:
                cells = []
                for result in loaded:
                    m = result["summary"].get(condition, {}).get(dataset)
                    value = None if m is None else m.get(metric)
                    cells.append(
                        f"{'-':>14}"
                        if value is None
                        else f"{value:14.3f}"
                        if isinstance(value, float)
                        else f"{value:>14}"
                    )
                if all(c.strip() == "-" for c in cells):
                    continue
                print(f"{condition:18} {dataset:10} " + " ".join(cells))


def report(labels: list[str], datasets: list[str] | None = None) -> None:
    """Bảng markdown: mỗi điều kiện một dòng, mỗi cấu hình một cột "WER · mất lượt · trễ p50/p90",
    cột cuối là lượt giả trên đoạn chỉ có nhiễu."""
    loaded = _load_results(labels)
    conditions = loaded[0]["conditions"]
    for dataset in datasets or ["ALL", *loaded[0]["datasets"]]:
        print(f"\n**{dataset}** (ô: WER lượt · câu không thành lượt · trễ chốt lượt p50/p90 s)\n")
        print("| Điều kiện | " + " | ".join(labels) + " | Lượt giả (đoạn chỉ nhiễu) |")
        print("|---|" + "---|" * (len(labels) + 1))
        for condition in conditions:
            cells = []
            for result in loaded:
                m = result["summary"].get(condition, {}).get(dataset)
                if m is None:
                    cells.append("-")
                    continue
                cells.append(
                    f"{m['wer_turn']:.3f} · {m['no_turn']}/{m['trials']} · "
                    f"{m['lat_p50'] if m['lat_p50'] is not None else '-'}/{m['lat_p90'] if m['lat_p90'] is not None else '-'}"
                )
            false_cells = []
            for result in loaded:
                m = result["summary"].get(condition, {}).get("noise_only")
                false_cells.append("-" if m is None else f"{m['false_turns']}/{m['trials']}")
            print(f"| {condition} | " + " | ".join(cells) + " | " + " → ".join(false_cells) + " |")


def paired(base: str, other: str, *, rounds: int = 2000, seed: int = 0) -> None:
    """So từng cặp trial cùng seed (cùng câu, cùng đoạn nhiễu): ΔWER lượt (other − base) với KTC
    95% bootstrap theo câu, số câu tốt hơn / tệ hơn, câu không thành lượt; đoạn chỉ nhiễu: lượt giả
    và số đoạn chỉ một bên có lượt giả. Hai lần chạy phải cùng --datasets/--conditions/--noise-trials
    (pool.imap giữ thứ tự trial nên đoạn nhiễu ghép theo thứ tự)."""
    a, b = _load_results([base, other])
    rng = np.random.default_rng(seed)

    def speech(result: dict) -> dict:
        return {
            (r["condition"], r["dataset"], r["id"]): r
            for r in result["rows"]
            if r["kind"] == "speech" and r["labelled"]
        }

    def noise(result: dict) -> dict:
        out: dict = {}
        for r in result["rows"]:
            if r["kind"] == "noise":
                out.setdefault(r["condition"], []).append(bool(r["turns"]))
        return out

    sa, sb = speech(a), speech(b)
    na, nb = noise(a), noise(b)
    print(f"\n{other} so với {base} (ô ΔWER: âm = {other} tốt hơn)\n")
    print(
        "| Điều kiện | WER | ΔWER [KTC 95%] | câu tốt hơn / tệ hơn | không thành lượt | lượt giả (chỉ nhiễu) |"
    )
    print("|---|---|---|---|---|---|")
    pooled: list[tuple[int, int, int]] = []
    for condition in [*a["conditions"], None]:
        if condition is None:
            pairs = pooled
            name = "**tất cả**"
        else:
            keys = sorted(k for k in sa if k[0] == condition and k in sb)
            pairs = [(sa[k]["turn_errors"], sb[k]["turn_errors"], sa[k]["words"]) for k in keys]
            pooled.extend(pairs)
            name = condition
        # Chỉ điều kiện có ở cả hai lần chạy (lần chạy ngắn hơn so được trên phần chung).
        noise_conditions = [
            c for c in (list(na) if condition is None else [condition]) if c in na and c in nb
        ]
        noise_pairs = [
            pair for c in noise_conditions for pair in zip(na[c], nb.get(c, []), strict=True)
        ]
        if not pairs and not noise_pairs:
            continue
        speech_cells = "- | - | - | -"
        if pairs:
            arr = np.array(pairs, dtype=np.float64)
            words = arr[:, 2].sum()
            delta = (arr[:, 1].sum() - arr[:, 0].sum()) / words
            idx = rng.integers(0, len(arr), (rounds, len(arr)))
            boot = (arr[idx, 1].sum(1) - arr[idx, 0].sum(1)) / arr[idx, 2].sum(1)
            low, high = np.percentile(boot, [2.5, 97.5])
            better = int((arr[:, 1] < arr[:, 0]).sum())
            worse = int((arr[:, 1] > arr[:, 0]).sum())
            used = [k for k in sa if k in sb] if condition is None else keys
            no_a = sum(not sa[k]["turns"] for k in used)
            no_b = sum(not sb[k]["turns"] for k in used)
            speech_cells = (
                f"{arr[:, 0].sum() / words:.3f} → {arr[:, 1].sum() / words:.3f} | "
                f"{delta:+.3f} [{low:+.3f}; {high:+.3f}] | {better} / {worse} | "
                f"{no_a} → {no_b} /{len(arr)}"
            )
        false_cell = "-"
        if noise_pairs:
            fa, fb = sum(x for x, _ in noise_pairs), sum(y for _, y in noise_pairs)
            only_a = sum(x and not y for x, y in noise_pairs)
            only_b = sum(y and not x for x, y in noise_pairs)
            false_cell = (
                f"{fa} → {fb} /{len(noise_pairs)} (chỉ {base}: {only_a}, chỉ {other}: {only_b})"
            )
        print(f"| {name} | {speech_cells} | {false_cell} |")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="mode", required=True)
    vad = sub.add_parser("vad")
    vad.add_argument("--label", required=True)
    vad.add_argument("--datasets", default="golden,pm,vietmed4,web")
    vad.add_argument(
        "--conditions", default="clean,clean~q25,office@8,office@3,cafe@5,cafe@0,street@5,traffic@5"
    )
    vad.add_argument("--channel", choices=("web", "phone"), default="web")
    vad.add_argument("--frontends", default=",".join(VAD_FRONTENDS))
    vad.add_argument("--noise-trials", type=int, default=NOISE_TRIALS)
    vad.add_argument("--workers", type=int, default=3)
    pipe = sub.add_parser("pipeline")
    pipe.add_argument("--label", required=True)
    pipe.add_argument("--datasets", default="golden,pm,vietmed6")
    pipe.add_argument("--conditions", default="clean,office@8,cafe@5,street@5")
    pipe.add_argument("--channel", choices=("web", "phone"), default="web")
    pipe.add_argument("--set", action="append", default=[], metavar="KHOÁ=GIÁ_TRỊ")
    pipe.add_argument("--noise-trials", type=int, default=NOISE_TRIALS)
    pipe.add_argument(
        "--noise-only", action="store_true", help="chỉ đoạn chỉ có nhiễu (đếm lượt giả), bỏ câu"
    )
    pipe.add_argument("--workers", type=int, default=3)
    cmp_parser = sub.add_parser("compare")
    cmp_parser.add_argument("labels", nargs="+")
    report_parser = sub.add_parser("report")
    report_parser.add_argument("labels", nargs="+")
    report_parser.add_argument("--datasets")
    paired_parser = sub.add_parser("paired")
    paired_parser.add_argument("base")
    paired_parser.add_argument("other")
    args = parser.parse_args()
    if args.mode == "vad":
        run_vad(args)
    elif args.mode == "pipeline":
        run_pipeline_mode(args)
    elif args.mode == "report":
        report(args.labels, args.datasets.split(",") if args.datasets else None)
    elif args.mode == "paired":
        paired(args.base, args.other)
    else:
        compare(args.labels)


if __name__ == "__main__":
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    main()
