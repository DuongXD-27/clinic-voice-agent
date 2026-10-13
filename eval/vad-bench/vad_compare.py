"""So sánh các VAD trên tiếng Việt, nhiều môi trường âm thanh — cùng dữ liệu, cùng hậu xử lý.

Mỗi model chỉ cho XÁC SUẤT tiếng nói theo cửa sổ của nó; mọi model đi qua CÙNG một bộ làm mượt
(`smooth`, đúng logic `SileroVadModel::IsSpeech` của sherpa-onnx mà production dùng: bắt đầu khi
xác suất > ngưỡng liên tục `min_speech` 250 ms, giữ khi > ngưỡng − 0,15, nhả sau `min_silence`
500 ms dưới ngưỡng). So sánh vì vậy là so MODEL, không lẫn cách hậu xử lý của từng thư viện.

Model (`--models`):
- `silero_v4`: đang chạy production (src/speech/asr/vad/assets/silero_vad.onnx, bản k2-fsa).
- `silero_v5`, `silero_v6`: ONNX chính thức snakers4/silero-vad v5.1.2 / v6.2.3 (ghép 64 mẫu ngữ
  cảnh trước mỗi cửa sổ như `OnnxWrapper` của họ).
- `ten`: TEN VAD (thư viện dựng sẵn của repo TEN-framework/ten-vad, hop 256 mẫu).
- `firered`: FireRedVAD Stream-VAD (DFSMN nhân quả, hop 10 ms; nạp `weights_only=True`).
- `webrtc0`..`webrtc3`: WebRTC VAD (nhị phân, khung 30 ms).
- `gtcrn_v4`: Silero v4 nghe bản khử nhiễu GTCRN + nền −70 dBFS (speech/audio/vad_frontend.py).

Dữ liệu:
- Giọng Việt sạch có nhãn khung 10 ms: VIVOS test (đọc, 16 kHz, nhiều người) + PM (31 câu thoại
  callbot thu thật). Nhãn = khung trong 40 dB so với khung to nhất của câu (audio sạch, trước khi
  trộn), lấp khoảng lặng < 150 ms giữa từ, bỏ cụm < 50 ms.
- Mỗi "luồng" = 3 câu nối nhau, nghỉ 0,6–2,5 s giữa câu, đệm 1–2 s đầu / 2 s cuối, nhiễu trộn liên
  tục cả luồng ở SNR tính trên đoạn có giọng.
- Nhiễu: văn phòng thật (dump LiveKit), DEMAND (căng tin, giao thông, hành lang, phòng khách, xe
  buýt, nhà ga, quảng trường, bếp, phòng họp, công viên), đường phố Việt Nam, ESC-50 (ho, hắt hơi,
  thở, cười, trẻ khóc, gõ cửa, gõ phím, còi xe…) ghép thành chuỗi âm thanh rời rạc, TV / nhiều người
  nói (nền là giọng người — báo riêng).
- Đoạn chỉ có nhiễu (người gọi im lặng) để đếm lần kích hoạt nhầm.
- `--tenset`: 30 file có nhãn tay khung của TEN VAD testset (LibriSpeech, GigaSpeech, DNS Challenge).

Chỉ số:
- AUC (khung 10 ms, xác suất thô — không phụ thuộc ngưỡng).
- Sau làm mượt ở ngưỡng θ: câu bị bỏ sót (phủ < 50% khung có giọng), trễ nhận ra đầu câu, trễ nhả
  cuối câu, câu bị cắt vụn (> 1 đoạn), khoảng nghỉ ≥ 1,3 s bị nối liền, kích hoạt nhầm mỗi phút
  (đoạn cờ bắt đầu ngoài mọi câu, collar 0,3 s trước / 0,8 s sau).
- θ = 0,5 (mặc định) VÀ θ* hiệu chỉnh theo cùng mức kích hoạt nhầm trên nửa A dữ liệu, đánh giá trên
  nửa B — so ở cùng mức báo nhầm, không thiên vị ngưỡng mặc định của từng model.

    python eval/vad-bench/vad_compare.py run --label full1 --vivos 240 --noise-streams 10 --tenset \\
        --models silero_v4,silero_v5,silero_v6,sherpa_v6,ten,firered,webrtc1,webrtc3,gtcrn_v4 \\
        --workers 11 --libcxx <thư mục có libc++.so.1>
    python eval/vad-bench/vad_compare.py report --label full1

Chạy bằng Python có torch + kaldi_native_fbank + kaldiio (FireRedVAD). Mã ngoài giải nén vào
temp/aq/ext/ (ten-vad-src/ten-vad-main, firered-src/FireRedVAD-main, firered_model/Stream-VAD), ONNX
Silero v5.1.2 / v6.2.3 vào temp/aq/models/silero_v512, silero_v623; TEN VAD cần libc++ (`--libcxx`
hoặc TEN_LIBCXX). Kết quả: temp/aq/vad/<label>.pkl (không commit).
"""

from __future__ import annotations

import argparse
import ctypes
import io
import json
import math
import os
import pickle
import sys
import time
from multiprocessing import get_context
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval" / "noise-bench"))

RATE = 16_000
GRID = 160  # 10 ms
OUT = ROOT / "temp" / "aq" / "vad"
EXT = ROOT / "temp" / "aq" / "ext"
MODELS_DIR = ROOT / "temp" / "aq" / "models"
DATA = ROOT / "temp" / "aq" / "data"

# ============================================================== model: xác suất theo cửa sổ


class _Model:
    name = ""

    def probs(self, audio: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(thời điểm cuối cửa sổ (s), xác suất) — chạy tuần tự như streaming, trạng thái mới."""
        raise NotImplementedError


class SileroV4(_Model):
    def __init__(self, path: str) -> None:
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(path, options, providers=["CPUExecutionProvider"])

    def probs(self, audio):
        x = audio.astype(np.float32) / 32768.0
        h = np.zeros((2, 1, 64), np.float32)
        c = np.zeros((2, 1, 64), np.float32)
        out = []
        for start in range(0, len(x) - 511, 512):
            p, h, c = self._session.run(None, {"x": x[None, start : start + 512], "h": h, "c": c})
            out.append(float(p[0, 0]))
        return (np.arange(1, len(out) + 1) * 512) / RATE, np.array(out)


class SileroV5(_Model):
    """v5 / v6: ghép 64 mẫu cuối của cửa sổ trước (như OnnxWrapper chính thức); `context=False` =
    chỉ đưa 512 mẫu (để kiểm cách sherpa-onnx chạy cùng model)."""

    def __init__(self, path: str, *, context: bool = True) -> None:
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(path, options, providers=["CPUExecutionProvider"])
        self._context = context

    def probs(self, audio):
        x = audio.astype(np.float32) / 32768.0
        state = np.zeros((2, 1, 128), np.float32)
        context = np.zeros(64, np.float32)
        sr = np.array(RATE, dtype=np.int64)
        out = []
        for start in range(0, len(x) - 511, 512):
            chunk = x[start : start + 512]
            window = np.concatenate([context, chunk]) if self._context else chunk
            p, state = self._session.run(None, {"input": window[None], "state": state, "sr": sr})
            context = window[-64:]
            out.append(float(p[0, 0]))
        return (np.arange(1, len(out) + 1) * 512) / RATE, np.array(out)


class SherpaSilero(_Model):
    """Đúng đường production: `SileroVadClassifier` (sherpa-onnx VoiceActivityDetector) trên frame 30 ms
    — cờ đã làm mượt bên trong sherpa (θ = 0,5, nhả sau 500 ms), không qua `smooth`."""

    presmoothed = True

    def __init__(self, path: str) -> None:
        self._path = path

    def probs(self, audio):
        from speech.asr.vad.silero import SileroVadClassifier

        vad = SileroVadClassifier(self._path, sample_rate=RATE, min_silence_ms=500)
        x = audio.astype(np.int16)
        out = [float(vad.is_speech(x[i : i + 480].tobytes())) for i in range(0, len(x) - 479, 480)]
        return (np.arange(1, len(out) + 1) * 480) / RATE, np.array(out)


class TenVadModel(_Model):
    def __init__(self, libcxx: str) -> None:
        ctypes.CDLL(f"{libcxx}/libc++abi.so.1", mode=ctypes.RTLD_GLOBAL)
        ctypes.CDLL(f"{libcxx}/libc++.so.1", mode=ctypes.RTLD_GLOBAL)
        sys.path.insert(0, str(EXT / "ten-vad-src" / "ten-vad-main" / "include"))
        from ten_vad import TenVad

        self._cls = TenVad

    def probs(self, audio):
        vad = self._cls(hop_size=256, threshold=0.5)
        x = audio.astype(np.int16)
        out = [float(vad.process(x[i : i + 256])[0]) for i in range(0, len(x) - 255, 256)]
        del vad
        return (np.arange(1, len(out) + 1) * 256) / RATE, np.array(out)


class FireRedStream(_Model):
    """Stream-VAD: fbank 25/10 ms + CMVN, DFSMN nhân quả (N2=0) — forward cả luồng = streaming."""

    def __init__(self) -> None:
        import argparse as _argparse

        import torch

        torch.set_num_threads(1)
        sys.path.insert(0, str(EXT / "firered-src" / "FireRedVAD-main"))
        from fireredvad.core.audio_feat import AudioFeat
        from fireredvad.core.detect_model import DetectModel

        model_dir = EXT / "firered_model" / "Stream-VAD"
        torch.serialization.add_safe_globals([_argparse.Namespace])
        package = torch.load(model_dir / "model.pth.tar", map_location="cpu", weights_only=True)
        self._model = DetectModel(package["args"])
        self._model.load_state_dict(package["model_state_dict"], strict=True)
        self._model.eval()
        self._feat = AudioFeat(str(model_dir / "cmvn.ark"))
        self._torch = torch

    def probs(self, audio):
        feats, _ = self._feat.extract(audio.astype(np.int16))
        with self._torch.no_grad():
            p, _ = self._model.forward(feats.unsqueeze(0))
        p = p.squeeze().numpy().reshape(-1)
        return (np.arange(len(p)) * 160 + 400) / RATE, p.astype(np.float64)


class WebRtc(_Model):
    def __init__(self, mode: int) -> None:
        import webrtcvad

        self._mode = mode
        self._mod = webrtcvad

    def probs(self, audio):
        vad = self._mod.Vad(self._mode)
        x = audio.astype(np.int16)
        out = [
            float(vad.is_speech(x[i : i + 480].tobytes(), RATE))
            for i in range(0, len(x) - 479, 480)
        ]
        return (np.arange(1, len(out) + 1) * 480) / RATE, np.array(out)


class GtcrnSilero(_Model):
    """Silero v4 nghe bản GTCRN + nền −70 dBFS — đúng `vad_frontend: gtcrn` (replace)."""

    def __init__(self, silero_path: str) -> None:
        self._silero = SileroV4(silero_path)

    def probs(self, audio):
        from speech.audio.vad_frontend import build_vad_frontend

        frontend = build_vad_frontend(
            "gtcrn",
            sample_rate=RATE,
            model_path=str(ROOT / "src/speech/asr/vad/assets/gtcrn_simple.onnx"),
            floor_dbfs=-70.0,
        )
        pieces = [
            np.frombuffer(frontend.process(audio[i : i + 480].astype(np.int16).tobytes()), np.int16)
            for i in range(0, len(audio) - 479, 480)
        ]
        cleaned = np.concatenate(pieces) if pieces else np.zeros(0, np.int16)
        # GTCRN nhả mẫu ngay, độ dài gần bằng đầu vào: thời điểm giữ nguyên.
        return self._silero.probs(cleaned)


def build_models(names: list[str], libcxx: str) -> dict[str, _Model]:
    silero_v4 = str(ROOT / "src/speech/asr/vad/assets/silero_vad.onnx")
    out: dict[str, _Model] = {}
    for name in names:
        if name == "silero_v4":
            out[name] = SileroV4(silero_v4)
        elif name == "silero_v5":
            out[name] = SileroV5(str(MODELS_DIR / "silero_v512" / "silero_vad.onnx"))
        elif name == "silero_v6":
            out[name] = SileroV5(str(MODELS_DIR / "silero_v623" / "silero_vad.onnx"))
        elif name == "ten":
            out[name] = TenVadModel(libcxx)
        elif name == "firered":
            out[name] = FireRedStream()
        elif name.startswith("webrtc"):
            out[name] = WebRtc(int(name[-1]))
        elif name == "gtcrn_v4":
            out[name] = GtcrnSilero(silero_v4)
        elif name == "sherpa_v6":
            out[name] = SherpaSilero(str(MODELS_DIR / "silero_v623" / "silero_vad.onnx"))
        elif name == "sherpa_v5":
            out[name] = SherpaSilero(str(MODELS_DIR / "silero_v512" / "silero_vad.onnx"))
        else:
            raise ValueError(name)
    return out


# ============================================================== làm mượt (chung mọi model)


def smooth(
    times: np.ndarray,
    probs: np.ndarray,
    threshold: float,
    *,
    min_speech_s: float = 0.25,
    min_silence_s: float = 0.5,
) -> np.ndarray:
    """Cờ "đang nói" theo từng cửa sổ — logic `SileroVadModel::IsSpeech` (sherpa-onnx)."""
    flags = np.zeros(len(probs), dtype=bool)
    triggered = False
    temp_start = temp_end = None
    for i, (t, p) in enumerate(zip(times, probs, strict=True)):
        if p > threshold and temp_end is not None:
            temp_end = None
        if not triggered:
            if p > threshold:
                if temp_start is None:
                    temp_start = t
                if t - temp_start >= min_speech_s:
                    triggered = True
                    flags[i] = True
            else:
                temp_start = None
            continue
        if p > threshold - 0.15:
            # Giữ "đang nói" nhưng KHÔNG xoá mốc bắt đầu im (chỉ xoá khi > threshold, dòng đầu vòng
            # lặp) — đúng như sherpa; xoá ở đây làm nhả cuối câu muộn hơn production.
            flags[i] = True
            continue
        if temp_end is None:
            temp_end = t
        if t - temp_end < min_silence_s:
            flags[i] = True
        else:
            triggered = False
            temp_start = temp_end = None
    return flags


def to_grid(times: np.ndarray, values: np.ndarray, n_cells: int) -> np.ndarray:
    """Giá trị đang có ở cuối mỗi ô 10 ms (cửa sổ gần nhất đã xong) — nhân quả như streaming."""
    cell_end = (np.arange(n_cells) + 1) * GRID / RATE
    idx = np.searchsorted(times, cell_end + 1e-9, side="right") - 1
    out = np.zeros(n_cells, dtype=np.float64)
    ok = idx >= 0
    out[ok] = values[idx[ok]]
    return out


# ============================================================== dữ liệu


def speech_labels(clean: np.ndarray) -> np.ndarray:
    """Nhãn tiếng nói theo ô 10 ms trên câu SẠCH: trong 40 dB so với ô to nhất, lấp lặng < 150 ms,
    bỏ cụm < 50 ms."""
    n = len(clean) // GRID
    if n == 0:
        return np.zeros(0, dtype=bool)
    frames = clean[: n * GRID].astype(np.float64).reshape(n, GRID)
    rms = np.sqrt(np.mean(frames**2, axis=1))
    peak = rms.max()
    floor = max(np.percentile(rms, 10) * 3.0, 3.0)
    lab = (rms >= peak * 10 ** (-40 / 20)) & (rms >= floor)
    # lấp khoảng lặng ngắn giữa từ
    idx = np.nonzero(lab)[0]
    for a, b in zip(idx[:-1], idx[1:], strict=True):
        if 1 < b - a <= 15:
            lab[a:b] = True
    # bỏ cụm quá ngắn
    out = lab.copy()
    i = 0
    while i < n:
        if lab[i]:
            j = i
            while j < n and lab[j]:
                j += 1
            if j - i < 5:
                out[i:j] = False
            i = j
        else:
            i += 1
    return out


def _decode(raw: bytes) -> np.ndarray:
    import soundfile as sf

    x, rate = sf.read(io.BytesIO(raw), dtype="int16", always_2d=False)
    if x.ndim > 1:
        x = x.mean(axis=1).astype(np.int16)
    return _resample(x, rate)


def _resample(x: np.ndarray, rate: int) -> np.ndarray:
    if rate == RATE:
        return x.astype(np.int16)
    import soxr

    return soxr.resample(x.astype(np.float32), rate, RATE).astype(np.int16)


def load_utterances(n_vivos: int, seed: int = 11) -> list[dict]:
    import csv

    import pyarrow.parquet as pq

    rng = np.random.default_rng(seed)
    utts = []
    rows = pq.read_table(ROOT / "temp" / "datasets" / "vivos" / "test.parquet").to_pylist()
    by_speaker: dict[str, list[dict]] = {}
    for row in rows:
        by_speaker.setdefault(row["audio"]["path"].split("_")[0], []).append(row)
    speakers = sorted(by_speaker)
    picked = 0
    while picked < n_vivos:
        for speaker in speakers:
            pool = by_speaker[speaker]
            if not pool or picked >= n_vivos:
                continue
            row = pool.pop(int(rng.integers(len(pool))))
            utts.append(
                {"id": f"vivos/{row['audio']['path']}", "pcm": _decode(row["audio"]["bytes"])}
            )
            picked += 1
    base = ROOT / "temp" / "PM_Public_Eval_STT"
    with open(base / "manifest.csv", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["nguon"] == "ghi_that" and row["dieu_kien"] == "sach" and row["cau_chuan"]:
                import soundfile as sf

                x, rate = sf.read(
                    base / "01_audio_goc" / "Ha_Noi" / "S01" / row["file"], dtype="int16"
                )
                utts.append({"id": f"pm/{row['id']}", "pcm": _resample(x, rate)})
    for u in utts:
        u["labels"] = speech_labels(u["pcm"])
    return [u for u in utts if u["labels"].sum() >= 20]


def _wav16(path: Path) -> np.ndarray:
    import soundfile as sf

    x, rate = sf.read(path, dtype="int16", always_2d=False)
    if x.ndim > 1:
        x = x.mean(axis=1).astype(np.int16)
    return _resample(x, rate)


def load_noises() -> dict[str, np.ndarray]:
    """Cùng nguồn nhiễu với eval/noise-bench/frontend_eval.py (văn phòng thật, đường phố, TV,
    DEMAND, ESC-50)."""
    import frontend_eval as fe

    noises = {
        "office": _wav16(ROOT / "temp" / "noise-bench" / "office_noise.wav"),
        "street": _wav16(ROOT / "temp" / "PM_Public_Eval_STT" / "noise" / "duong.wav"),
        "tv": _wav16(ROOT / "temp" / "PM_Public_Eval_STT" / "noise" / "tv.wav"),
    }
    noises.update({k: np.asarray(v) for k, v in fe.load_extra_noises().items()})
    return noises


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if len(x) else 0.0


def _active_rms(x: np.ndarray) -> float:
    n = len(x) // 480
    if n == 0:
        return _rms(x)
    levels = np.sqrt(np.mean(x[: n * 480].astype(np.float64).reshape(n, 480) ** 2, axis=1))
    if levels.max() <= 0:
        return 0.0
    act = levels[levels >= levels.max() * 10 ** (-30 / 20)]
    return float(np.sqrt(np.mean(act**2)))


# Nền là giọng người (TV, căng tin, phòng họp): VAD nào cũng "nghe" — báo riêng, không dùng để
# hiệu chỉnh ngưỡng. ESC-50 là tiếng rời rạc: đo mức trên đoạn có tiếng như nền giọng người.
BACKGROUND_SPEECH = {"tv", "babble", "meeting", "cafe"}
ACTIVE_LEVEL = BACKGROUND_SPEECH | {"esc_human", "esc_house", "esc_street"}


def parse_condition(cond: str) -> dict:
    base, *mods = cond.split("~")
    noise, _, snr = base.partition("@")
    spec = {"noise": None if noise in ("clean", "silence") else noise, "snr": float(snr) if snr else None,
            "quiet": 0.0, "rt60": 0.0, "phone": False, "bns": False}  # fmt: skip
    for m in mods:
        if m.startswith("q"):
            spec["quiet"] = float(m[1:])
        elif m.startswith("rev"):
            spec["rt60"] = float(m[3:]) / 10
        elif m == "phone":
            spec["phone"] = True
        elif m == "bns":
            spec["bns"] = True
    return spec


def build_stream(
    utts: list[dict],
    spec: dict,
    noises: dict,
    rng: np.random.Generator,
    median_level: float,
    seconds: float | None = None,
) -> tuple[np.ndarray, np.ndarray, list]:
    """Luồng: đệm đầu, các câu cách nhau 0,6–2,5 s, đệm cuối; nhãn ô 10 ms; danh sách (đầu, cuối) câu."""
    import frontend_eval as fe

    pieces, labels, spans = [], [], []
    cursor = 0
    lead = int(rng.uniform(1.0, 2.0) * RATE) // GRID * GRID
    if seconds is not None:  # chỉ nhiễu
        total = int(seconds * RATE) // GRID * GRID
        pieces.append(np.zeros(total))
        labels.append(np.zeros(total // GRID, dtype=bool))
    else:
        pieces.append(np.zeros(lead))
        labels.append(np.zeros(lead // GRID, dtype=bool))
        cursor = lead
        for k, u in enumerate(utts):
            x = u["pcm"].astype(np.float64)
            n = len(u["labels"]) * GRID
            x = x[:n]
            if spec["rt60"]:
                level = _active_rms(x)
                x = np.convolve(x, fe.synthetic_rir(spec["rt60"], rng))[:n]
                x *= level / max(_active_rms(x), 1e-6)
            pieces.append(x)
            labels.append(u["labels"])
            idx = np.nonzero(u["labels"])[0]
            spans.append((cursor // GRID + idx[0], cursor // GRID + idx[-1] + 1))
            cursor += n
            gap = (
                int(rng.uniform(0.6, 2.5) * RATE) // GRID * GRID if k < len(utts) - 1 else 2 * RATE
            )
            pieces.append(np.zeros(gap))
            labels.append(np.zeros(gap // GRID, dtype=bool))
            cursor += gap
    mix = np.concatenate(pieces)
    lab = np.concatenate(labels)
    speech_level = (
        median_level
        if seconds is not None
        else max(_active_rms(np.concatenate([u["pcm"].astype(np.float64) for u in utts])), 1.0)
    )
    if spec["noise"] is None:
        mix += rng.normal(0.0, 1.0, len(mix))
    else:
        noise = noises[spec["noise"]]
        if len(noise) < len(mix) + 1:
            noise = np.tile(noise, int(math.ceil((len(mix) + 1) / len(noise))) + 1)
        start = int(rng.integers(0, len(noise) - len(mix)))
        seg = noise[start : start + len(mix)].astype(np.float64)
        level = max((_active_rms if spec["noise"] in ACTIVE_LEVEL else _rms)(seg), 1e-6)
        mix += seg * (speech_level / 10 ** (spec["snr"] / 20) / level)
    if spec["quiet"]:
        mix *= 10 ** (-spec["quiet"] / 20)
    pcm = np.clip(np.round(mix), -32768, 32767).astype(np.int16)
    if spec["bns"]:
        pcm = fe.browser_ns(pcm)
    if spec["phone"]:
        pcm = fe.bench.phone_channel(pcm)
    return pcm, lab[: len(pcm) // GRID], spans


def load_tenset() -> list[dict]:
    base = EXT / "ten-vad-src" / "ten-vad-main" / "testset"
    items = []
    for wav in sorted(base.glob("*.wav")):
        x = _wav16(wav)
        line = (base / (wav.stem + ".scv")).read_text().strip().split(",")
        n = len(x) // GRID
        lab = np.zeros(n, dtype=bool)
        vals = line[1:]
        for i in range(0, len(vals) - 2, 3):
            s, e, v = float(vals[i]), float(vals[i + 1]), int(float(vals[i + 2]))
            if v:
                lab[int(s * 100) : int(e * 100)] = True
        items.append({"id": wav.stem, "pcm": x, "labels": lab})
    return items


# ============================================================== chạy


_STATE: dict = {}


def _init_worker(names: list[str], libcxx: str) -> None:
    os.environ["OMP_NUM_THREADS"] = "1"
    _STATE["models"] = build_models(names, libcxx)


def _run_task(task: dict) -> dict:
    pcm = task["pcm"]
    n = len(task["labels"])
    out = {k: v for k, v in task.items() if k != "pcm"}
    out["probs"], out["cpu"] = {}, {}
    for name, model in _STATE["models"].items():
        t0 = time.process_time()
        times, probs = model.probs(pcm)
        out["cpu"][name] = time.process_time() - t0
        out["probs"][name] = (times.astype(np.float32), probs.astype(np.float32))
    out["seconds"] = len(pcm) / RATE
    out["n"] = n
    return out


DEFAULT_CONDITIONS = (
    "clean,clean~q20,clean~q30,clean~rev6,"
    "office@15,office@5,cafe@10,cafe@5,street@10,street@5,street@0,traffic@10,traffic@5,"
    "hallway@5,bus@5,station@5,square@5,kitchen@5,park@5,living@5,"
    "esc_human@5,esc_house@5,esc_street@5,"
    "street@5~bns,cafe@5~bns,"
    "clean~phone,office@10~phone,street@5~phone,cafe@5~phone,traffic@5~phone,"
    "tv@10,meeting@5"
)
NOISE_ONLY = (
    "silence,office@15,office@5,cafe@5,street@5,traffic@5,hallway@5,bus@5,station@5,square@5,"
    "kitchen@5,park@5,living@5,esc_human@5,esc_house@5,esc_street@5,street@5~bns,cafe@5~bns,"
    "silence~phone,office@10~phone,street@5~phone,cafe@5~phone,traffic@5~phone,"
    "tv@15,tv@10,tv@5,meeting@10,meeting@5,cafe@10"
)


def run(args) -> None:
    names = args.models.split(",")
    utts = load_utterances(args.vivos)
    noises = load_noises()
    median_level = float(np.median([_active_rms(u["pcm"].astype(np.float64)) for u in utts]))
    rng = np.random.default_rng(2026)
    tasks = []
    conditions = [
        c for c in args.conditions.split(",") if parse_condition(c)["noise"] in (None, *noises)
    ]
    for cond in conditions:
        spec = parse_condition(cond)
        order = rng.permutation(len(utts))
        for s in range(0, len(order) - 2, 3):
            group = [utts[i] for i in order[s : s + 3]]
            pcm, lab, spans = build_stream(group, spec, noises, rng, median_level)
            half = "A" if (s // 3) % 2 == 0 else "B"
            tasks.append({"kind": "speech", "cond": cond, "half": half, "ids": [u["id"] for u in group],
                          "pcm": pcm, "labels": lab, "spans": spans})  # fmt: skip
    for cond in args.noise_only.split(","):
        spec = parse_condition(cond)
        if spec["noise"] is not None and spec["noise"] not in noises:
            continue
        if spec["noise"] is None:
            spec["noise"], spec["snr"] = None, None
        for k in range(args.noise_streams):
            pcm, lab, _ = build_stream(
                [],
                {**spec, "snr": spec["snr"] if spec["snr"] is not None else 0},
                noises,
                rng,
                median_level,
                seconds=20.0,
            )
            tasks.append({"kind": "noise", "cond": cond, "half": "A" if k % 2 == 0 else "B", "ids": [],
                          "pcm": pcm, "labels": lab, "spans": []})  # fmt: skip
    if args.tenset:
        for item in load_tenset():
            tasks.append({"kind": "tenset", "cond": "tenset", "half": "B", "ids": [item["id"]],
                          "pcm": item["pcm"], "labels": item["labels"], "spans": []})  # fmt: skip
    print(
        f"{len(tasks)} luồng, {sum(len(t['pcm']) for t in tasks) / RATE / 3600:.1f} giờ audio, "
        f"{len(names)} model",
        flush=True,
    )
    started = time.monotonic()
    results = []
    with get_context("fork").Pool(args.workers, _init_worker, (names, args.libcxx)) as pool:
        for done, res in enumerate(pool.imap_unordered(_run_task, tasks, chunksize=2), 1):
            results.append(res)
            if done % 200 == 0:
                print(f"  {done}/{len(tasks)} ({time.monotonic() - started:.0f} s)", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / f"{args.label}.pkl", "wb") as handle:
        pickle.dump({"models": names, "results": results}, handle)
    print(f"xong {time.monotonic() - started:.0f} s -> {OUT / (args.label + '.pkl')}")


# ============================================================== chấm điểm


def _runs(flags: np.ndarray) -> list[tuple[int, int]]:
    runs, start = [], None
    for i, f in enumerate([*flags, False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            runs.append((start, i))
            start = None
    return runs


PRESMOOTHED = {"sherpa_v5", "sherpa_v6"}


def _flags(times: np.ndarray, probs: np.ndarray, model: str, threshold: float) -> np.ndarray:
    return probs > 0.5 if model in PRESMOOTHED else smooth(times, probs, threshold)


def event_metrics(res: dict, model: str, threshold: float) -> dict:
    times, probs = res["probs"][model]
    n = res["n"]
    flags_w = _flags(times, probs, model, threshold)
    flags = to_grid(times, flags_w.astype(np.float64), n) > 0.5
    runs = _runs(flags)
    m = {"utts": 0, "missed": 0, "onset": [], "release": [], "fragmented": 0, "bridged": 0,
         "pauses": 0, "false_triggers": 0, "nonspeech_s": 0.0}  # fmt: skip
    spans = res["spans"]
    covered = np.zeros(n, dtype=bool)
    for a, b in spans:
        covered[max(0, a - 30) : min(n, b + 80)] = True
    m["nonspeech_s"] = float((~covered).sum()) * GRID / RATE
    for a, _ in runs:
        if not covered[a]:
            m["false_triggers"] += 1
    lab = res["labels"]
    for k, (a, b) in enumerate(spans):
        m["utts"] += 1
        speech = lab[a:b]
        hit = flags[a:b] & speech
        if hit.sum() < 0.5 * speech.sum():
            m["missed"] += 1
        inside = [r for r in runs if r[1] > a and r[0] < b]
        if len(inside) > 1:
            m["fragmented"] += 1
        if inside:
            m["onset"].append((max(inside[0][0], a) - a) * 0.01 if inside[0][0] >= a else 0.0)
            end = inside[-1][1]
            m["release"].append((end - b) * 0.01)
        if k + 1 < len(spans):
            gap = (spans[k + 1][0] - b) * 0.01
            if gap >= 1.3:
                m["pauses"] += 1
                if flags[b : spans[k + 1][0]].all():
                    m["bridged"] += 1
    return m


def auc_parts(res: dict, model: str) -> tuple[np.ndarray, np.ndarray]:
    times, probs = res["probs"][model]
    return to_grid(times, probs.astype(np.float64), res["n"]), res["labels"]


def _fa_fraction(pool: list[dict], model: str, threshold: float) -> float:
    """Tỉ lệ thời gian bị gắn cờ "đang nói" trên đoạn chỉ có nhiễu — không lách được bằng cách bật
    cờ suốt (một đoạn dài vẫn tính đủ thời gian), khác với đếm số lần kích hoạt."""
    flagged = total = 0
    for r in pool:
        flags = _flags(*r["probs"][model], model, threshold)
        flagged += int(flags.sum())
        total += len(flags)
    return flagged / max(total, 1)


def _noise_pool(results: list[dict], half: str) -> list[dict]:
    return [r for r in results if r["kind"] == "noise" and r["half"] == half
            and parse_condition(r["cond"])["noise"] not in BACKGROUND_SPEECH]  # fmt: skip


def _background_pool(results: list[dict], half: str) -> list[dict]:
    return [r for r in results if r["kind"] == "noise" and r["half"] == half
            and parse_condition(r["cond"])["noise"] in BACKGROUND_SPEECH]  # fmt: skip


def calibrate(
    results: list[dict], model: str, target: float, target_bg: float | None = None
) -> float:
    """θ nhạy nhất (lưới 0,05 trong [0,3; 0,95]) có tỉ lệ thời gian báo nhầm trên đoạn chỉ nhiễu
    (nửa A, nền không phải giọng người) <= `target`; có `target_bg` thì thêm điều kiện báo nhầm trên
    nền là giọng người (TV, phòng họp, căng tin) <= `target_bg` — không thêm lượt giả nào so với mốc."""
    pool, bg = _noise_pool(results, "A"), _background_pool(results, "A")
    for th in np.arange(0.30, 0.96, 0.05):
        if _fa_fraction(pool, model, float(th)) > target:
            continue
        if target_bg is not None and _fa_fraction(bg, model, float(th)) > target_bg:
            continue
        return round(float(th), 2)
    return 0.95


GROUPS = {
    "sạch / nhỏ / vang": lambda c: parse_condition(c)["noise"] is None and not parse_condition(c)["phone"],
    "nhiễu nền đều": lambda c: parse_condition(c)["noise"] in {
        "office", "street", "traffic", "hallway", "bus", "station", "square", "kitchen", "park", "living"}
    and not parse_condition(c)["phone"] and not parse_condition(c)["bns"],
    "tiếng động rời (ESC-50)": lambda c: (parse_condition(c)["noise"] or "").startswith("esc_"),
    "qua khử nhiễu trình duyệt": lambda c: parse_condition(c)["bns"],
    "kênh điện thoại": lambda c: parse_condition(c)["phone"],
    "nền là giọng người": lambda c: parse_condition(c)["noise"] in BACKGROUND_SPEECH
    and not parse_condition(c)["bns"] and not parse_condition(c)["phone"],
}  # fmt: skip


def _bootstrap_missed(
    results: list[dict],
    model: str,
    base: str,
    th_m: float,
    th_b: float,
    conds: set[str],
    rounds: int = 1000,
) -> tuple[float, float, float]:
    """Hiệu tỉ lệ câu bỏ sót (model − base) và khoảng tin cậy 95% bootstrap theo luồng (cặp)."""
    rs = [r for r in results if r["kind"] == "speech" and r["half"] == "B" and r["cond"] in conds]
    if not rs:
        return float("nan"), float("nan"), float("nan")
    a = np.array([event_metrics(r, model, th_m)["missed"] for r in rs], dtype=float)
    b = np.array([event_metrics(r, base, th_b)["missed"] for r in rs], dtype=float)
    u = np.array([len(r["spans"]) for r in rs], dtype=float)
    rng = np.random.default_rng(0)
    diffs = []
    for _ in range(rounds):
        idx = rng.integers(0, len(rs), len(rs))
        diffs.append((a[idx].sum() - b[idx].sum()) / u[idx].sum())
    return (
        (a.sum() - b.sum()) / u.sum(),
        float(np.percentile(diffs, 2.5)),
        float(np.percentile(diffs, 97.5)),
    )


def report(args) -> None:
    from sklearn.metrics import roc_auc_score

    with open(OUT / f"{args.label}.pkl", "rb") as handle:
        data = pickle.load(handle)
    models, results = data["models"], data["results"]
    # Mức báo nhầm chuẩn: Silero v4 (production) ở 0,5 trên nửa A (tối thiểu 0,2% thời gian).
    base = "silero_v4" if "silero_v4" in models else models[0]
    target = max(_fa_fraction(_noise_pool(results, "A"), base, 0.5), 0.002)
    fixed = lambda m: m.startswith("webrtc") or m in PRESMOOTHED  # noqa: E731
    thetas = {m: (0.5 if fixed(m) else calibrate(results, m, target)) for m in models}
    target_bg = _fa_fraction(_background_pool(results, "A"), base, 0.5)
    thetas2 = {m: (0.5 if fixed(m) else calibrate(results, m, target, target_bg)) for m in models}
    print(f"Mức báo nhầm chuẩn ({base} @0,5, nửa A): nhiễu không phải giọng người {target * 100:.2f}% "
          f"thời gian, nền giọng người {target_bg * 100:.2f}%.\nθ* (cùng mức nhiễu thường): {thetas}\n"
          f"θ** (không hơn mốc ở cả hai loại nền): {thetas2}\n")  # fmt: skip
    summary: dict = {"thetas": thetas, "thetas2": thetas2, "target": target, "target_bg": target_bg}
    speech_conds = list(dict.fromkeys(r["cond"] for r in results if r["kind"] == "speech"))
    noise_conds = list(dict.fromkeys(r["cond"] for r in results if r["kind"] == "noise"))
    for mode, th_of in (
        ("θ=0.5", lambda m: 0.5),
        ("θ*", lambda m: thetas[m]),
        ("θ**", lambda m: thetas2[m]),
    ):
        print(f"## {mode} — nửa B (dữ liệu không dùng để hiệu chỉnh)\n")
        print("| Nhóm tình huống | " + " | ".join(models) + " |")
        print("|---|" + "---|" * len(models))
        for group, pred in GROUPS.items():
            conds = {c for c in speech_conds if pred(c)}
            if not conds:
                continue
            cells = []
            for m in models:
                rs = [
                    r
                    for r in results
                    if r["kind"] == "speech" and r["half"] == "B" and r["cond"] in conds
                ]
                agg = _agg([event_metrics(r, m, th_of(m)) for r in rs])
                summary.setdefault(mode, {}).setdefault(f"group:{group}", {})[m] = agg
                cells.append(f"{agg['missed']}/{agg['utts']} · {agg['onset_p50']:.2f}/{agg['release_p50']:.2f}"
                             f"/{agg['release_p90']:.2f} · fr{agg['fragmented']} · br{agg['bridged']}")  # fmt: skip
            print(f"| {group} | " + " | ".join(cells) + " |")
        print("\n(ô: câu bỏ sót/câu · trễ đầu câu p50 / nhả cuối câu p50 / p90 (s) · câu cắt vụn · khoảng "
              "nghỉ ≥ 1,3 s bị nối)\n")  # fmt: skip
        print("| Điều kiện | " + " | ".join(models) + " |")
        print("|---|" + "---|" * len(models))
        for cond in speech_conds:
            cells = []
            for m in models:
                rs = [
                    r
                    for r in results
                    if r["kind"] == "speech" and r["cond"] == cond and r["half"] == "B"
                ]
                agg = _agg([event_metrics(r, m, th_of(m)) for r in rs])
                summary.setdefault(mode, {}).setdefault(cond, {})[m] = agg
                cells.append(f"{agg['missed']}/{agg['utts']} · {agg['release_p50']:.2f}")
            print(f"| {cond} | " + " | ".join(cells) + " |")
        print("\n(ô: câu bỏ sót/câu · nhả cuối câu p50 (s))\n")
        print("| Chỉ nhiễu (nửa B) | " + " | ".join(models) + " |")
        print("|---|" + "---|" * len(models))
        for cond in noise_conds:
            rs = [
                r
                for r in results
                if r["kind"] == "noise" and r["cond"] == cond and r["half"] == "B"
            ]
            mins = sum(r["seconds"] for r in rs) / 60
            cells = []
            for m in models:
                frac = _fa_fraction(rs, m, th_of(m))
                trig = sum(len(_runs(_flags(*r["probs"][m], m, th_of(m)))) for r in rs)
                summary.setdefault(mode, {}).setdefault(f"noise:{cond}", {})[m] = (
                    frac,
                    trig / max(mins, 1e-9),
                )
                cells.append(f"{frac * 100:.1f}% · {trig / max(mins, 1e-9):.1f}")
            print(f"| {cond} | " + " | ".join(cells) + " |")
        overall = {m: _fa_fraction(_noise_pool(results, "B"), m, th_of(m)) for m in models}
        overall_bg = {m: _fa_fraction(_background_pool(results, "B"), m, th_of(m)) for m in models}
        summary.setdefault(mode, {})["noise:overall"] = overall
        summary.setdefault(mode, {})["noise:overall_bg"] = overall_bg
        print("| **tổng nhiễu thường** | "
              + " | ".join(f"**{overall[m] * 100:.2f}%**" for m in models) + " |")  # fmt: skip
        print("| **tổng nền giọng người** | "
              + " | ".join(f"**{overall_bg[m] * 100:.2f}%**" for m in models) + " |")  # fmt: skip
        print("\n(ô: % thời gian báo nhầm · số lần kích hoạt nhầm/phút)\n")
        main_conds = {
            c for c in speech_conds if parse_condition(c)["noise"] not in BACKGROUND_SPEECH
        }
        print(
            "Câu bỏ sót so với silero_v4 @0,5 (mọi điều kiện trừ nền giọng người), hiệu và KTC 95%:"
        )
        for m in models:
            d, lo, hi = _bootstrap_missed(results, m, base, th_of(m), 0.5, main_conds)
            print(f"  {m:12} {d * 100:+.1f} điểm % [{lo * 100:+.1f}; {hi * 100:+.1f}]")
        print()
    print("## AUC (khung 10 ms, xác suất thô, cả hai nửa)")
    print("| Điều kiện | " + " | ".join(models) + " |")
    print("|---|" + "---|" * len(models))
    for cond in dict.fromkeys(r["cond"] for r in results if r["kind"] in ("speech", "tenset")):
        cells = []
        for m in models:
            ps, ls = [], []
            for r in results:
                if r["cond"] == cond and r["kind"] in ("speech", "tenset"):
                    prob, lab = auc_parts(r, m)
                    ps.append(prob)
                    ls.append(lab)
            y, sc = np.concatenate(ls), np.concatenate(ps)
            binary = m.startswith("webrtc") or m in PRESMOOTHED
            auc = roc_auc_score(y, sc) if 0 < y.mean() < 1 and not binary else float("nan")
            summary.setdefault("auc", {}).setdefault(cond, {})[m] = auc
            cells.append(f"{auc:.3f}")
        print(f"| {cond} | " + " | ".join(cells) + " |")
    cpu = {
        m: sum(r["cpu"][m] for r in results) / sum(r["seconds"] for r in results) for m in models
    }
    print("\nCPU (giây CPU / giây audio, 1 luồng):", {m: round(v, 4) for m, v in cpu.items()})
    summary["cpu"] = cpu
    (OUT / f"{args.label}_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1, default=float)
    )


def _agg(items: list[dict]) -> dict:
    out = {"utts": sum(i["utts"] for i in items), "missed": sum(i["missed"] for i in items),
           "fragmented": sum(i["fragmented"] for i in items), "bridged": sum(i["bridged"] for i in items),
           "pauses": sum(i["pauses"] for i in items)}  # fmt: skip
    onsets = [x for i in items for x in i["onset"]]
    releases = [x for i in items for x in i["release"]]
    out["onset_p50"] = float(np.median(onsets)) if onsets else float("nan")
    out["release_p50"] = float(np.median(releases)) if releases else float("nan")
    out["release_p90"] = float(np.percentile(releases, 90)) if releases else float("nan")
    secs = sum(i["nonspeech_s"] for i in items)
    out["ft_per_min"] = sum(i["false_triggers"] for i in items) / max(secs / 60, 1e-9)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="mode", required=True)
    r = sub.add_parser("run")
    r.add_argument("--label", required=True)
    r.add_argument("--models", default="silero_v4,silero_v5,silero_v6,ten,firered,webrtc3,gtcrn_v4")
    r.add_argument("--conditions", default=DEFAULT_CONDITIONS)
    r.add_argument("--noise-only", default=NOISE_ONLY)
    r.add_argument(
        "--noise-streams", type=int, default=6, help="số luồng 20 s chỉ nhiễu mỗi điều kiện"
    )
    r.add_argument("--vivos", type=int, default=120)
    r.add_argument("--tenset", action="store_true")
    r.add_argument("--workers", type=int, default=8)
    r.add_argument("--libcxx", default=os.environ.get("TEN_LIBCXX", ""))
    p = sub.add_parser("report")
    p.add_argument("--label", required=True)
    args = parser.parse_args()
    run(args) if args.mode == "run" else report(args)


if __name__ == "__main__":
    main()
