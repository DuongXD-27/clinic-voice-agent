"""Đo hotword theo lượt trên GipFormer thật (bộ golden 40 câu, eval/stt-bench).

So 4 cách decode cùng một file audio:
- greedy: như production hiện tại (ZIPFORMER_HOTWORDS_ENABLED=false).
- beam: modified_beam_search, chưa có hotword — đo riêng việc đổi cách decode có làm tụt không.
- hint: lượt hỏi tên, hotword = đúng tên trong hồ sơ (khách nói đúng tên mình).
- trap: lượt hỏi tên, hồ sơ là "NGUYỄN VĂN A" nhưng khách nói tên khác (STT_ID_07 "Anh",
  STT_ID_08 "An"...). Đo xem hotword có KÉO tên khác về tên hồ sơ không (rủi ro SF-03).

Chạy từ gốc repo, máy có model (assets/zipformer/ như config/asr.yaml):
    python scripts/hotword_eval.py
    python scripts/hotword_eval.py --score 1.0 --score 1.5 --score 2.0

Thiếu bpe.vocab thì tự tải bpe.model (huggingface_hub) và xuất vocab (sentencepiece).
Audio golden là audio thu sẵn, không có PII thật; kết quả ghi eval/stt-bench/results/.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "eval" / "stt-bench"
sys.path[:0] = [str(ROOT / "src"), str(BENCH)]

from adapters.base import STTResult  # noqa: E402
from evaluate import evaluate_case, load_dataset  # noqa: E402

from inference.asr.config import ZipFormerConfig  # noqa: E402
from inference.asr.providers.zipformer import ZipFormerASR  # noqa: E402
from speech.asr.hotwords import NO_HOTWORDS, Hotwords  # noqa: E402

GIPFORMER_REPO = "g-group-ai-lab/gipformer1.5-68M-rnnt"
TRAP_PROFILE = "NGUYỄN VĂN A"


@dataclass
class Row:
    case_id: str
    category: str
    mode: str
    score: float | None
    hotwords: str
    reference: str
    prediction: str
    critical_pass: bool
    wer: float | None
    pulled_to_profile: bool
    decode_ms: float


def ensure_bpe_vocab(vocab_path: Path) -> None:
    if vocab_path.exists():
        return
    model_path = vocab_path.with_suffix(".model")
    if not model_path.exists():
        from huggingface_hub import hf_hub_download  # pip install huggingface_hub

        hf_hub_download(GIPFORMER_REPO, "bpe.model", local_dir=str(model_path.parent))
    import sentencepiece as spm  # pip install sentencepiece

    sp = spm.SentencePieceProcessor(model_file=str(model_path))
    with vocab_path.open("w", encoding="utf-8") as out:
        for i in range(sp.get_piece_size()):
            out.write(f"{sp.id_to_piece(i)}\t{sp.get_score(i)}\n")
    print(f"Đã xuất {vocab_path}")


def read_pcm(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as w:
        return w.readframes(w.getnframes()), w.getframerate()


def decode(asr: ZipFormerASR, pcm: bytes, rate: int, hints: Hotwords) -> tuple[str, float]:
    start = time.perf_counter()
    if asr.supports_hotwords:
        text = asr._decode_stream_hinted(pcm, rate, hints).text
    else:
        text = asr._decode_stream_scored(pcm, rate).text
    return text, (time.perf_counter() - start) * 1000


def names_of(case) -> tuple[str, ...]:
    return tuple(e.value.upper() for e in case.critical_entities if e.type == "person_name")


def run(scores: list[float], out_dir: Path) -> Path:
    base = ZipFormerConfig()
    vocab = Path(base.bpe_vocab_path)
    if not vocab.is_absolute():
        vocab = ROOT / vocab
    ensure_bpe_vocab(vocab)
    greedy = ZipFormerASR(base.model_copy(update={"hotwords_enabled": False}))
    beams = {
        score: ZipFormerASR(
            base.model_copy(
                update={
                    "hotwords_enabled": True,
                    "bpe_vocab_path": str(vocab),
                    "hotwords_score": score,
                }
            )
        )
        for score in scores
    }
    dataset = load_dataset(BENCH / "golden-cases.yaml")
    rows: list[Row] = []

    def add(case, mode, score, hints, asr, pcm, rate) -> None:
        text, ms = decode(asr, pcm, rate, hints)
        scored = evaluate_case(case, STTResult(text=text, latency_ms=ms))
        reference_names = names_of(case)
        rows.append(
            Row(
                case_id=case.id,
                category=case.category,
                mode=mode,
                score=score,
                hotwords="/".join(hints.phrases),
                reference=case.reference,
                prediction=text,
                critical_pass=scored.critical_entities_pass and not scored.hallucination,
                wer=scored.wer.wer,
                pulled_to_profile=mode == "trap"
                and f" {TRAP_PROFILE} " in f" {text.upper()} "
                and TRAP_PROFILE not in reference_names,
                decode_ms=ms,
            )
        )

    for case in dataset.cases:
        pcm, rate = read_pcm(case.audio_path)
        add(case, "greedy", None, NO_HOTWORDS, greedy, pcm, rate)
        for score, asr in beams.items():
            add(case, "beam", score, NO_HOTWORDS, asr, pcm, rate)
            names = names_of(case)
            if case.category != "identity_name" or not names:
                continue  # ngày sinh và câu xác nhận: không bao giờ có hotword
            add(case, "hint", score, Hotwords(names, guard_one_word=True), asr, pcm, rate)
            if TRAP_PROFILE not in names:
                add(case, "trap", score, Hotwords((TRAP_PROFILE,), True), asr, pcm, rate)

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    csv_path = out_dir / f"hotword-{stamp}.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(Row.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(r.__dict__ for r in rows)
    summary = summarize(rows)
    (out_dir / f"hotword-{stamp}.md").write_text(summary, encoding="utf-8")
    print(summary)
    print(f"Chi tiết: {csv_path}")
    return csv_path


def summarize(rows: list[Row]) -> str:
    lines = [
        "| Cách decode | Điểm | Số câu | Đúng entity | WER TB | Bị kéo về hồ sơ | ms TB | ms p95 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    groups: dict[tuple[str, float | None], list[Row]] = {}
    for row in rows:
        groups.setdefault((row.mode, row.score), []).append(row)
    for (mode, score), group in groups.items():
        wers = [r.wer for r in group if r.wer is not None]
        ms = sorted(r.decode_ms for r in group)
        p95 = ms[min(len(ms) - 1, int(round(0.95 * (len(ms) - 1))))]
        pulled = sum(r.pulled_to_profile for r in group) if mode == "trap" else "—"
        lines.append(
            f"| {mode} | {score if score is not None else '—'} | {len(group)} "
            f"| {sum(r.critical_pass for r in group)}/{len(group)} "
            f"| {statistics.mean(wers) if wers else 0:.3f} | {pulled} "
            f"| {statistics.mean(ms):.0f} | {p95:.0f} |"
        )
    changed = [
        f"- {r.case_id} [{r.mode} {r.score}] {r.reference} → {r.prediction}"
        for r in rows
        if r.mode in ("hint", "trap") and (not r.critical_pass or r.pulled_to_profile)
    ]
    if changed:
        lines += ["", "Câu tên còn sai / bị kéo:", *changed]
    # Từng câu tên qua mọi cách decode: thấy hotword sửa được / làm hỏng câu nào so với greedy.
    by_case: dict[str, list[Row]] = {}
    for row in rows:
        if row.category == "identity_name":
            by_case.setdefault(row.case_id, []).append(row)
    if by_case:
        lines += ["", "Từng câu tên (✓ đúng entity, ✗ sai):"]
        for case_id, group in by_case.items():
            lines.append(f"- {case_id}: {group[0].reference}")
            for r in group:
                mark = "✓" if r.critical_pass else "✗"
                label = r.mode if r.score is None else f"{r.mode} {r.score}"
                lines.append(f"  - {label}: {mark} {r.prediction}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--score", type=float, action="append", help="hotwords_score (lặp được)")
    parser.add_argument("--out", type=Path, default=BENCH / "results")
    args = parser.parse_args()
    run(args.score or [1.5], args.out)


if __name__ == "__main__":
    main()
