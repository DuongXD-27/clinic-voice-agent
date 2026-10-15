"""Đo một lượt nói như trên LiveKit: audio golden đẩy vào `ZipFormerASR.stream()` theo thời gian
thực (frame 30 ms, 16 kHz, Silero chốt câu như config/speech.yaml), so greedy với hotword.

Mỗi câu tách thời gian từ lúc khách dứt lời tới lúc có final thành: chờ im lặng (hangover Silero
+ end_silence_ms) và decode final; thêm số partial, tổng thời gian decode partial, độ trễ top 4
trên UI. Sau final, TurnController còn chờ `turn_merge_window_ms` (in ra ở đầu, không đo ở đây).

Chạy từ gốc repo, máy có model:  python scripts/turn_latency.py
"""

from __future__ import annotations

import asyncio
import os
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "eval" / "stt-bench"
sys.path[:0] = [str(ROOT / "src"), str(BENCH), str(ROOT / "scripts")]

from evaluate import load_dataset  # noqa: E402
from hotword_eval import ensure_bpe_vocab, names_of, read_pcm  # noqa: E402

from inference.asr.config import ZipFormerConfig  # noqa: E402
from inference.asr.providers.zipformer import ZipFormerASR  # noqa: E402
from speech.asr.hotwords import NO_HOTWORDS, HotwordBox, Hotwords  # noqa: E402
from speech.asr.nbest import NBestBox  # noqa: E402
from speech.audio.codec import resample  # noqa: E402

RATE = 16_000
FRAME_MS = 30
FRAME_BYTES = RATE * FRAME_MS // 1000 * 2
LEAD_MS, TAIL_MS = 600, 3000
SPEECH = yaml.safe_load((ROOT / "config" / "speech.yaml").read_text(encoding="utf-8"))


def classifier():
    model = ROOT / SPEECH["silero_vad_model_path"]
    if model.exists():
        from speech.asr.vad.silero import SileroVadClassifier

        return SileroVadClassifier(
            str(model), sample_rate=RATE, min_silence_ms=SPEECH["silero_min_silence_ms"]
        ), "silero"
    from speech.asr.vad.energy import EnergyFrameClassifier

    return EnergyFrameClassifier(), "energy (thiếu silero_vad.onnx)"


def speech_end_ms(pcm: bytes) -> float:
    """Cuối frame cuối còn to (trong 30 dB so với frame to nhất) — lúc khách dứt lời."""
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    n = FRAME_BYTES // 2
    frames = samples[: len(samples) // n * n].reshape(-1, n)
    db = 20 * np.log10(np.sqrt((frames**2).mean(axis=1)) + 1e-9)
    voiced = np.nonzero(db >= db.max() - 30)[0]
    return (voiced[-1] + 1) * FRAME_MS if len(voiced) else 0.0


class Timed(ZipFormerASR):
    def __init__(self, config: ZipFormerConfig) -> None:
        super().__init__(config)
        self.calls: list[tuple[float, float, bool]] = []  # (bắt đầu, ms, có hotword)

    def _decode_stream_hinted(self, pcm, source_rate, hints):
        start = time.perf_counter()
        try:
            return super()._decode_stream_hinted(pcm, source_rate, hints)
        finally:
            self.calls.append((start, (time.perf_counter() - start) * 1000, bool(hints)))


async def run_case(asr: Timed, pcm: bytes, hints: Hotwords) -> dict:
    vad, _ = classifier()
    box = HotwordBox()
    box.set(hints)
    nbest = NBestBox()
    audio = bytes(LEAD_MS * RATE // 1000 * 2) + pcm + bytes(TAIL_MS * RATE // 1000 * 2)
    audio = audio[: len(audio) // FRAME_BYTES * FRAME_BYTES]
    asr.calls.clear()
    t0 = time.perf_counter()

    async def frames():
        # Frame thứ i tới lúc t0 + i*30ms như mic thật; decode chặn thì frame dồn lại (backlog).
        for i in range(0, len(audio), FRAME_BYTES):
            due = t0 + (i // FRAME_BYTES + 1) * FRAME_MS / 1000
            delay = due - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
            yield audio[i : i + FRAME_BYTES]

    final_at = None
    partials = 0
    async for event in asr.stream(
        frames(),
        audio_sample_rate=RATE,
        silence_classifier=vad,
        end_silence_ms=SPEECH["vad_end_silence_ms"],
        hotwords=box,
        nbest=nbest,
    ):
        if event.is_final:
            final_at = time.perf_counter()
            break
        partials += 1
    if final_at is None:
        return {}
    tasks = nbest.take()
    nbest_ms = None
    if tasks:
        await asyncio.gather(*tasks)
        nbest_ms = (time.perf_counter() - final_at) * 1000
    end = t0 + (LEAD_MS + speech_end_ms(pcm)) / 1000
    final_start, final_ms, _ = asr.calls[-1]
    partial_calls = asr.calls[:-1]
    return {
        "sau dứt lời → final": (final_at - end) * 1000,
        "chờ im lặng (VAD)": (final_start - end) * 1000,
        "decode final": final_ms,
        "số partial": len(partial_calls),
        "decode partial (tổng)": sum(ms for _, ms, _ in partial_calls),
        "partial chậm nhất": max((ms for _, ms, _ in partial_calls), default=0.0),
        "top 4 UI sau final": nbest_ms,
        "partial phát ra": partials,
    }


def main() -> None:
    base = ZipFormerConfig()
    vocab = Path(base.bpe_vocab_path)
    if not vocab.is_absolute():
        vocab = ROOT / vocab
    ensure_bpe_vocab(vocab)
    modes = {
        "greedy": Timed(base.model_copy(update={"hotwords_enabled": False})),
        "hotword": Timed(
            base.model_copy(update={"hotwords_enabled": True, "bpe_vocab_path": str(vocab)})
        ),
    }
    _, vad_name = classifier()
    print(
        f"vad={vad_name} hangover={SPEECH['silero_min_silence_ms']}ms "
        f"end_silence={SPEECH['vad_end_silence_ms']}ms "
        f"turn_merge_window={SPEECH.get('turn_merge_window_ms', 0)}ms (sau final, không đo ở đây) "
        f"partial mỗi {300}ms beam={base.max_active_paths} score={base.hotwords_score} "
        f"cpu={os.cpu_count()} num_threads={base.num_threads}"
    )

    dataset = load_dataset(BENCH / "golden-cases.yaml")
    groups = {
        "lượt tên (hotword tên)": [
            (c, Hotwords(names_of(c), name_turn=True))
            for c in dataset.cases
            if c.category == "identity_name" and names_of(c)
        ],
        "không hotword (ngày sinh, ý định, xác nhận)": [
            (c, NO_HOTWORDS)
            for c in dataset.cases
            if c.category in ("identity_dob", "business_entity", "confirmation")
        ],
    }

    # Nạp model (session ONNX, decoder n-best) trước khi đo.
    case0, hints0 = groups["lượt tên (hotword tên)"][0]
    pcm0, rate0 = read_pcm(case0.audio_path)
    for asr in modes.values():
        asr._decode_stream_hinted(pcm0, rate0, hints0)
        asr._decode_stream_hinted(pcm0, rate0, NO_HOTWORDS)
        asr.nbest(pcm0, rate0, hints0.phrases)

    for group, cases in groups.items():
        rows: dict[str, dict[str, list[float]]] = {}
        print(f"\n### {group} ({len(cases)} câu)\n")
        print(
            "| câu | chế độ | sau dứt lời → final | chờ VAD | decode final | partial | top 4 UI |"
        )
        print("|---|---|---|---|---|---|---|")
        for case, hints in cases:
            pcm, rate = read_pcm(case.audio_path)
            if rate != RATE:
                pcm = resample(pcm, rate, RATE)
            for mode, asr in modes.items():
                result = asyncio.run(run_case(asr, pcm, hints))
                if not result:
                    print(f"| {case.id} | {mode} | không ra final | | | | |")
                    continue
                for key, value in result.items():
                    if value is not None:
                        rows.setdefault(mode, {}).setdefault(key, []).append(value)
                nb = result["top 4 UI sau final"]
                print(
                    f"| {case.id} | {mode} | {result['sau dứt lời → final']:.0f} "
                    f"| {result['chờ im lặng (VAD)']:.0f} | {result['decode final']:.0f} "
                    f"| {result['số partial']} × (max {result['partial chậm nhất']:.0f}) "
                    f"| {'' if nb is None else f'{nb:.0f}'} |"
                )
        print("\n| trung vị (ms) | " + " | ".join(modes) + " | chênh |")
        print("|---|" + "---|" * (len(modes) + 1))
        keys = list(next(iter(rows.values())).keys()) if rows else []
        for key in keys:
            med = {
                m: statistics.median(rows[m][key]) if rows.get(m, {}).get(key) else None
                for m in modes
            }
            cells = ["" if v is None else f"{v:.0f}" for v in med.values()]
            diff = (
                f"{med['hotword'] - med['greedy']:+.0f}"
                if med["hotword"] is not None and med["greedy"] is not None
                else ""
            )
            print(f"| {key} | " + " | ".join(cells) + f" | {diff} |")


if __name__ == "__main__":
    main()
