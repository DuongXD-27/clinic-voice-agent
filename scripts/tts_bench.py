"""Bộ đo TTS dùng chung — 6 tiêu chí ADR-002, chạy được cho mọi provider trong `create_tts`.

    python scripts/tts_bench.py --provider elevenlabs [--voice <id>] [--label elevenlabs:trang] [--repeats 2]
    python scripts/tts_bench.py --import-dir ../ZeroTTS --wav-dir ../ZeroTTS/wav --family zerotts ...   # CSV đo ở Colab
    python scripts/tts_bench.py --matrix                                # dựng lại docs/evidence/tts-bench/matrix.md

Tự động đo tiêu chí 2 (streaming/TTFA/RTF/đứt tiếng), 3 (barge-in), 5 (P95, chi phí); 6 chấm tĩnh theo tài liệu.
Tiêu chí 1 (đọc đúng entity) và 4 (nghe rõ qua điện thoại) **do người nghe**: script sinh WAV sạch + WAV đã qua
mô phỏng đường dây (8 kHz, 300–3400 Hz, G.711 μ-law, nhiễu 25 dB) và một phiếu nghe `listening_sheet.csv`
cho 3 người; điền phiếu xong chạy `--matrix` để gộp điểm vào ma trận.

Kết quả: `docs/evidence/tts-bench/<label>/` (CSV, phiếu nghe, summary.json — commit được),
WAV ở `temp/tts-bench/<label>/wav/` (không commit). Không in key; text đo là câu cố định không PII.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Iterator, Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tts_bench_set import LONGEST, TEST_SET, TOTAL_CHARS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = ROOT / "docs" / "evidence" / "tts-bench"
WAV_ROOT = ROOT / "temp" / "tts-bench"
LISTENERS = 3

# ---------------------------------------------------------------------------------------------
# Ngưỡng chấm — kế hoạch TTS 6 tuần + hợp đồng §4.1.2 (TTS ≤ 1,5–2 s trong ngân sách 8 s/lượt)
# ---------------------------------------------------------------------------------------------
THRESHOLDS = {
    "c1_entity": {"High": 0.95, "Medium": 0.85},  # % câu người nghe xác nhận đọc đúng mọi entity
    "c2_ttfa_p95_ms": {"High": 500, "Medium": 1500},  # byte audio đầu
    "c2_rtf_p95": {"High": 0.7, "Medium": 1.0},  # < 1 mới phát liên tục được
    "c2_underrun": {"High": 0.05, "Medium": 0.2},  # % câu bị đứt tiếng khi phát ngay từ chunk đầu
    "c3_stop_ms": {"High": 100, "Medium": 500},  # sau cancel không còn chunk mới quá X ms (TTS-4.2)
    "c4_clear_8k": {"High": 4.0, "Medium": 3.0},  # điểm nghe rõ qua điện thoại, thang 1–5
    "c5_total_p95_ms": {"High": 2000, "Medium": 3500},  # P95 tổng thời gian sinh 1 câu
}

# Tiêu chí 6 — bảo mật: tĩnh theo nhà cung cấp; "High*" = theo tài liệu, chưa kiểm chứng
SECURITY = {
    "elevenlabs": (
        "Medium",
        "Máy chủ nước ngoài (US/EU); lưu lịch sử generation mặc định (tắt được ở gói trả phí); "
        "key qua header; adapter không log text.",
    ),
    "zerotts": ("High", "Self-host, dữ liệu không rời hệ thống; không có key."),
    "azure": ("High*", "Theo tài liệu: không retain text/audio, region SEA; chưa đo."),
}

# Tiêu chí 5 — chi phí: mô hình giá đơn giản, KIỂM LẠI trên trang giá nhà cung cấp trước khi báo cáo
CHARS_PER_CALL = 750
CALLS_PER_MONTH = (500, 5000, 50000)


def cost_elevenlabs(chars: int) -> str:
    # Flash v2.5 tính 0,5 credit/ký tự. (gói, USD/tháng, credit kèm, USD/1k credit mua thêm) — elevenlabs.io/pricing
    credits = chars * 0.5
    plans = [
        ("Free", 0, 10_000, None),
        ("Starter", 5, 30_000, None),
        ("Creator", 22, 100_000, 0.30),
        ("Pro", 99, 500_000, 0.24),
        ("Scale", 330, 2_000_000, 0.18),
        ("Business", 1320, 11_000_000, 0.12),
    ]
    best = None
    for name, usd, cap, extra in plans:
        if credits <= cap:
            total, note = usd, ""
        elif extra is None:
            continue
        else:
            total = usd + (credits - cap) / 1000 * extra
            note = f" (+{(credits - cap) / 1000:.0f}k credit mua thêm)"
        if best is None or total < best[0]:
            best = (total, f"{name} ~{total:.0f} USD{note}")
    return best[1] if best else "?"


def cost_for(family: str, chars: int) -> str:
    if family == "elevenlabs":
        return cost_elevenlabs(chars)
    if family == "zerotts":
        return "self-host: xem AWS trong report gốc"
    return "?"


# ---------------------------------------------------------------------------------------------
# Audio utils
# ---------------------------------------------------------------------------------------------
def pcm16_to_f32(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


def resample_f32(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst:
        return x
    from scipy.signal import resample_poly

    g = math.gcd(src, dst)
    return resample_poly(x, dst // g, src // g).astype(np.float32)


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    import soundfile as sf

    x, sr = sf.read(str(path), dtype="float32")
    if x.ndim > 1:
        x = x.mean(axis=1)
    return x, sr


def write_wav(path: Path, x: np.ndarray, sr: int) -> None:
    import soundfile as sf

    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.asarray(x, dtype=np.float32), sr, subtype="PCM_16")


_BIAS, _CLIP = 0x84, 32635


def mulaw_encode(pcm16: np.ndarray) -> np.ndarray:
    s = pcm16.astype(np.int32)
    sign = np.where(s < 0, 0x80, 0).astype(np.int32)
    s = np.minimum(np.abs(s), _CLIP) + _BIAS
    exp = (np.floor(np.log2(s)) - 7).astype(np.int32)
    mant = (s >> (exp + 3)) & 0x0F
    return (~(sign | (exp << 4) | mant) & 0xFF).astype(np.uint8)


def mulaw_decode(u: np.ndarray) -> np.ndarray:
    u = (~u.astype(np.int32)) & 0xFF
    sign, exp, mant = u & 0x80, (u >> 4) & 0x07, u & 0x0F
    s = (((mant << 3) + _BIAS) << exp) - _BIAS
    return np.where(sign, -s, s).astype(np.int16)


def telephony(
    x: np.ndarray, sr: int, snr_db: float = 25.0, seed: int = 0
) -> tuple[np.ndarray, int]:
    """Mô phỏng cuộc gọi: hạ 8 kHz, băng 300–3400 Hz, G.711 μ-law, nhiễu nền 25 dB."""
    from scipy.signal import butter, sosfilt

    y = resample_f32(x, sr, 8000)
    sos = butter(4, [300, 3400], btype="bandpass", fs=8000, output="sos")
    y = sosfilt(sos, y).astype(np.float32)
    rng = np.random.default_rng(seed)
    p = float(np.mean(y**2)) + 1e-12
    y = y + rng.normal(0, math.sqrt(p / (10 ** (snr_db / 10))), size=y.shape).astype(np.float32)
    pcm = (np.clip(y, -1, 1) * 32767).astype(np.int16)
    return mulaw_decode(mulaw_encode(pcm)).astype(np.float32) / 32768.0, 8000


def make_telephony_wavs(prefix: str, wav_dir: Path) -> int:
    """Với mỗi `<prefix>__<id>.wav` sạch, ghi `<prefix>__<id>__tel8k.wav` cho người nghe tiêu chí 4."""
    n = 0
    for item in TEST_SET:
        src = wav_dir / f"{prefix}__{item['id']}.wav"
        if not src.exists():
            continue
        x, sr = read_wav(src)
        y, ysr = telephony(x, sr)
        write_wav(wav_dir / f"{prefix}__{item['id']}__tel8k.wav", y, ysr)
        n += 1
    return n


# ---------------------------------------------------------------------------------------------
# Provider adapter: dùng đúng adapter production trong callbot.speech.tts
# ---------------------------------------------------------------------------------------------
class Bench:
    def __init__(self, provider: str, voice: Optional[str], label: str, timeout_s: float) -> None:
        from callbot.speech.settings import SpeechSettings
        from callbot.speech.tts import create_tts

        voice_field = {"elevenlabs": "elevenlabs_voice_id"}
        timeout_field = {"elevenlabs": "elevenlabs_timeout_s"}
        settings = SpeechSettings()
        overrides: dict[str, Any] = {"tts_provider": provider, timeout_field[provider]: timeout_s}
        if voice:
            overrides[voice_field[provider]] = voice
        settings = settings.model_copy(update=overrides)
        self.tts = create_tts(settings)
        self.voice = voice or getattr(settings, voice_field[provider])
        self.family = provider
        self.label = label
        self.sr = self.tts.sample_rate

    def stream(self, text: str) -> Iterator[bytes]:
        return self.tts.stream(text)


# ---------------------------------------------------------------------------------------------
# Tiêu chí 2 & 5 — latency / RTF / đứt tiếng
# ---------------------------------------------------------------------------------------------
def run_one(b: Bench, item: dict, rep: int, wav_dir: Path) -> dict:
    """Mô phỏng phát ra loa ngay khi có chunk đầu: chunk n phải đến trước TTFA + tổng audio trước đó."""
    t0 = time.perf_counter()
    chunks: list[tuple[float, float, bytes]] = []
    base = {
        "provider": b.label,
        "id": item["id"],
        "kind": item["kind"],
        "rep": rep,
        "chars": len(item["text"]),
    }
    try:
        for pcm in b.stream(item["text"]):
            chunks.append((time.perf_counter() - t0, len(pcm) / 2 / b.sr, pcm))
    except Exception as exc:  # noqa: BLE001 — ghi lỗi vào CSV, không dừng cả bộ
        return {**base, "error": f"{type(exc).__name__}: {str(exc)[:100]}"}
    if not chunks:
        return {**base, "error": "no audio"}
    ttfa = chunks[0][0]
    cum = worst_late = 0.0
    underruns = 0
    for t, d, _ in chunks:
        late = t - (ttfa + cum)
        if late > 0.02:
            underruns += 1
            worst_late = max(worst_late, late)
        cum += d
    total = chunks[-1][0]
    if rep == 0:
        audio = pcm16_to_f32(b"".join(c[2] for c in chunks))
        out = wav_dir / f"{safe_dir(b.label)}__{item['id']}.wav"
        write_wav(out, resample_f32(audio, b.sr, 16000), 16000)
    return {
        **base,
        "ttfa_ms": round(ttfa * 1000),
        "total_ms": round(total * 1000),
        "audio_s": round(cum, 2),
        "rtf": round(total / cum, 2) if cum else None,
        "chunks": len(chunks),
        "first_chunk_s": round(chunks[0][1], 2),
        "max_chunk_s": round(max(c[1] for c in chunks), 2),
        "underruns": underruns,
        "buffer_needed_ms": round(worst_late * 1000),
        "chars_per_s": round(len(item["text"]) / cum, 1) if cum else None,
        "error": "",
    }


# ---------------------------------------------------------------------------------------------
# Tiêu chí 3 — barge-in
# ---------------------------------------------------------------------------------------------
def run_bargein(b: Bench, rep: int) -> dict:
    """Sinh câu dài nhất, sau 400 ms cancel; đo bao lâu mới dừng và bao nhiêu audio đã nhận phải bỏ."""
    gen = b.stream(LONGEST["text"])
    t0 = time.perf_counter()
    received = 0.0
    t_cancel = ttfa = stop_ms = None
    try:
        for pcm in gen:
            now = time.perf_counter() - t0
            received += len(pcm) / 2 / b.sr
            if ttfa is None:
                ttfa = now
            if now >= 0.4:
                t_cancel = now
                gen.close()  # GeneratorExit → adapter đóng WS/HTTP trong finally
                stop_ms = round((time.perf_counter() - t0 - t_cancel) * 1000)
                break
    except Exception:  # noqa: BLE001
        pass
    if t_cancel is None:
        return {"provider": b.label, "rep": rep, "note": "câu xong trước 400 ms — không đo được"}
    played = max(0.0, t_cancel - (ttfa or 0))
    return {
        "provider": b.label,
        "rep": rep,
        "cancel_at_ms": round(t_cancel * 1000),
        "stop_latency_ms": stop_ms,
        "chunks_after_cancel": 0,
        "audio_received_s": round(received, 2),
        "audio_to_discard_s": round(max(0.0, received - played), 2),
        "note": "",
    }


# ---------------------------------------------------------------------------------------------
# Tiêu chí 1 & 4 — phiếu nghe cho người
# ---------------------------------------------------------------------------------------------
def listening_sheet(label: str, wav_dir: Path) -> list[dict]:
    """Một dòng/câu. Mỗi người: entity (1 = đọc đúng hết mục cần nghe, 0 = sai), tu_nhien 1–5, ro_8k 1–5 (file tel8k)."""
    rows = []
    prefix = safe_dir(label)
    for item in TEST_SET:
        row = {
            "provider": label,
            "id": item["id"],
            "kind": item["kind"],
            "text": item["text"],
            "can_nghe_dung": " | ".join(v[0] for v in item["entities"]),
            "wav_sach": str(wav_dir / f"{prefix}__{item['id']}.wav"),
            "wav_dien_thoai": str(wav_dir / f"{prefix}__{item['id']}__tel8k.wav"),
        }
        for i in range(1, LISTENERS + 1):
            for c in ("entity", "tu_nhien", "ro_8k"):
                row[f"nguoi{i}_{c}"] = ""
        rows.append(row)
    return rows


def read_listening(rows: list[dict]) -> dict:
    """Gộp phiếu đã điền: entity = % câu đúng (trung bình các người), tu_nhien/ro_8k = điểm trung bình 1–5."""
    out: dict[str, Any] = {"listeners": 0}
    ent, nat, clear = [], [], []
    for i in range(1, LISTENERS + 1):
        e = [r.get(f"nguoi{i}_entity") for r in rows]
        e = [v for v in e if v not in (None, "")]
        if len(e) < len(rows):
            continue  # người này chưa điền hết → bỏ qua
        out["listeners"] += 1
        ent.append(
            sum(1 for v in e if str(v).strip().lower() in ("1", "1.0", "true", "x")) / len(e)
        )
        for col, acc in (("tu_nhien", nat), ("ro_8k", clear)):
            vals = [
                float(v) for v in (r.get(f"nguoi{i}_{col}") for r in rows) if v not in (None, "")
            ]
            if vals:
                acc.append(statistics.mean(vals))
    if out["listeners"]:
        out["entity_human"] = statistics.mean(ent)
        out["natural_5"] = statistics.mean(nat) if nat else None
        out["clear_8k_5"] = statistics.mean(clear) if clear else None
    return out


# ---------------------------------------------------------------------------------------------
# Tổng hợp + chấm
# ---------------------------------------------------------------------------------------------
def q(values: list[float], p: float) -> Optional[float]:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    k = (len(vals) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    return vals[lo] if lo == hi else vals[lo] + (vals[hi] - vals[lo]) * (k - lo)


def grade(value: Optional[float], key: str, lower_is_better: bool = True) -> str:
    if value is None:
        return "chưa đo"
    th = THRESHOLDS[key]
    if lower_is_better:
        return "High" if value <= th["High"] else "Medium" if value <= th["Medium"] else "Low"
    return "High" if value >= th["High"] else "Medium" if value >= th["Medium"] else "Low"


def worst(*grades: str) -> str:
    order = {"Low": 0, "Medium": 1, "High": 2}
    real = [g for g in grades if g in order]
    return min(real, key=lambda g: order[g]) if real else "chưa đo"


def summarize(
    label: str, family: str, meta: dict, lat: list[dict], barge: list[dict], sheet: list[dict]
) -> dict:
    ok = [r for r in lat if not r.get("error")]
    s: dict[str, Any] = {"label": label, "family": family, **meta}
    s.update(n_runs=len(lat), errors=len(lat) - len(ok))
    if ok:
        s.update(
            ttfa_p50=q([r["ttfa_ms"] for r in ok], 0.5),
            ttfa_p95=q([r["ttfa_ms"] for r in ok], 0.95),
            total_p50=q([r["total_ms"] for r in ok], 0.5),
            total_p95=q([r["total_ms"] for r in ok], 0.95),
            rtf_p50=q([r["rtf"] for r in ok], 0.5),
            rtf_p95=q([r["rtf"] for r in ok], 0.95),
            underrun_rate=sum(1 for r in ok if r["underruns"] > 0) / len(ok),
            buffer_p95_ms=q([r["buffer_needed_ms"] for r in ok], 0.95),
            max_chunk_s=max(r["max_chunk_s"] for r in ok),
            chars_per_s=statistics.median(r["chars_per_s"] for r in ok if r["chars_per_s"]),
            greet_total_p95=q([r["total_ms"] for r in ok if r["kind"] == "fixed"], 0.95),
        )
        # stream thật = chunk đầu chỉ chứa một phần câu (< 50 % audio). CSV cũ không có first_chunk_s → heuristic.
        firsts = [
            r["first_chunk_s"] / r["audio_s"]
            for r in ok
            if r.get("first_chunk_s") is not None and r["audio_s"]
        ]
        if firsts:
            s["first_chunk_share"] = statistics.median(firsts)
            s["streams"] = s["first_chunk_share"] < 0.5
        else:
            s["streams"] = (
                statistics.median(r["chunks"] for r in ok) > 1
                and s["ttfa_p50"] < 0.8 * s["total_p50"]
            )
    bok = [r for r in barge if r.get("stop_latency_ms") is not None]
    if bok:
        s["stop_latency_ms"] = max(r["stop_latency_ms"] for r in bok)
        s["audio_to_discard_s"] = statistics.mean(r["audio_to_discard_s"] for r in bok)
    s.update(read_listening(sheet) if sheet else {"listeners": 0})

    g = {}
    heard = s["listeners"] > 0
    g["c1"] = (
        grade(s.get("entity_human"), "c1_entity", lower_is_better=False) if heard else "chưa nghe"
    )
    if ok:
        c2 = worst(
            grade(s["ttfa_p95"], "c2_ttfa_p95_ms"),
            grade(s["rtf_p95"], "c2_rtf_p95"),
            grade(s["underrun_rate"], "c2_underrun"),
        )
        g["c2"] = (
            c2 if s["streams"] else worst(c2, "Medium")
        )  # không stream thì tối đa Medium dù nhanh
        g["c3"] = "Low" if not s["streams"] else grade(s.get("stop_latency_ms"), "c3_stop_ms")
    else:
        g["c2"] = g["c3"] = "chưa đo"
    g["c4"] = (
        grade(s.get("clear_8k_5"), "c4_clear_8k", lower_is_better=False) if heard else "chưa nghe"
    )
    g["c5"] = grade(s.get("total_p95"), "c5_total_p95_ms")
    g["c6"] = SECURITY.get(family, ("chưa đo", ""))[0]
    s["grades"] = g
    s["cost"] = {str(c): cost_for(family, c * CHARS_PER_CALL) for c in CALLS_PER_MONTH}
    s["pass_28_9"] = g["c5"] == "High" and g["c1"] != "Low"
    return s


# ---------------------------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------------------------
def safe_dir(label: str) -> str:
    """Tên thư mục/file hợp lệ trên Windows: `elevenlabs:trang` → `elevenlabs__trang`."""
    return re.sub(r"[^\w.-]+", "__", label)


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    keys: list[str] = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        c: dict[str, Any] = {}
        for k, v in r.items():
            if v in ("", None):
                c[k] = None if k != "error" else ""
            elif v in ("True", "False"):
                c[k] = v == "True"
            elif re.fullmatch(r"-?\d+", v):
                c[k] = int(v)
            elif re.fullmatch(r"-?\d+\.\d+", v):
                c[k] = float(v)
            else:
                c[k] = v
        out.append(c)
    return out


def read_sheet(folder: Path) -> list[dict]:
    p = folder / "listening_sheet.csv"
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fmt(v: Any, nd: int = 0) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "có" if v else "không"
    if isinstance(v, float):
        return f"{v:.{nd}f}" if nd else f"{v:,.0f}"
    return str(v)


def pct(v: Any) -> str:
    return "—" if v is None else f"{v * 100:.0f} %"


META_KEYS = ("date", "machine", "voice", "sample_rate", "repeats", "imported_from")


def resummarize(folder: Path) -> dict:
    """Chấm lại một dòng từ CSV + phiếu nghe + meta cũ — đổi ngưỡng hay điền phiếu xong chỉ cần `--matrix`."""
    old = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    meta = {k: old[k] for k in META_KEYS if k in old}
    s = summarize(
        old["label"],
        old["family"],
        meta,
        read_csv(folder / "latency_raw.csv"),
        read_csv(folder / "bargein.csv"),
        read_sheet(folder),
    )
    (folder / "summary.json").write_text(
        json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return s


def passed(s: dict) -> str:
    if not s.get("pass_28_9"):
        return "Không"
    return "**Có** (tốc độ) — chờ phiếu nghe" if s["grades"]["c1"] == "chưa nghe" else "**Có**"


def build_matrix() -> Path:
    summaries = [resummarize(p.parent) for p in sorted(EVIDENCE_DIR.glob("*/summary.json"))]
    L = [
        "# Ma trận đánh giá TTS — số đo chung (ADR-002)",
        "",
        f"_Sinh tự động bởi `scripts/tts_bench.py` · cập nhật {date.today().isoformat()} · "
        f"bộ câu `scripts/tts_bench_set.py` ({len(TEST_SET)} câu, {TOTAL_CHARS} ký tự)._",
        "",
        "Cùng bộ câu, cùng cách đo cho mọi provider. Tiêu chí 2, 3, 5 đo tự động; 6 chấm tĩnh theo tài liệu; "
        "**tiêu chí 1 và 4 do người nghe** (phiếu `listening_sheet.csv`, 3 người, điền xong chạy `--matrix`).",
        "",
        "## 1. Ma trận High / Medium / Low",
        "",
        "| Label | Ngày · máy | 1. Đọc đúng (người nghe) | 2. Streaming/TTFA | 3. Barge-in | "
        "4. Điện thoại (người nghe) | 5. P95 & chi phí | 6. Bảo mật | Đạt 28/9? |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summaries:
        g = s["grades"]
        L.append(
            f"| **{s['label']}** | {s.get('date', '?')} · {s.get('machine', '?')} | {g['c1']} | {g['c2']} | "
            f"{g['c3']} | {g['c4']} | {g['c5']} | {g['c6']} | {passed(s)} |"
        )
    L += [
        "",
        "Ngưỡng: đọc đúng ≥ 95 % câu High / ≥ 85 % Medium · TTFA P95 ≤ 500 ms & RTF P95 < 0,7 & đứt tiếng < 5 % High "
        "(không stream → tối đa Medium) · dừng sau cancel ≤ 100 ms High (không stream → Low) · nghe rõ qua điện thoại "
        "≥ 4/5 High, ≥ 3/5 Medium · P95 tổng ≤ 2 000 ms High / ≤ 3 500 Medium · bảo mật chấm tĩnh. "
        '"Đạt 28/9" = P95 High và đọc đúng không Low.',
        "",
        "## 2. Số đo tự động (tiêu chí 2, 3, 5)",
        "",
        "| Label | n | Lỗi | TTFA P50/P95 (ms) | Tổng P50/P95 (ms) | Câu chào P95 | RTF P50/P95 | Đứt tiếng | "
        "Stream? | Chunk đầu / câu | Chunk max (s) | Dừng sau cancel (ms) | Audio phải bỏ (s) |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summaries:
        L.append(
            f"| {s['label']} | {s.get('n_runs', '—')} | {s.get('errors', '—')} | "
            f"{fmt(s.get('ttfa_p50'))} / {fmt(s.get('ttfa_p95'))} | {fmt(s.get('total_p50'))} / {fmt(s.get('total_p95'))} | "
            f"{fmt(s.get('greet_total_p95'))} | {fmt(s.get('rtf_p50'), 2)} / {fmt(s.get('rtf_p95'), 2)} | "
            f"{pct(s.get('underrun_rate'))} | {fmt(s.get('streams'))} | {pct(s.get('first_chunk_share'))} | "
            f"{fmt(s.get('max_chunk_s'), 2)} | {fmt(s.get('stop_latency_ms'))} | {fmt(s.get('audio_to_discard_s'), 2)} |"
        )
    L += [
        "",
        "## 3. Người nghe (tiêu chí 1, 4)",
        "",
        "| Label | Số người đã nghe | Đọc đúng mọi entity (% câu) | Tự nhiên (1–5) | Nghe rõ qua điện thoại (1–5) | Phiếu |",
        "|---|---|---|---|---|---|",
    ]
    for s in summaries:
        L.append(
            f"| {s['label']} | {s.get('listeners', 0)}/{LISTENERS} | {pct(s.get('entity_human'))} | "
            f"{fmt(s.get('natural_5'), 1)} | {fmt(s.get('clear_8k_5'), 1)} | `{safe_dir(s['label'])}/listening_sheet.csv` |"
        )
    L += [
        "",
        f"## 4. Chi phí ước tính ({CHARS_PER_CALL} ký tự/cuộc gọi — kiểm lại giá trước khi báo cáo)",
        "",
        "| Label | " + " | ".join(f"{c:,} cuộc/tháng" for c in CALLS_PER_MONTH) + " |",
        "|---|" + "---|" * len(CALLS_PER_MONTH),
    ]
    for s in summaries:
        L.append(
            f"| {s['label']} | "
            + " | ".join(s.get("cost", {}).get(str(c), "?") for c in CALLS_PER_MONTH)
            + " |"
        )
    L += ["", "## 5. Bảo mật (tiêu chí 6, chấm tĩnh)", ""]
    for fam, (g, note) in SECURITY.items():
        L.append(f"- **{fam}** — {g}: {note}")
    L += [
        "",
        "## 6. Cách lặp lại",
        "",
        "```",
        "python scripts/tts_bench.py --provider elevenlabs [--voice <id>] [--label provider:giong] [--repeats 2]",
        "python scripts/tts_bench.py --import-dir <CSV Colab> --wav-dir <wav Colab> --family zerotts --date ... --machine ...",
        "python scripts/tts_bench.py --matrix        # sau khi điền listening_sheet.csv",
        "```",
        "",
        "Mỗi dòng: `docs/evidence/tts-bench/<label>/` (latency_raw.csv, bargein.csv, listening_sheet.csv, summary.json). "
        "WAV sạch + WAV điện thoại (`__tel8k`) để nghe: `temp/tts-bench/<label>/wav/`.",
    ]
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE_DIR / "matrix.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8", newline="\n")
    return out


# ---------------------------------------------------------------------------------------------
# Lệnh
# ---------------------------------------------------------------------------------------------
def _finish(
    label: str,
    family: str,
    meta: dict,
    out_dir: Path,
    wav_dir: Path,
    lat: list[dict],
    barge: list[dict],
) -> None:
    n_tel = make_telephony_wavs(safe_dir(label), wav_dir)
    sheet_path = out_dir / "listening_sheet.csv"
    if not sheet_path.exists():  # không ghi đè phiếu người đã điền
        write_csv(sheet_path, listening_sheet(label, wav_dir))
    s = summarize(label, family, meta, lat, barge, read_sheet(out_dir))
    (out_dir / "summary.json").write_text(
        json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"{n_tel} WAV điện thoại → {wav_dir} · phiếu nghe → {sheet_path}")
    keys = (
        "grades",
        "ttfa_p50",
        "ttfa_p95",
        "total_p95",
        "rtf_p95",
        "underrun_rate",
        "stop_latency_ms",
        "pass_28_9",
    )
    print(json.dumps({k: s[k] for k in keys if k in s}, ensure_ascii=False))
    print("ma trận:", build_matrix())


def cmd_run(args: argparse.Namespace) -> int:
    import platform

    b = Bench(
        args.provider,
        args.voice,
        args.label or f"{args.provider}:{args.voice or 'default'}",
        args.timeout,
    )
    out_dir, wav_dir = EVIDENCE_DIR / safe_dir(b.label), WAV_ROOT / safe_dir(b.label) / "wav"
    out_dir.mkdir(parents=True, exist_ok=True)
    wav_dir.mkdir(parents=True, exist_ok=True)
    est = TOTAL_CHARS * args.repeats + len(LONGEST["text"]) * 2
    print(
        f"label={b.label} voice={b.voice} sr={b.sr} | {len(TEST_SET)} câu × {args.repeats} lặp ≈ {est} ký tự"
    )

    lat = []
    for item in TEST_SET:
        for rep in range(args.repeats):
            lat.append(run_one(b, item, rep, wav_dir))
            print("x" if lat[-1].get("error") else ".", end="", flush=True)
    print(" latency xong")
    write_csv(out_dir / "latency_raw.csv", lat)
    errs = [r for r in lat if r.get("error")]
    if errs:
        print(f"  {len(errs)} lỗi, ví dụ: {errs[0]['error']}")
    barge = [run_bargein(b, rep) for rep in range(2)]
    write_csv(out_dir / "bargein.csv", barge)
    print("barge-in xong:", [r.get("stop_latency_ms", r.get("note")) for r in barge])

    meta = {
        "date": date.today().isoformat(),
        "machine": f"{platform.system()} laptop, API qua Internet",
        "voice": b.voice,
        "sample_rate": b.sr,
        "repeats": args.repeats,
    }
    _finish(b.label, b.family, meta, out_dir, wav_dir, lat, barge)
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    """Nhập latency/barge-in đo nơi khác (cùng cột CSV) + WAV sạch của nó; sinh WAV điện thoại và phiếu nghe."""
    import shutil

    src = Path(args.import_dir)
    lat_all = read_csv(src / "latency_raw.csv")
    barge_all = read_csv(src / "bargein.csv")
    for lab in sorted({r["provider"] for r in lat_all}):
        out_dir, wav_dir = EVIDENCE_DIR / safe_dir(lab), WAV_ROOT / safe_dir(lab) / "wav"
        out_dir.mkdir(parents=True, exist_ok=True)
        wav_dir.mkdir(parents=True, exist_ok=True)
        lat = [r for r in lat_all if r["provider"] == lab]
        barge = [r for r in barge_all if r["provider"] == lab]
        write_csv(out_dir / "latency_raw.csv", lat)
        write_csv(out_dir / "bargein.csv", barge)
        if args.wav_dir:  # WAV Colab có thể tên `zerotts_baotrang__id.wav` → copy về tên chuẩn
            alt = re.sub(r"[^\w.-]+", "_", lab)
            for item in TEST_SET:
                for name in (f"{alt}__{item['id']}.wav", f"{safe_dir(lab)}__{item['id']}.wav"):
                    cand = Path(args.wav_dir) / name
                    if cand.exists():
                        shutil.copy(cand, wav_dir / f"{safe_dir(lab)}__{item['id']}.wav")
                        break
        meta = {"date": args.date or "?", "machine": args.machine or "?", "imported_from": str(src)}
        print(f"== {lab}")
        _finish(lab, args.family or lab.split(":")[0], meta, out_dir, wav_dir, lat, barge)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--provider", choices=["elevenlabs"])
    ap.add_argument("--voice")
    ap.add_argument("--label", help="tên dòng trong ma trận, mặc định provider:voice")
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="deadline mỗi câu (s) — đo thì nới, production 4 s",
    )
    ap.add_argument("--import-dir", help="thư mục CSV đo nơi khác (Colab)")
    ap.add_argument("--wav-dir", help="import: thư mục WAV sạch đi kèm")
    ap.add_argument(
        "--family", help="import: họ provider cho chấm bảo mật/chi phí (zerotts, elevenlabs, azure)"
    )
    ap.add_argument("--date")
    ap.add_argument("--machine")
    ap.add_argument(
        "--matrix", action="store_true", help="chỉ dựng lại matrix.md (đọc phiếu nghe mới)"
    )
    args = ap.parse_args()
    if args.import_dir:
        return cmd_import(args)
    if args.matrix:
        print("ma trận:", build_matrix())
        return 0
    if not args.provider:
        ap.error("cần --provider, --import-dir hoặc --matrix")
    return cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
