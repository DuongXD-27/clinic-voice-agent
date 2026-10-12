"""Top N phương án của model transducer (GipFormer) cho một câu — để XEM, không dùng để quyết.

sherpa-onnx chỉ trả phương án tốt nhất, nên đây chạy lại modified beam search bằng onnxruntime
trên đúng 3 file encoder/decoder/joiner của provider ZipFormer và giữ các phương án cuối beam.
Không có hotword: cho thấy model "nghe" ra những gì trước khi bị bias.

Điểm = tổng log-xác suất của chuỗi token (càng gần 0 càng chắc); `share` = tỉ lệ của phương án
trong N phương án (softmax trên điểm) để đọc nhanh.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

BLANK_ID = 0


@dataclass(frozen=True)
class NBestHyp:
    text: str
    log_prob: float
    share: float


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
    ) -> None:
        self._paths = (encoder, decoder, joiner)
        self._tokens_path = tokens
        self._num_threads = num_threads
        self.sample_rate = sample_rate
        self._sessions: Any = None

    def nbest(self, samples: Any, k: int = 4) -> list[NBestHyp]:
        """`samples`: float32 [-1, 1] ở `sample_rate`. Trả tối đa `k` phương án, tốt nhất trước."""
        import numpy as np

        if len(samples) == 0 or k <= 0:
            return []
        encoder, decoder, joiner, symbols, context_size = self._load()
        feats = self._features(np.asarray(samples, dtype=np.float32))
        if feats.shape[0] == 0:
            return []
        enc_in = encoder.get_inputs()
        encoder_out, encoder_out_lens = encoder.run(
            None,
            {
                enc_in[0].name: feats[None, :, :],
                enc_in[1].name: np.array([feats.shape[0]], dtype=np.int64),
            },
        )
        frames = encoder_out[0, : int(encoder_out_lens[0])]
        hyps = beam_search(
            frames,
            decode=lambda contexts: _run(decoder, np.array(contexts, dtype=np.int64)),
            join=lambda enc, dec: _run(joiner, enc, dec),
            context_size=context_size,
            beam=max(k, 4),
        )
        return to_nbest(hyps, symbols, k)

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


def beam_search(
    frames: Any, *, decode: Any, join: Any, context_size: int, beam: int
) -> list[tuple[tuple[int, ...], float]]:
    """Modified beam search (tối đa 1 token mỗi frame), gộp phương án trùng chuỗi token.

    `decode(contexts [N, context_size]) -> [N, D]`, `join(enc [N, D], dec [N, D]) -> logits [N, V]`.
    Trả (chuỗi token không gồm phần đệm đầu, log-xác suất), tốt nhất trước."""
    import numpy as np

    start = (BLANK_ID,) * context_size
    hyps: dict[tuple[int, ...], float] = {start: 0.0}
    for frame in frames:
        items = list(hyps.items())
        contexts = [ys[-context_size:] for ys, _ in items]
        dec_out = decode(contexts)
        enc = np.repeat(frame[None, :], len(items), axis=0)
        logits = np.asarray(join(enc, dec_out), dtype=np.float64)
        logits = logits.reshape(len(items), -1)
        log_probs = logits - _logsumexp(logits)
        totals = log_probs + np.array([score for _, score in items])[:, None]
        flat = totals.ravel()
        top = np.argpartition(-flat, min(beam, flat.size) - 1)[:beam]
        merged: dict[tuple[int, ...], float] = {}
        vocab = totals.shape[1]
        for index in top:
            row, token = divmod(int(index), vocab)
            ys = items[row][0] if token == BLANK_ID else items[row][0] + (token,)
            score = float(flat[index])
            merged[ys] = _logaddexp(merged[ys], score) if ys in merged else score
        hyps = merged
    ranked = sorted(hyps.items(), key=lambda item: item[1], reverse=True)
    return [(ys[context_size:], score) for ys, score in ranked]


def to_nbest(
    hyps: list[tuple[tuple[int, ...], float]], symbols: dict[int, str], k: int
) -> list[NBestHyp]:
    """Ghép token thành chữ (giữ phương án đầu tiên của mỗi chữ), lấy `k` phương án đầu."""
    texts: list[tuple[str, float]] = []
    seen: set[str] = set()
    for ys, score in hyps:
        text = "".join(symbols.get(t, "") for t in ys).replace("▁", " ").strip()
        text = " ".join(text.split())
        if text in seen:
            continue
        seen.add(text)
        texts.append((text, score))
        if len(texts) == k:
            break
    if not texts:
        return []
    best = max(score for _, score in texts)
    weights = [math.exp(score - best) for _, score in texts]
    total = sum(weights)
    return [
        NBestHyp(text=text, log_prob=round(score, 3), share=round(w / total, 3))
        for (text, score), w in zip(texts, weights, strict=True)
    ]


def _logsumexp(values: Any) -> Any:
    import numpy as np

    peak = values.max(axis=1, keepdims=True)
    return peak + np.log(np.exp(values - peak).sum(axis=1, keepdims=True))


def _logaddexp(a: float, b: float) -> float:
    peak = max(a, b)
    return peak + math.log(math.exp(a - peak) + math.exp(b - peak))
