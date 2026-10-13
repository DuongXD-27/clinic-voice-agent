"""Top N phương án của model transducer (GipFormer) cho một câu — để XEM, không dùng để quyết.

sherpa-onnx chỉ trả phương án tốt nhất, nên đây chạy lại modified beam search bằng onnxruntime
trên đúng 3 file encoder/decoder/joiner của provider ZipFormer và giữ các phương án cuối beam.

Có hotword của lượt thì beam cộng điểm hotword như sherpa-onnx (mỗi token khớp cụm +`score`, khớp
dở rồi trượt thì trừ lại, hết câu còn dở cũng trừ): điểm là điểm CUỐI dùng để chọn câu. Không có
hotword: điểm thô, cho thấy model "nghe" ra những gì.

Điểm = tổng log-xác suất của chuỗi token (+ điểm hotword); `bonus` = phần hotword trong đó; `share`
= tỉ lệ của phương án trong N phương án (softmax trên điểm) để đọc nhanh.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Any, NamedTuple, Optional, Sequence

BLANK_ID = 0


@dataclass(frozen=True)
class NBestHyp:
    text: str
    log_prob: float
    share: float
    # Phần điểm hotword trong `log_prob` (0 khi lượt không có hotword hoặc không khớp cụm nào).
    bonus: float = 0.0
    # Như sherpa-onnx `ys_log_probs` nhưng không lẫn điểm hotword: exp(trung bình log-prob token)
    # và xác suất token thấp nhất; None khi không có token.
    confidence: Optional[float] = None
    min_token_prob: Optional[float] = None


class Path(NamedTuple):
    """Một phương án cuối beam: token (không gồm đệm đầu), điểm, phần hotword, log-prob từng token."""

    ys: tuple[int, ...]
    score: float
    bonus: float = 0.0
    token_log_probs: tuple[float, ...] = ()


@dataclass(frozen=True)
class NBest:
    """Top N của một final kèm các cụm hotword lượt đó (để trang demo hiện cùng)."""

    hyps: list[NBestHyp]
    hotwords: tuple[str, ...] = ()


class TransducerNBest:
    def __init__(
        self,
        *,
        encoder: str,
        decoder: str,
        joiner: str,
        tokens: str,
        num_threads: int = 1,
        sample_rate: int = 16_000,
        bpe_vocab: str = "",
    ) -> None:
        self._paths = (encoder, decoder, joiner)
        self._tokens_path = tokens
        self._num_threads = num_threads
        self.sample_rate = sample_rate
        self._bpe_vocab_path = bpe_vocab
        self._bpe_vocab: Optional[dict[str, float]] = None
        self._sessions: Any = None

    def nbest(
        self,
        samples: Any,
        k: int = 4,
        hotwords: Sequence[str] = (),
        hotwords_score: float = 0.0,
        beam: int = 4,
    ) -> list[NBestHyp]:
        """`samples`: float32 [-1, 1] ở `sample_rate`. Trả tối đa `k` phương án, tốt nhất trước.
        `hotwords` + `hotwords_score`: beam cộng điểm hotword như sherpa-onnx (điểm cuối).
        `beam`: để bằng max_active_paths của sherpa-onnx thì phương án 1 trùng câu sherpa chọn."""
        if len(samples) == 0 or k <= 0:
            return []
        return self.search(self.encode(samples), k, hotwords, hotwords_score, beam)

    def encode(self, samples: Any) -> Any:
        """Chạy encoder một lần (phần nặng nhất); kết quả dùng lại cho nhiều lần `search`."""
        import numpy as np

        encoder = self._load()[0]
        feats = self._features(np.asarray(samples, dtype=np.float32))
        if feats.shape[0] == 0:
            return feats
        enc_in = encoder.get_inputs()
        encoder_out, encoder_out_lens = encoder.run(
            None,
            {
                enc_in[0].name: feats[None, :, :],
                enc_in[1].name: np.array([feats.shape[0]], dtype=np.int64),
            },
        )
        return encoder_out[0, : int(encoder_out_lens[0])]

    def search(
        self,
        frames: Any,
        k: int = 4,
        hotwords: Sequence[str] = (),
        hotwords_score: float = 0.0,
        beam: int = 4,
        decoder_cache: Optional[dict[tuple[int, ...], Any]] = None,
    ) -> list[NBestHyp]:
        """Beam search trên đầu ra encoder (`encode`), như `nbest`. Nhiều lần search trên cùng
        câu thì truyền chung `decoder_cache` (một dict rỗng)."""
        import numpy as np

        if len(frames) == 0 or k <= 0:
            return []
        _, decoder, joiner, symbols, context_size = self._load()
        hyps = beam_search(
            frames,
            decode=lambda contexts: _run(decoder, np.array(contexts, dtype=np.int64)),
            join=lambda enc, dec: _run(joiner, enc, dec),
            context_size=context_size,
            beam=max(k, beam),
            context=self._context(hotwords, hotwords_score, symbols),
            decoder_cache=decoder_cache,
        )
        return to_nbest(hyps, symbols, k)

    def search_many(
        self,
        frames: Any,
        searches: Sequence[tuple[int, Sequence[str], float, int]],
        decoder_cache: Optional[dict[tuple[int, ...], Any]] = None,
    ) -> list[list[NBestHyp]]:
        """Nhiều `search` trên cùng đầu ra encoder, mỗi cái `(k, hotwords, hotwords_score, beam)`,
        chạy chung một vòng frame (gộp batch decoder/joiner) — nhanh hơn gọi `search` lần lượt,
        kết quả y hệt."""
        import numpy as np

        if len(frames) == 0:
            return [[] for _ in searches]
        _, decoder, joiner, symbols, context_size = self._load()
        paths = beam_search_many(
            frames,
            decode=lambda contexts: _run(decoder, np.array(contexts, dtype=np.int64)),
            join=lambda enc, dec: _run(joiner, enc, dec),
            context_size=context_size,
            searches=[
                (max(k, beam), self._context(hotwords, score, symbols))
                for k, hotwords, score, beam in searches
            ],
            decoder_cache=decoder_cache,
        )
        return [
            to_nbest(hyps, symbols, k) if k > 0 else []
            for hyps, (k, *_) in zip(paths, searches, strict=True)
        ]

    def _context(
        self, hotwords: Sequence[str], score: float, symbols: dict[int, str]
    ) -> Optional[ContextGraph]:
        if not hotwords or score <= 0 or not self._bpe_vocab_path:
            return None
        if self._bpe_vocab is None:
            self._bpe_vocab = load_bpe_vocab(self._bpe_vocab_path)
        ids = {piece: i for i, piece in symbols.items()}
        phrases = []
        for phrase in hotwords:
            pieces = bpe_encode(phrase, self._bpe_vocab)
            # Như sherpa-onnx: cụm có token ngoài tokens.txt thì bỏ cả cụm.
            if pieces and all(p in ids for p in pieces):
                phrases.append([ids[p] for p in pieces])
        return ContextGraph(phrases, score) if phrases else None

    def _features(self, samples: Any) -> Any:
        import kaldi_native_fbank as knf  # pip install kaldi-native-fbank
        import numpy as np

        # Cùng cấu hình fbank sherpa-onnx dùng cho model này (80 bin, không dither, không cắt mép).
        opts = knf.FbankOptions()
        opts.frame_opts.dither = 0
        opts.frame_opts.snip_edges = False
        opts.frame_opts.samp_freq = self.sample_rate
        opts.mel_opts.num_bins = 80
        opts.mel_opts.high_freq = -400
        fbank = knf.OnlineFbank(opts)
        fbank.accept_waveform(self.sample_rate, samples.tolist())
        fbank.input_finished()
        rows = [fbank.get_frame(i) for i in range(fbank.num_frames_ready)]
        return np.array(rows, dtype=np.float32).reshape(-1, 80)

    def _load(self) -> Any:
        if self._sessions is None:
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.intra_op_num_threads = self._num_threads
            options.inter_op_num_threads = 1
            encoder, decoder, joiner = (
                ort.InferenceSession(path, options, providers=["CPUExecutionProvider"])
                for path in self._paths
            )
            meta = decoder.get_modelmeta().custom_metadata_map
            context_size = int(meta.get("context_size", 2))
            symbols: dict[int, str] = {}
            with open(self._tokens_path, encoding="utf-8") as f:
                for line in f:
                    parts = line.rstrip("\n").rsplit(maxsplit=1)
                    if len(parts) == 2 and parts[1].isdigit():
                        symbols[int(parts[1])] = parts[0]
            self._sessions = (encoder, decoder, joiner, symbols, context_size)
        return self._sessions


def _run(session: Any, *inputs: Any) -> Any:
    names = [i.name for i in session.get_inputs()]
    return session.run(None, dict(zip(names, inputs, strict=True)))[0]


class ContextGraph:
    """Trie Aho-Corasick các cụm hotword (theo token id), chấm điểm như ContextGraph sherpa-onnx:
    mỗi token đi sâu thêm trong cụm +`score`; trượt khỏi cụm thì trừ phần đã cộng của đoạn khớp
    dở; khớp trọn cụm thì giữ điểm và quay về gốc."""

    def __init__(self, phrases: Sequence[Sequence[int]], score: float) -> None:
        self.score = score
        self._next: list[dict[int, int]] = [{}]
        self._depth = [0]
        self._end = [False]
        for ids in phrases:
            node = 0
            for token in ids:
                if token not in self._next[node]:
                    self._next.append({})
                    self._depth.append(self._depth[node] + 1)
                    self._end.append(False)
                    self._next[node][token] = len(self._next) - 1
                node = self._next[node][token]
            self._end[node] = True
        self._fail = [0] * len(self._next)
        queue = deque(self._next[0].values())
        while queue:
            node = queue.popleft()
            for token, child in self._next[node].items():
                fail = self._fail[node]
                while fail and token not in self._next[fail]:
                    fail = self._fail[fail]
                target = self._next[fail].get(token, 0)
                self._fail[child] = target if target != child else 0
                queue.append(child)

    def step(self, node: int, token: int) -> tuple[int, float]:
        """(trạng thái mới, điểm cộng/trừ) khi phát `token` từ `node`."""
        state = node
        while state and token not in self._next[state]:
            state = self._fail[state]
        child = self._next[state].get(token, 0)
        delta = (self._depth[child] - self._depth[node]) * self.score
        return (0 if self._end[child] else child), delta

    def finalize(self, node: int) -> float:
        """Hết câu còn khớp dở: trừ lại phần đã cộng."""
        return -self._depth[node] * self.score

    def leaving(self, node: int) -> float:
        """Điểm của token bất kỳ không đi tiếp cụm nào từ `node` (trượt về gốc)."""
        return -self._depth[node] * self.score

    def continuing(self, node: int) -> set[int]:
        """Token có thể đi tiếp một cụm từ `node` (gồm cả nút fail và gốc)."""
        tokens: set[int] = set()
        state = node
        while True:
            tokens.update(self._next[state])
            if state == 0:
                return tokens
            state = self._fail[state]


def beam_search(
    frames: Any,
    *,
    decode: Any,
    join: Any,
    context_size: int,
    beam: int,
    context: Optional[ContextGraph] = None,
    decoder_cache: Optional[dict[tuple[int, ...], Any]] = None,
) -> list[Path]:
    """Modified beam search (tối đa 1 token mỗi frame), gộp phương án trùng chuỗi token.

    `decode(contexts [N, context_size]) -> [N, D]`, `join(enc [N, D], dec [N, D]) -> logits [N, V]`.
    `context`: cộng điểm hotword vào điểm chọn beam. Trả (chuỗi token không gồm phần đệm đầu,
    điểm, phần điểm hotword), tốt nhất trước.
    `decoder_cache`: đầu ra decoder theo ngữ cảnh token (chỉ phụ thuộc `context_size` token cuối,
    blank giữ nguyên ngữ cảnh nên lặp lại rất nhiều); truyền cùng một dict cho nhiều lần search
    trên cùng câu để dùng chung."""
    return beam_search_many(
        frames,
        decode=decode,
        join=join,
        context_size=context_size,
        searches=[(beam, context)],
        decoder_cache=decoder_cache,
    )[0]


def beam_search_many(
    frames: Any,
    *,
    decode: Any,
    join: Any,
    context_size: int,
    searches: Sequence[tuple[int, Optional[ContextGraph]]],
    decoder_cache: Optional[dict[tuple[int, ...], Any]] = None,
) -> list[list[Path]]:
    """Nhiều `beam_search` (mỗi cái một `(beam, context)`) trên cùng câu, chạy song song từng
    frame: mỗi frame gọi decoder và joiner MỘT lần cho phương án của mọi search (gộp batch) thay
    vì mỗi search một lần. Kết quả từng search y hệt chạy riêng."""
    import numpy as np

    cache: dict[tuple[int, ...], Any] = {} if decoder_cache is None else decoder_cache

    start = (BLANK_ID,) * context_size
    # Mỗi search: ys -> (điểm, phần hotword, trạng thái context, log-prob từng token); cùng ys thì
    # cùng trạng thái context.
    states: list[dict[tuple[int, ...], tuple[float, float, int, tuple[float, ...]]]] = [
        {start: (0.0, 0.0, 0, ())} for _ in searches
    ]
    for frame in frames:
        groups = [list(hyps.items()) for hyps in states]
        items = [item for group in groups for item in group]
        contexts = [ys[-context_size:] for ys, _ in items]
        missing = list(dict.fromkeys(c for c in contexts if c not in cache))
        if missing:
            for ctx, row in zip(missing, decode(missing), strict=True):
                cache[ctx] = row
        dec_out = np.stack([cache[c] for c in contexts])
        enc = np.repeat(frame[None, :], len(items), axis=0)
        all_logits = np.asarray(join(enc, dec_out), dtype=np.float64)
        all_logits = all_logits.reshape(len(items), -1)
        offset = 0
        for index, ((beam, context), group) in enumerate(zip(searches, groups, strict=True)):
            logits = all_logits[offset : offset + len(group)]
            offset += len(group)
            states[index] = _beam_step(logits, group, beam, context)
    results = []
    for (_, context), hyps in zip(searches, states, strict=True):
        final = []
        for ys, (score, bonus, node, token_lps) in hyps.items():
            if context is not None:
                score, bonus = score + context.finalize(node), bonus + context.finalize(node)
            final.append(Path(ys[context_size:], score, bonus, token_lps))
        results.append(sorted(final, key=lambda item: item.score, reverse=True))
    return results


def _beam_step(
    logits: Any, items: list, beam: int, context: Optional[ContextGraph]
) -> dict[tuple[int, ...], tuple[float, float, int, tuple[float, ...]]]:
    """Một frame của modified beam search: giữ `beam` phương án tốt nhất (đã gộp chuỗi trùng)."""
    import numpy as np

    log_probs = logits - _logsumexp(logits)
    totals = log_probs + np.array([h[0] for _, h in items])[:, None]
    deltas = _context_deltas(totals.shape, items, context) if context else None
    if deltas is not None:
        totals = totals + deltas
    flat = totals.ravel()
    top = np.argpartition(-flat, min(beam, flat.size) - 1)[:beam]
    merged: dict[tuple[int, ...], tuple[float, float, int, tuple[float, ...]]] = {}
    vocab = totals.shape[1]
    for index in top:
        row, token = divmod(int(index), vocab)
        ys, (_, bonus, node, token_lps) = items[row]
        if token != BLANK_ID:
            ys = ys + (token,)
            token_lps = token_lps + (float(log_probs[row, token]),)
            if context is not None:
                node, delta = context.step(node, token)
                bonus += delta
        score = float(flat[index])
        if ys in merged:
            previous = merged[ys]
            merged[ys] = (_logaddexp(previous[0], score), *previous[1:])
        else:
            merged[ys] = (score, bonus, node, token_lps)
    return merged


def _context_deltas(shape: tuple[int, int], items: list, context: ContextGraph) -> Any:
    """Điểm hotword của từng ô (phương án, token): blank giữ nguyên trạng thái (0), token đi tiếp
    cụm theo `step`, mọi token khác trượt khỏi đoạn đang khớp dở."""
    import numpy as np

    deltas = np.zeros(shape)
    for row, (_, (_, _, node, _)) in enumerate(items):
        if node:
            deltas[row, :] = context.leaving(node)
            deltas[row, BLANK_ID] = 0.0
        for token in context.continuing(node):
            if 0 < token < shape[1]:
                deltas[row, token] = context.step(node, token)[1]
    return deltas


def to_nbest(hyps: Sequence[Sequence[Any]], symbols: dict[int, str], k: int) -> list[NBestHyp]:
    """Ghép token thành chữ (giữ phương án đầu tiên của mỗi chữ), lấy `k` phương án đầu.
    `hyps`: `Path` hoặc (ys, điểm, phần hotword)."""
    texts: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for hyp in hyps:
        path = Path(*hyp)
        text = "".join(symbols.get(t, "") for t in path.ys).replace("▁", " ").strip()
        text = " ".join(text.split())
        if text in seen:
            continue
        seen.add(text)
        texts.append((text, path))
        if len(texts) == k:
            break
    if not texts:
        return []
    best = max(path.score for _, path in texts)
    weights = [math.exp(path.score - best) for _, path in texts]
    total = sum(weights)
    result = []
    for (text, path), w in zip(texts, weights, strict=True):
        lps = path.token_log_probs
        result.append(
            NBestHyp(
                text=text,
                log_prob=round(path.score, 3),
                share=round(w / total, 3),
                bonus=round(path.bonus, 3),
                confidence=math.exp(sum(lps) / len(lps)) if lps else None,
                min_token_prob=math.exp(min(lps)) if lps else None,
            )
        )
    return result


def load_bpe_vocab(path: str) -> dict[str, float]:
    """bpe.vocab ("piece<TAB>score", xuất từ bpe.model) -> điểm unigram của từng piece."""
    vocab: dict[str, float] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) == 2 and not parts[0].startswith("<"):
                vocab[parts[0]] = float(parts[1])
    return vocab


def bpe_encode(text: str, vocab: dict[str, float]) -> list[str]:
    """Cắt cụm thành piece như sentencepiece unigram (Viterbi trên điểm piece); [] nếu không cắt
    được. Không cần thư viện sentencepiece lúc chạy (sherpa-onnx cũng tự cắt từ bpe.vocab)."""
    longest = max((len(p) for p in vocab), default=0)
    pieces: list[str] = []
    for word in text.upper().split():
        chars = "▁" + word
        best: list[tuple[float, int]] = [(0.0, 0)] + [(-math.inf, 0)] * len(chars)
        for i in range(len(chars)):
            if best[i][0] == -math.inf:
                continue
            for j in range(i + 1, min(len(chars), i + longest) + 1):
                score = vocab.get(chars[i:j])
                if score is not None and best[i][0] + score > best[j][0]:
                    best[j] = (best[i][0] + score, i)
        if best[-1][0] == -math.inf:
            return []
        word_pieces, end = [], len(chars)
        while end:
            start = best[end][1]
            word_pieces.append(chars[start:end])
            end = start
        pieces.extend(reversed(word_pieces))
    return pieces


def _logsumexp(values: Any) -> Any:
    import numpy as np

    peak = values.max(axis=1, keepdims=True)
    return peak + np.log(np.exp(values - peak).sum(axis=1, keepdims=True))


def _logaddexp(a: float, b: float) -> float:
    peak = max(a, b)
    return peak + math.log(math.exp(a - peak) + math.exp(b - peak))
