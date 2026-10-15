"""Độ trễ một lượt theo số cụm hotword (GipFormer thật, 40 câu golden).

Lượt có hotword (trừ lượt tên) decode một lần bằng sherpa-onnx beam search + cụm của lượt. Đo
greedy (lượt không hotword), beam không cụm nào, rồi beam với 6, 13 cụm và danh sách lớn hơn ghép
từ cụm mẫu (ý định, lý do hủy) và giờ đọc thành chữ.

Chạy từ gốc repo, máy có model:  python scripts/hotword_count_latency.py
"""

from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "eval" / "stt-bench"
sys.path[:0] = [str(ROOT / "src"), str(BENCH), str(ROOT / "scripts")]

from evaluate import load_dataset  # noqa: E402
from hotword_eval import ensure_bpe_vocab, read_pcm, spoken_number  # noqa: E402

from inference.asr.config import ZipFormerConfig  # noqa: E402
from inference.asr.providers.zipformer import ZipFormerASR  # noqa: E402
from speech.audio.codec import resample  # noqa: E402

SIZES = (6, 13, 30, 80, 160)
# Cụm mẫu để đủ số lượng đo (production chỉ còn hotword họ tên, xem callbot/engine/asr_hints.py).
SEED_PHRASES = (
    "ĐẶT LỊCH",
    "ĐỔI LỊCH",
    "DỜI LỊCH",
    "HỦY LỊCH",
    "XÁC NHẬN LỊCH",
    "GẶP NHÂN VIÊN",
    "BẬN",
    "CÓ VIỆC",
    "ĐI CÔNG TÁC",
    "VỀ QUÊ",
    "KHÔNG ĐẾN ĐƯỢC",
    "KHỎI RỒI",
    "ĐỠ RỒI",
    "KHÔNG CẦN KHÁM NỮA",
    "KHÁM CHỖ KHÁC",
    "BỆNH VIỆN KHÁC",
    "PHÒNG KHÁM KHÁC",
    "ĐẮT QUÁ",
    "KHÔNG ĐỦ TIỀN",
)


def phrase_pool() -> list[str]:
    pool = list(SEED_PHRASES)
    for hour in range(1, 13):
        for minute in (0, 15, 30, 45):
            for period in ("SÁNG", "CHIỀU", "TỐI"):
                clock = f"{spoken_number(hour)} GIỜ"
                pool.append(
                    f"{clock} {period}"
                    if minute == 0
                    else f"{clock} {spoken_number(minute)} {period}"
                )
    return list(dict.fromkeys(pool))


def main() -> None:
    base = ZipFormerConfig()
    vocab = Path(base.bpe_vocab_path)
    if not vocab.is_absolute():
        vocab = ROOT / vocab
    ensure_bpe_vocab(vocab)
    asr = ZipFormerASR(
        base.model_copy(update={"hotwords_enabled": True, "bpe_vocab_path": str(vocab)})
    )
    pool = phrase_pool()
    print(
        f"hotwords_score={asr._config.hotwords_score} max_active_paths={asr._config.max_active_paths}"
        f" num_threads={asr._config.num_threads} cpu={os.cpu_count()} cụm có sẵn={len(pool)}"
    )
    cases = load_dataset(BENCH / "golden-cases.yaml").cases
    audio = []
    for case in cases:
        pcm, rate = read_pcm(case.audio_path)
        if rate != asr.input_sample_rate:
            pcm = resample(pcm, rate, asr.input_sample_rate)
        audio.append(pcm)
    asr._decode_scored(audio[0], beam=False)
    asr._decode_scored(audio[0], hotwords="/".join(pool[:6]))

    modes: list[tuple[str, dict]] = [
        ("greedy (không hotword)", {"beam": False}),
        ("beam, 0 cụm", {}),
    ]
    modes += [(f"beam, {n} cụm", {"hotwords": "/".join(pool[:n])}) for n in SIZES]
    print("\n| cách decode | trung vị ms | p90 ms | max ms | so với greedy |")
    print("|---|---|---|---|---|")
    greedy_median = None
    for name, kwargs in modes:
        times = []
        for pcm in audio:
            start = time.perf_counter()
            asr._decode_scored(pcm, **kwargs)
            times.append((time.perf_counter() - start) * 1000)
        times.sort()
        median = statistics.median(times)
        greedy_median = greedy_median or median
        p90 = times[int(len(times) * 0.9) - 1]
        print(
            f"| {name} | {median:.0f} | {p90:.0f} | {times[-1]:.0f} | +{median - greedy_median:.0f} |"
        )


if __name__ == "__main__":
    main()
