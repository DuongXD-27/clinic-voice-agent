"""Đo độ trễ lượt tên (GipFormer thật, bộ golden): từng bước sau khi khách nói xong tốn bao lâu.

Lượt tên có hotword tên hồ sơ (`guard_one_word`): decode có hotword, decode không hotword, rồi
nếu hai bản lệch 1 từ thì tính thêm top N thô (`_accept_hinted`). Sau final còn top 4 hiện trên
UI chạy nền. In trung vị/max từng bước và tổng của `_decode_stream_hinted` như lúc chạy thật.

Chạy từ gốc repo, máy có model:  python scripts/name_turn_latency.py
"""

from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "eval" / "stt-bench"
sys.path[:0] = [str(ROOT / "src"), str(BENCH), str(ROOT / "scripts")]

from evaluate import load_dataset  # noqa: E402
from hotword_eval import ensure_bpe_vocab, names_of, read_pcm  # noqa: E402

from inference.asr.config import ZipFormerConfig  # noqa: E402
from inference.asr.providers.zipformer import ZipFormerASR  # noqa: E402
from speech.asr.hotwords import Hotwords  # noqa: E402
from speech.audio.codec import resample  # noqa: E402


def timed(fn, *args, **kwargs) -> tuple[object, float]:
    start = time.perf_counter()
    result = fn(*args, **kwargs)
    return result, (time.perf_counter() - start) * 1000


def main() -> None:
    base = ZipFormerConfig()
    vocab = Path(base.bpe_vocab_path)
    if not vocab.is_absolute():
        vocab = ROOT / vocab
    ensure_bpe_vocab(vocab)
    config = base.model_copy(update={"hotwords_enabled": True, "bpe_vocab_path": str(vocab)})
    asr = ZipFormerASR(config)
    # Nhánh cũ (sherpa decode 2-3 lần, mỗi lần chạy lại encoder) để so tốc độ và chữ.
    old = ZipFormerASR(config)
    old._shared_encoder = False
    greedy = ZipFormerASR(base.model_copy(update={"hotwords_enabled": False}))
    print(
        f"hotwords_score={config.hotwords_score} max_active_paths={config.max_active_paths} "
        f"accept_top_k={config.hotwords_accept_top_k} nbest_top_k={config.nbest_top_k} "
        f"num_threads={config.num_threads} cpu={os.cpu_count()}"
    )

    dataset = load_dataset(BENCH / "golden-cases.yaml")
    cases = [c for c in dataset.cases if c.category == "identity_name" and names_of(c)]
    steps: dict[str, list[float]] = {}

    def add(name: str, ms: float) -> None:
        steps.setdefault(name, []).append(ms)

    # Cuộc gọi mới trên LiveKit = process mới, prewarm cũ chỉ nạp greedy: lượt tên đầu tiên và
    # lượt hỏi ý định đầu tiên tự nạp model. So với process đã gọi `warm_up()`.
    pcm0, rate0 = read_pcm(cases[0].audio_path)
    hints0 = Hotwords(names_of(cases[0]), guard_one_word=True)
    intent0 = Hotwords(("ĐẶT LỊCH", "ĐỔI LỊCH", "HỦY LỊCH"))
    for label, warm in (("prewarm cũ (chỉ greedy)", False), ("prewarm mới (warm_up)", True)):
        fresh = ZipFormerASR(config)
        _, load = timed(fresh._decode_stream_scored, pcm0, rate0)
        if warm:
            _, extra = timed(fresh.warm_up)
            load += extra
        _, first_name = timed(fresh._decode_stream_hinted, pcm0, rate0, hints0)
        _, first_intent = timed(fresh._decode_stream_hinted, pcm0, rate0, intent0)
        print(
            f"{label}: prewarm {load:.0f}ms | lượt tên ĐẦU TIÊN {first_name:.0f}ms"
            f" | lượt hỏi ý định ĐẦU TIÊN {first_intent:.0f}ms"
        )

    # Nạp model trước (lần đầu tạo session ONNX), không tính vào số đo.
    pcm0, rate0 = read_pcm(cases[0].audio_path)
    asr._decode_stream_hinted(pcm0, rate0, Hotwords(names_of(cases[0]), guard_one_word=True))
    old._decode_stream_hinted(pcm0, rate0, Hotwords(names_of(cases[0]), guard_one_word=True))
    asr.nbest(pcm0, rate0, names_of(cases[0]))
    greedy._decode_stream_scored(pcm0, rate0)

    print(
        "\n| câu | giây audio | greedy | có hotword | không hotword | top 10 thô | tổng lượt tên"
        " | top 4 UI | cũ: tổng | chữ mới = cũ |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|")
    for case in cases:
        pcm, rate = read_pcm(case.audio_path)
        hints = Hotwords(names_of(case), guard_one_word=True)
        model_pcm = (
            pcm if rate == asr.input_sample_rate else resample(pcm, rate, asr.input_sample_rate)
        )
        seconds = len(model_pcm) / 2 / asr.input_sample_rate
        _, g = timed(greedy._decode_scored, model_pcm)
        _, b = timed(asr._decode_scored, model_pcm, hotwords="/".join(hints.phrases))
        _, p = timed(asr._decode_scored, model_pcm)
        _, t = timed(asr._nbest_at_model_rate, model_pcm, config.hotwords_accept_top_k)
        # Từng phần của đường mới: encoder một lần, hai beam riêng, hai beam gộp batch.
        nb = asr._get_nbest()
        samples = np.frombuffer(model_pcm, dtype=np.int16).astype(np.float32) / 32768.0
        frames, enc = timed(nb.encode, samples)
        beam, score = config.max_active_paths, config.hotwords_score
        searches = [
            (max(1, config.nbest_top_k), hints.phrases, score, beam),
            (max(1, config.hotwords_accept_top_k), (), 0, beam),
        ]
        cache: dict = {}
        _, s1 = timed(nb.search, frames, *searches[0], cache)
        _, s2 = timed(nb.search, frames, *searches[1], cache)
        _, sm = timed(nb.search_many, frames, searches, {})
        new, total = timed(asr._decode_stream_hinted, pcm, rate, hints)
        _, ui = timed(asr.nbest, pcm, rate, hints.phrases)
        before, old_total = timed(old._decode_stream_hinted, pcm, rate, hints)
        same = "khớp" if new.text == before.text else "LỆCH"
        for name, ms in (
            ("greedy", g),
            ("có hotword", b),
            ("không hotword", p),
            ("top 10 thô", t),
            ("encoder", enc),
            ("beam có hotword (riêng)", s1),
            ("beam không hotword (riêng, chung cache)", s2),
            ("hai beam gộp batch", sm),
            ("tổng lượt tên", total),
            ("top 4 UI (lấy lại)", ui),
            ("cũ: tổng lượt tên", old_total),
        ):
            add(name, ms)
        print(
            f"| {case.id} | {seconds:.1f} | {g:.0f} | {b:.0f} | {p:.0f} | {t:.0f} | {total:.0f} | {ui:.0f} | {old_total:.0f} | {same} |"
        )

    print("\n| bước | trung vị ms | max ms |")
    print("|---|---|---|")
    for name, values in steps.items():
        print(f"| {name} | {statistics.median(values):.0f} | {max(values):.0f} |")


if __name__ == "__main__":
    main()
