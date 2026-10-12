"""Trace hotword trên từng câu tên của bộ golden (GipFormer thật): vì sao câu sai vẫn sai.

Với mỗi câu tên và mỗi cấu hình (điểm hotword, số beam), in:
- cách sentencepiece cắt cụm hotword thành token, và token nào không có trong tokens.txt
  (thiếu token thì sherpa-onnx bỏ qua cả cụm, hotword không có tác dụng);
- bản decode không hotword, bản có hotword TRƯỚC khi qua chặn 1 từ, khoảng cách từ, và bản
  được nhận sau chặn (đúng logic `ZipFormerASR._decode_stream_hinted`);
- top 4 phương án (không hotword) của `TransducerNBest` — phương án 1 phải trùng bản sherpa-onnx
  beam không hotword, nếu không là bộ giải mã top N sai.

Chạy từ gốc repo, máy có model:  python scripts/hotword_trace.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "eval" / "stt-bench"
sys.path[:0] = [str(ROOT / "src"), str(BENCH), str(ROOT / "scripts")]

from evaluate import load_dataset  # noqa: E402
from hotword_eval import TRAP_PROFILE, ensure_bpe_vocab, names_of, read_pcm  # noqa: E402

from inference.asr.config import ZipFormerConfig  # noqa: E402
from inference.asr.providers.transducer_nbest import TransducerNBest  # noqa: E402
from inference.asr.providers.zipformer import ZipFormerASR  # noqa: E402
from speech.asr.hotwords import word_distance  # noqa: E402
from speech.audio.codec import resample  # noqa: E402

GRID = ((1.5, 4), (3.0, 4), (5.0, 4), (3.0, 8), (5.0, 8), (8.0, 8))


def main() -> None:
    base = ZipFormerConfig()
    vocab = Path(base.bpe_vocab_path)
    if not vocab.is_absolute():
        vocab = ROOT / vocab
    ensure_bpe_vocab(vocab)

    import sentencepiece as spm

    sp = spm.SentencePieceProcessor(model_file=str(vocab.with_suffix(".model")))
    tokens = {line.split()[0] for line in Path(base.tokens_path).read_text("utf-8").splitlines()}

    dataset = load_dataset(BENCH / "golden-cases.yaml")
    cases = [c for c in dataset.cases if c.category == "identity_name" and names_of(c)]

    print("## Token hóa cụm hotword")
    for phrase in sorted({n for c in cases for n in names_of(c)} | {TRAP_PROFILE}):
        pieces = sp.encode(phrase, out_type=str)
        missing = [p for p in pieces if p not in tokens]
        print(f"- {phrase}: {' '.join(pieces)}" + (f"  THIẾU TOKEN: {missing}" if missing else ""))

    recognizers = {
        (score, paths): ZipFormerASR(
            base.model_copy(
                update={
                    "hotwords_enabled": True,
                    "bpe_vocab_path": str(vocab),
                    "hotwords_score": score,
                    "max_active_paths": paths,
                }
            )
        )
        for score, paths in GRID
    }

    nbest = TransducerNBest(
        encoder=base.encoder_path,
        decoder=base.decoder_path,
        joiner=base.joiner_path,
        tokens=base.tokens_path,
    )

    print("\n## Từng câu tên (plain = beam không hotword, biased = có hotword trước chặn)")
    for case in cases:
        pcm, rate = read_pcm(case.audio_path)
        asr0 = next(iter(recognizers.values()))
        if rate != asr0.input_sample_rate:
            pcm = resample(pcm, rate, asr0.input_sample_rate)
        hint_sets = [("hint", names_of(case))]
        if TRAP_PROFILE not in names_of(case):
            hint_sets.append(("trap", (TRAP_PROFILE,)))
        print(f"\n### {case.id}: {case.reference}")
        top = nbest.nbest(np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0, 4)
        sherpa = asr0._decode_scored(pcm).text
        same = "khớp" if top and top[0].text == sherpa else f"LỆCH (sherpa: {sherpa})"
        print(f"- top 4 không hotword ({same}):")
        for rank, hyp in enumerate(top, 1):
            print(f"  {rank}. {hyp.text}  {hyp.log_prob:.2f} · {hyp.share:.0%}")
        for kind, phrases in hint_sets:
            print(f"- {kind} hotword = {'/'.join(phrases)}")
            for (score, paths), asr in recognizers.items():
                plain = asr._decode_scored(pcm).text
                biased = asr._decode_scored(pcm, hotwords="/".join(phrases)).text
                dist = word_distance(plain, biased)
                kept = biased if plain == biased or dist <= 1 else plain
                verdict = "nhận biased" if kept == biased else "CHẶN, giữ plain"
                print(
                    f"  - điểm {score}, beam {paths}: plain={plain} | biased={biased}"
                    f" | lệch {dist} từ → {verdict}"
                )


if __name__ == "__main__":
    main()
