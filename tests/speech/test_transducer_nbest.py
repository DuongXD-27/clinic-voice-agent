"""Top N phương án ASR (inference/asr/providers/transducer_nbest.py) và đường gửi lên trang demo."""

import asyncio
import math
from typing import AsyncIterator, Iterable

import numpy as np
import pytest

from inference.asr.config import ZipFormerConfig
from inference.asr.providers.transducer_nbest import NBestHyp, beam_search, to_nbest
from inference.asr.providers.zipformer import ZipFormerASR
from speech.asr.nbest import NBestBox
from speech.asr.vad.streaming import FRAME_MS

_FRAME_BYTES = int(8000 * FRAME_MS / 1000) * 2
_LOUD = b"\x00\x10" * (_FRAME_BYTES // 2)
_SILENT = b"\x00\x00" * (_FRAME_BYTES // 2)

# Vocab: 0 = blank, 1 = "▁XIN", 2 = "▁CHÀO", 3 = "▁CHAO".
_SYMBOLS = {0: "<blk>", 1: "▁XIN", 2: "▁CHÀO", 3: "▁CHAO"}


def _search(frame_logits: list[list[float]], beam: int = 4):
    """Logit chỉ phụ thuộc frame (frame mang chỉ số của nó ở cột 0)."""
    frames = np.array([[i] for i in range(len(frame_logits))], dtype=np.float32)

    def join(enc, dec):
        return np.array([frame_logits[int(row[0])] for row in enc])

    return beam_search(
        frames,
        decode=lambda contexts: np.zeros((len(contexts), 1)),
        join=join,
        context_size=2,
        beam=beam,
    )


def test_beam_search_ranks_hypotheses_by_log_prob() -> None:
    hyps = _search([[0.0, 5.0, 0.0, 0.0], [0.0, 0.0, 4.0, 3.0], [5.0, 0.0, 0.0, 0.0]])

    assert hyps[0][0] == (1, 2)
    assert [ys for ys, _ in hyps[:2]] == [(1, 2), (1, 3)]
    scores = [score for _, score in hyps]
    assert scores == sorted(scores, reverse=True)
    assert all(score <= 0 for score in scores)


def test_beam_search_merges_identical_token_sequences() -> None:
    """Hai đường cùng ra "XIN" (XIN rồi blank, blank rồi XIN) cộng xác suất, không đứng riêng."""
    hyps = _search([[0.0, 0.0, -9.0, -9.0], [0.0, 0.0, -9.0, -9.0]], beam=8)

    sequences = [ys for ys, _ in hyps]
    assert len(sequences) == len(set(sequences))
    best = dict(hyps)
    assert best[(1,)] > best[(1, 1)]


def test_to_nbest_joins_pieces_and_shares_sum_to_one() -> None:
    hyps = [((1, 2), -0.5), ((1, 3), -1.5), ((1, 2), -2.0), ((1,), -3.0)]

    result = to_nbest(hyps, _SYMBOLS, 2)

    assert [h.text for h in result] == ["XIN CHÀO", "XIN CHAO"]
    assert result[0].log_prob == -0.5
    assert math.isclose(sum(h.share for h in result), 1.0, abs_tol=1e-3)
    assert result[0].share > result[1].share


def test_to_nbest_empty() -> None:
    assert to_nbest([], _SYMBOLS, 4) == []


@pytest.fixture
def _inline_threads(monkeypatch):
    async def inline(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", inline)


class _Recognizer:
    class _Stream:
        result = None

        def accept_waveform(self, sample_rate, samples) -> None:
            pass

    def create_stream(self, hotwords=None):
        return self._Stream()

    def decode_stream(self, stream) -> None:
        import types

        stream.result = types.SimpleNamespace(text="XIN CHÀO", ys_log_probs=[-0.1])


async def _aiter(frames: Iterable[bytes]) -> AsyncIterator[bytes]:
    for frame in frames:
        yield frame


async def _final_tasks(top_k: int) -> tuple[list, NBestBox]:
    config = ZipFormerConfig(
        encoder_path="e", decoder_path="d", joiner_path="j", tokens_path="t", nbest_top_k=top_k
    )
    asr = ZipFormerASR(config, recognizer=_Recognizer())
    calls: list[int] = []

    def fake_nbest(pcm: bytes, rate: int) -> list[NBestHyp]:
        calls.append(rate)
        return [NBestHyp("XIN CHÀO", -0.2, 0.8), NBestHyp("XIN CHAO", -1.6, 0.2)]

    asr.nbest = fake_nbest  # type: ignore[method-assign]
    box = NBestBox()
    events = [
        event
        async for event in asr.stream(
            _aiter([_LOUD] * 20 + [_SILENT] * 25),
            end_silence_ms=600,
            min_emit_interval_ms=0,
            min_decode_ms=0,
            nbest=box,
        )
    ]
    assert [e.text for e in events if e.is_final] == ["XIN CHÀO"]
    assert any(not e.is_final for e in events)
    return calls, box


async def test_zipformer_computes_nbest_for_finals_only(_inline_threads) -> None:
    calls, box = await _final_tasks(top_k=4)

    tasks = box.take()
    assert len(tasks) == 1
    assert [h.text for h in await tasks[0]] == ["XIN CHÀO", "XIN CHAO"]
    assert calls == [8000]
    assert box.take() == []


async def test_zipformer_skips_nbest_when_disabled(_inline_threads) -> None:
    calls, box = await _final_tasks(top_k=0)

    assert box.take() == [] and calls == []
