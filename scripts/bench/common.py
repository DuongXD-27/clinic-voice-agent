"""Phần dùng chung của bộ benchmark (scripts/bench/): thống kê, câu người gọi, định dạng kết quả.

Ở mức module chỉ import thư viện chuẩn: `compare.py` chạy được bằng python3 của host EC2 (không có
package callbot). Code cần package dự án thì import trong hàm.

Không ghi text hội thoại vào kết quả (NFR-16): chỉ số ký tự, thời gian, provider, mã lỗi.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = "bench.v1"
TURN_BUDGET_MS = 8000  # §4.1.2: ≤ 8 s mỗi lượt, tính tới lúc tải xong audio_url

# Câu người gọi mặc định: giữ cuộc gọi ở bước hỏi lại danh tính, không dẫn tới chuyển máy / ghi
# kết quả trên Clinic mock dùng chung (xem docs/reference/latency-benchmark.md).
CALLER_LINES = ["Alo, tôi nghe đây.", "Anh chị nói lại giúp tôi được không?"]
BARGE_IN_LINE = "Khoan đã, cho tôi hỏi một chút."
# Ước lượng số ký tự bot nói mỗi lượt để in quota trước khi chạy (câu chào ~110 ký tự)
BOT_CHARS_PER_TURN = 110


def log(message: str = "") -> None:
    print(message, file=sys.stderr, flush=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


# --- thống kê ---------------------------------------------------------------------------------


def clean(values: Iterable[Optional[float]]) -> list[float]:
    return [float(v) for v in values if v is not None and not math.isnan(float(v))]


def median(values: Iterable[Optional[float]]) -> Optional[float]:
    data = clean(values)
    return statistics.median(data) if data else None


def percentile(values: Iterable[Optional[float]], q: float, min_n: int = 10) -> Optional[float]:
    """Nearest-rank; None khi ít hơn `min_n` mẫu (p95 với vài mẫu chỉ là số lớn nhất)."""
    data = sorted(clean(values))
    if len(data) < min_n:
        return None
    return data[min(len(data) - 1, max(0, math.ceil(q / 100 * len(data)) - 1))]


def stats(values: Iterable[Optional[float]]) -> dict[str, Any]:
    data = clean(values)
    return {
        "n": len(data),
        "median": statistics.median(data) if data else None,
        "p90": percentile(data, 90),
        "p95": percentile(data, 95),
        "min": min(data) if data else None,
        "max": max(data) if data else None,
    }


def fmt(value: Optional[float], digits: int = 0) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def fmt_diff(before: Optional[float], after: Optional[float]) -> str:
    if before is None or after is None:
        return "-"
    diff = after - before
    pct = f" ({diff / before * 100:+.0f}%)" if before else ""
    return f"{diff:+.0f}{pct}"


# --- kết quả ----------------------------------------------------------------------------------


def result(part: str, meta: dict[str, Any], samples: list[dict], **extra: Any) -> dict[str, Any]:
    return {"schema": SCHEMA, "part": part, "meta": meta, "samples": samples, **extra}


def emit(payload: dict[str, Any]) -> None:
    """JSON ra stdout (để host lưu file), mọi log khác ra stderr."""
    print(json.dumps(payload, ensure_ascii=False, indent=1))


def load(path: Path) -> Optional[dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def base_meta(label: str, image: str) -> dict[str, Any]:
    return {"label": label, "image": image, "started_at": now_iso()}


# --- câu người gọi (cần package dự án) --------------------------------------------------------


def _clip_key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def caller_clip(text: str, sample_rate: int, cache_dir: Path) -> bytes:
    """PCM16 mono của một câu người gọi ở `sample_rate`, sinh bằng TTS đang cấu hình và cache lại.

    Cache bản gốc của provider (tên file ghi tần số gốc), đổi tần số khi đọc: phần HTTP (8 kHz) và
    LiveKit (16 kHz) dùng chung một lần sinh. Chạy lại trong cùng container không tốn quota nữa, và
    nếu cache còn thì lần "trước" / "sau" dùng đúng một bản audio.
    """
    cached = sorted(cache_dir.glob(f"caller-{_clip_key(text)}-*.pcm"))
    if cached:
        pcm, rate = cached[0].read_bytes(), int(cached[0].stem.rsplit("-", 1)[1])
    else:
        from inference.tts import create_tts_gateway
        from speech.settings import SpeechSettings

        settings = SpeechSettings()
        gateway = create_tts_gateway(settings.tts_provider, fallback=settings.tts_fallback_provider)
        produced = gateway.synthesize(text)
        if produced is None:
            raise RuntimeError("TTS không sinh được câu người gọi")
        pcm, rate = produced.pcm, produced.sample_rate
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / f"caller-{_clip_key(text)}-{rate}.pcm").write_bytes(pcm)
    if rate != sample_rate:
        from speech.audio.codec import resample

        pcm = resample(pcm, rate, sample_rate)
    return pcm


def caller_quota(lines: Iterable[str], cache_dir: Path) -> int:
    """Số ký tự TTS phải sinh cho câu người gọi (0 nếu đã có cache)."""
    return sum(
        len(text)
        for text in set(lines)
        if not any(cache_dir.glob(f"caller-{_clip_key(text)}-*.pcm"))
    )
