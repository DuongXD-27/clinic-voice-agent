"""Top N phương án ASR (inference/asr/providers/transducer_nbest.py) và đường gửi lên trang demo."""

import asyncio
import math
from typing import AsyncIterator, Iterable

import numpy as np
import pytest

from inference.asr.config import ZipFormerConfig
from inference.asr.providers.transducer_nbest import (
    ContextGraph,
    NBest,
    NBestHyp,
    beam_search,
    bpe_encode,
    to_nbest,
)
from inference.asr.providers.zipformer import ZipFormerASR
from speech.asr.nbest import NBestBox
from speech.asr.vad.streaming import FRAME_MS

_FRAME_BYTES = int(8000 * FRAME_MS / 1000) * 2
_LOUD = b"\x00\x10" * (_FRAME_BYTES // 2)
_SILENT = b"\x00\x00" * (_FRAME_BYTES // 2)

# Vocab: 0 = blank, 1 = "▁XIN", 2 = "▁CHÀO", 3 = "▁CHAO".
_SYMBOLS = {0: "<blk>", 1: "▁XIN", 2: "▁CHÀO", 3: "▁CHAO"}


def _search(frame_logits: list[list[float]], beam: int = 4, context=None):
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
        context=context,
    )


def test_beam_search_ranks_hypotheses_by_log_prob() -> None:
    hyps = _search([[0.0, 5.0, 0.0, 0.0], [0.0, 0.0, 4.0, 3.0], [5.0, 0.0, 0.0, 0.0]])

    assert hyps[0][0] == (1, 2)
    assert [h.ys for h in hyps[:2]] == [(1, 2), (1, 3)]
    scores = [h.score for h in hyps]
    assert scores == sorted(scores, reverse=True)
    assert all(score <= 0 for score in scores)
    assert all(bonus == 0 for _, _, bonus, _ in hyps)


def test_beam_search_merges_identical_token_sequences() -> None:
    """Hai đường cùng ra "XIN" (XIN rồi blank, blank rồi XIN) cộng xác suất, không đứng riêng."""
    hyps = _search([[0.0, 0.0, -9.0, -9.0], [0.0, 0.0, -9.0, -9.0]], beam=8)

    sequences = [ys for ys, _, _, _ in hyps]
    assert len(sequences) == len(set(sequences))
    best = {ys: score for ys, score, _, _ in hyps}
    assert best[(1,)] > best[(1, 1)]


def test_beam_search_with_hotword_flips_choice_and_reports_bonus() -> None:
    """ "XIN CHAO" kém "XIN CHÀO" 1 điểm thô; hotword XIN CHAO (2 token x 3.0) lật thứ hạng."""
    logits = [[0.0, 5.0, 0.0, 0.0], [0.0, 0.0, 4.0, 3.0], [5.0, 0.0, 0.0, 0.0]]
    plain = {ys: score for ys, score, _, _ in _search(logits)}

    hyps = _search(logits, beam=8, context=ContextGraph([[1, 3]], 3.0))

    assert hyps[0][0] == (1, 3)
    assert hyps[0][2] == 6.0
    assert math.isclose(hyps[0][1], plain[(1, 3)] + 6.0)
    # "XIN CHÀO" khớp dở (chỉ "XIN") rồi trượt: phần đã cộng bị trừ lại.
    chao = next(h for h in hyps if h[0] == (1, 2))
    assert chao[2] == 0.0


def test_context_graph_partial_match_is_removed_at_end() -> None:
    graph = ContextGraph([[1, 2, 3]], 2.0)

    node, delta = graph.step(0, 1)
    node, delta2 = graph.step(node, 2)

    assert (delta, delta2) == (2.0, 2.0)
    assert graph.finalize(node) == -4.0
    end, delta3 = graph.step(node, 3)
    assert (end, delta3) == (0, 2.0)
    assert graph.step(node, 9) == (0, -4.0)


def test_bpe_encode_picks_best_scoring_pieces() -> None:
    vocab = {"▁NGUYỄN": -5.0, "▁VĂN": -5.0, "▁A": -6.0, "▁": -3.0, "A": -4.0, "▁R": -8.0, "Ư": -6.0}

    assert bpe_encode("Nguyễn Văn A", vocab) == ["▁NGUYỄN", "▁VĂN", "▁A"]
    assert bpe_encode("RƯ", vocab) == ["▁R", "Ư"]
    assert bpe_encode("XYZ", vocab) == []


def test_to_nbest_joins_pieces_and_shares_sum_to_one() -> None:
    hyps = [((1, 2), -0.5, 0.0), ((1, 3), -1.5, 3.0), ((1, 2), -2.0, 0.0), ((1,), -3.0, 0.0)]

    result = to_nbest(hyps, _SYMBOLS, 2)

    assert [h.text for h in result] == ["XIN CHÀO", "XIN CHAO"]
    assert result[0].log_prob == -0.5
    assert result[1].bonus == 3.0
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

    def fake_nbest(pcm: bytes, rate: int, hotwords: tuple[str, ...] = ()) -> NBest:
        calls.append(rate)
        return NBest([NBestHyp("XIN CHÀO", -0.2, 0.8), NBestHyp("XIN CHAO", -1.6, 0.2)])

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
    assert [h.text for h in (await tasks[0]).hyps] == ["XIN CHÀO", "XIN CHAO"]
    assert calls == [8000]
    assert box.take() == []


async def test_zipformer_skips_nbest_when_disabled(_inline_threads) -> None:
    calls, box = await _final_tasks(top_k=0)

    assert box.take() == [] and calls == []


def test_beam_search_reports_token_log_probs_for_confidence() -> None:
    """Confidence như sherpa `ys_log_probs` (chỉ token phát ra, không lẫn điểm hotword)."""
    logits = [[0.0, 5.0, 0.0, 0.0], [0.0, 0.0, 4.0, 3.0], [5.0, 0.0, 0.0, 0.0]]
    plain = _search(logits)[0]
    biased = _search(logits, beam=8, context=ContextGraph([[1, 3]], 3.0))[0]

    assert len(plain.token_log_probs) == 2 and all(lp < 0 for lp in plain.token_log_probs)
    assert len(biased.token_log_probs) == 2 and all(lp < 0 for lp in biased.token_log_probs)
    hyp = to_nbest([plain], _SYMBOLS, 1)[0]
    assert math.isclose(hyp.confidence, math.exp(sum(plain.token_log_probs) / 2))
    assert math.isclose(hyp.min_token_prob, math.exp(min(plain.token_log_probs)))


def test_beam_search_decoder_cache_skips_repeated_contexts() -> None:
    """Decoder chỉ phụ thuộc ngữ cảnh token: cùng ngữ cảnh không gọi lại, kết quả không đổi."""
    logits = [[0.0, 5.0, 0.0, 0.0], [0.0, 0.0, 4.0, 3.0], [5.0, 0.0, 0.0, 0.0]]
    frames = np.array([[i] for i in range(len(logits))], dtype=np.float32)
    seen: list[tuple[int, ...]] = []

    def decode(contexts):
        seen.extend(contexts)
        return np.zeros((len(contexts), 1))

    def search(cache):
        return beam_search(
            frames,
            decode=decode,
            join=lambda enc, dec: np.array([logits[int(r[0])] for r in enc]),
            context_size=2,
            beam=4,
            decoder_cache=cache,
        )

    cache: dict = {}
    first = search(cache)
    assert len(seen) == len(set(seen))
    calls = len(seen)
    assert search(cache) == first and len(seen) == calls
