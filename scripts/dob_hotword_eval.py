"""Đo hotword CHUNG cho lượt ngày sinh trên GipFormer (10 câu ngày sinh của bộ golden, có nhiễu).

Hotword chung = mọi cách đọc ngày / tháng / năm sinh mà rule-base (`extraction/spoken_numbers.py`,
`extraction/dob.py`) đọc được, KHÔNG lấy từ hồ sơ: năm nào, ngày nào trong danh sách cũng được
cộng như nhau, chỉ đẩy model về phía "nghe ra số" thay vì chữ rác.

Golden sạch gần như đã đúng hết, nên mỗi câu được trộn nhiễu giọng người (babble: 3 luồng câu
golden khác cộng lại) ở vài mức SNR. Kết quả chấm bằng chính `extract_dob`:
- đúng: ra đúng giá trị như câu tham chiếu (kể cả INVALID với câu "hình như", 31/02);
- sai ngày: ra một ngày KHÁC (nguy hiểm: đi tiếp vào Verifier);
- không đọc được: ra INVALID / không có (an toàn: hỏi lại).

Cách tính điểm (`--mode`):
- `token`: như hiện tại, mỗi token khớp cụm +score (cụm nhiều token được cộng nhiều hơn);
- `phrase`: mỗi cụm khớp trọn được cộng ~score bất kể số token (cú pháp "CỤM :điểm/token").

Chạy từ gốc repo, máy có model:
    python scripts/dob_hotword_eval.py
    python scripts/dob_hotword_eval.py --snr 10 --snr 5 --snr 0 --score 1.5 --score 3.0
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "eval" / "stt-bench"
sys.path[:0] = [str(ROOT / "src"), str(BENCH), str(ROOT / "scripts")]

from evaluate import load_dataset  # noqa: E402
from hotword_eval import ensure_bpe_vocab, read_pcm  # noqa: E402

from callbot.engine.asr_hints import spoken_number  # noqa: E402
from callbot.engine.extraction.dob import extract_dob  # noqa: E402
from inference.asr.config import ZipFormerConfig  # noqa: E402
from inference.asr.providers.transducer_nbest import bpe_encode, load_bpe_vocab  # noqa: E402
from inference.asr.providers.zipformer import ZipFormerASR  # noqa: E402
from speech.audio.codec import resample  # noqa: E402

TODAY = date(2026, 10, 12)
_DIGITS = ("KHÔNG", "MỘT", "HAI", "BA", "BỐN", "NĂM", "SÁU", "BẢY", "TÁM", "CHÍN")


def number_forms(n: int) -> set[str]:
    """Các cách đọc số 1-99 mà `parse_number` nhận: chuẩn, "tư"/"bốn", nói tắt "hai mốt"."""
    forms = {spoken_number(n)}
    tens, unit = divmod(n, 10)
    if tens >= 2 and unit:
        short = {1: "MỐT", 4: "TƯ", 5: "LĂM"}.get(unit, _DIGITS[unit])
        forms.add(f"{_DIGITS[tens]} {short}")
        if unit == 4:
            forms |= {f"{_DIGITS[tens]} MƯƠI BỐN", f"{_DIGITS[tens]} BỐN"}
    if n == 4:
        forms.add("TƯ")
    return forms


def year_forms(year: int) -> set[str]:
    forms: set[str] = set()
    digits = " ".join(_DIGITS[int(d)] for d in str(year))
    forms.add(digits)  # "MỘT CHÍN BẢY TÁM", "HAI KHÔNG KHÔNG TƯ" (thêm dạng tư dưới)
    century, rest = divmod(year, 100)
    for thousand in ("NGHÌN", "NGÀN"):
        if century == 19:
            tail = f"CHÍN TRĂM {spoken_number(rest)}" if rest else "CHÍN TRĂM"
            if 0 < rest < 10:
                tail = f"CHÍN TRĂM LINH {_DIGITS[rest]}"
            forms.add(f"MỘT {thousand} {tail}")
        else:
            if rest == 0:
                forms.add(f"HAI {thousand}")
            elif rest < 10:
                forms |= {
                    f"HAI {thousand} LINH {_DIGITS[rest]}",
                    f"HAI {thousand} LẺ {_DIGITS[rest]}",
                }
            else:
                forms.add(f"HAI {thousand} {spoken_number(rest)}")
    if century == 19 and rest >= 10:
        forms |= number_forms(rest)  # "BẢY MƯƠI TÁM", "BẢY TÁM"
        forms.add(f"MỘT CHÍN {spoken_number(rest)}")  # đọc cặp: "một chín bảy mươi tám"
    return forms


def dob_phrases(first_year: int = 1930, last_year: int = 2010) -> list[str]:
    phrases: set[str] = set()
    for day in range(1, 32):
        for form in number_forms(day):
            phrases.add(f"NGÀY {form}")
            if day <= 10:
                phrases |= {f"MÙNG {form}", f"MỒNG {form}"}
    for month in range(1, 13):
        for form in number_forms(month):
            phrases.add(f"THÁNG {form}")
    for year in range(first_year, last_year + 1):
        for form in year_forms(year):
            phrases.add(f"NĂM {form}")
    return sorted(phrases)


def hotword_string(phrases: list[str], score: float, mode: str, vocab: dict[str, float]) -> str:
    if mode == "token":
        return "/".join(phrases)
    # Điểm mỗi token = score / số token, nên cụm khớp trọn được ~score bất kể dài ngắn.
    lines = []
    for phrase in phrases:
        tokens = len(bpe_encode(phrase, vocab)) or 1
        lines.append(f"{phrase} :{score / tokens:.3f}")
    return "/".join(lines)


def babble(clips: list[np.ndarray], seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    streams = [
        np.concatenate(
            [
                clips[i] / max(np.sqrt(np.mean(clips[i] ** 2)), 1.0)
                for i in rng.permutation(len(clips))
            ]
        )
        for _ in range(3)
    ]
    length = min(len(s) for s in streams)
    return sum(s[:length] for s in streams)


def mix(speech: np.ndarray, noise: np.ndarray, snr_db: float | None, seed: int) -> np.ndarray:
    if snr_db is None:
        return speech
    start = int(np.random.default_rng(seed).integers(0, len(noise) - len(speech)))
    segment = noise[start : start + len(speech)]
    gain = (
        np.sqrt(np.mean(speech**2)) / max(np.sqrt(np.mean(segment**2)), 1e-6) / 10 ** (snr_db / 20)
    )
    return np.clip(speech + gain * segment, -32768, 32767)


def outcome(value, expected) -> str:
    if value == expected:
        return "đúng"
    return "sai ngày" if isinstance(value, date) else "không đọc"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--snr", type=float, action="append", help="dB; lặp được (mặc định sạch, 10, 5, 0)"
    )
    parser.add_argument("--score", type=float, action="append", help="mặc định 1.5, 3.0")
    parser.add_argument("--mode", action="append", choices=["token", "phrase"])
    args = parser.parse_args()
    snrs: list[float | None] = args.snr or [None, 10.0, 5.0, 0.0]
    scores = args.score or [1.5, 3.0]
    modes = args.mode or ["token", "phrase"]

    base = ZipFormerConfig()
    vocab_path = Path(base.bpe_vocab_path)
    if not vocab_path.is_absolute():
        vocab_path = ROOT / vocab_path
    ensure_bpe_vocab(vocab_path)
    vocab = load_bpe_vocab(str(vocab_path))
    asr = ZipFormerASR(
        base.model_copy(update={"hotwords_enabled": True, "bpe_vocab_path": str(vocab_path)})
    )
    greedy = ZipFormerASR(base.model_copy(update={"hotwords_enabled": False}))
    phrases = dob_phrases()
    print(f"{len(phrases)} cụm hotword ngày sinh, vd: {', '.join(phrases[:3])} ... {phrases[-1]}")

    dataset = load_dataset(BENCH / "golden-cases.yaml")
    cases = [c for c in dataset.cases if c.category == "identity_dob"]
    others = [read_pcm(c.audio_path) for c in dataset.cases if c.category != "identity_dob"]
    noise = babble([np.frombuffer(p, dtype=np.int16).astype(np.float64) for p, _ in others])

    configs: list[tuple[str, ZipFormerASR, str]] = [
        ("greedy", greedy, ""),
        ("beam, không hotword", asr, ""),
    ]
    for mode in modes:
        for score in scores:
            configs.append((f"{mode} {score}", asr, hotword_string(phrases, score, mode, vocab)))

    rows: dict[str, list[tuple[str, float]]] = {name: [] for name, _, _ in configs}
    examples: list[str] = []
    for snr in snrs:
        for i, case in enumerate(cases):
            pcm, rate = read_pcm(case.audio_path)
            speech = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
            noisy = mix(speech, noise, snr, seed=i).astype(np.int16).tobytes()
            audio = resample(noisy, rate, 16000)
            expected = extract_dob(case.reference, TODAY).value
            for name, model, hotwords in configs:
                start = time.perf_counter()
                text = model._decode_scored(audio, hotwords=hotwords).text
                ms = (time.perf_counter() - start) * 1000
                result = outcome(extract_dob(text, TODAY).value, expected)
                rows[name].append((result, ms))
                if result != "đúng":
                    examples.append(
                        f"- [{'sạch' if snr is None else f'{snr:g} dB'}] {case.id} {name}: {case.reference} → {text}"
                    )

    total = len(cases) * len(snrs)
    print(
        f"\nSNR: {', '.join('sạch' if s is None else f'{s:g} dB' for s in snrs)} — {total} lượt mỗi cấu hình"
    )
    print("| Cấu hình | Đúng | Sai ngày (nguy hiểm) | Không đọc (hỏi lại) | ms TB |")
    print("|---|---|---|---|---|")
    for name, results in rows.items():
        count = {k: sum(r == k for r, _ in results) for k in ("đúng", "sai ngày", "không đọc")}
        print(
            f"| {name} | {count['đúng']}/{total} | {count['sai ngày']} | {count['không đọc']} "
            f"| {statistics.mean(ms for _, ms in results):.0f} |"
        )
    print("\nCâu sai:")
    print("\n".join(examples))


if __name__ == "__main__":
    main()
