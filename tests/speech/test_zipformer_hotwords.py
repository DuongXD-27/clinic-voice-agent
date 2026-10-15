"""Hotword theo lượt trên ZipFormer (callbot/engine/asr_hints.py): chỉ final, lượt tên luôn nhận bản có hotword."""

import asyncio
import sys
import types
from typing import AsyncIterator, Iterable, Optional

import pytest
from pydantic import ValidationError

from inference.asr.config import ZipFormerConfig
from inference.asr.providers.transducer_nbest import NBestHyp
from inference.asr.providers.zipformer import ZipFormerASR
from speech.asr.hotwords import HotwordBox, Hotwords, word_distance
from speech.asr.vad.streaming import FRAME_MS

_FRAME_BYTES = int(8000 * FRAME_MS / 1000) * 2
_LOUD = b"\x00\x10" * (_FRAME_BYTES // 2)
_SILENT = b"\x00\x00" * (_FRAME_BYTES // 2)


@pytest.fixture(autouse=True)
def _run_decoder_inline(monkeypatch):
    async def inline(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", inline)


def _config(**overrides) -> ZipFormerConfig:
    base = dict(
        encoder_path="e",
        decoder_path="d",
        joiner_path="j",
        tokens_path="t",
        hotwords_enabled=True,
        bpe_vocab_path="bpe.vocab",
    )
    return ZipFormerConfig(**{**base, **overrides})


class _Stream:
    def __init__(self, recognizer: "_Recognizer", hotwords: Optional[str]) -> None:
        self._recognizer = recognizer
        self.hotwords = hotwords
        self.result = None

    def accept_waveform(self, sample_rate: int, samples: object) -> None:
        pass


class _Recognizer:
    """Bản không hotword ra `plain`; có hotword ra `biased`. Ghi lại hotword từng lần decode."""

    def __init__(self, plain: str, biased: str, biased_log_prob: float = -0.1) -> None:
        self.plain, self.biased = plain, biased
        self.biased_log_prob = biased_log_prob
        self.calls: list[Optional[str]] = []

    def create_stream(self, hotwords: Optional[str] = None) -> _Stream:
        return _Stream(self, hotwords)

    def decode_stream(self, stream: _Stream) -> None:
        self.calls.append(stream.hotwords)
        text = self.biased if stream.hotwords else self.plain
        log_prob = self.biased_log_prob if stream.hotwords else -0.1
        stream.result = types.SimpleNamespace(
            text=text, ys_log_probs=[log_prob], tokens=[f" {w}" for w in text.split()]
        )


async def _aiter(frames: Iterable[bytes]) -> AsyncIterator[bytes]:
    for frame in frames:
        yield frame


async def _run(asr: ZipFormerASR, box: Optional[HotwordBox]) -> list:
    frames = [_LOUD] * 20 + [_SILENT] * 25
    return [
        event
        async for event in asr.stream(
            _aiter(frames),
            end_silence_ms=600,
            min_emit_interval_ms=0,
            min_decode_ms=0,
            hotwords=box,
        )
    ]


def _box(*phrases: str, name_turn: bool = False) -> HotwordBox:
    box = HotwordBox()
    box.set(Hotwords(phrases, name_turn))
    return box


async def test_hotwords_apply_to_final_only() -> None:
    recognizer = _Recognizer("TÔI CHỌN THỨ BẢY", "TÔI CHỌN THỨ SÁU")
    asr = ZipFormerASR(_config(), recognizer=recognizer)

    events = await _run(asr, _box("THỨ SÁU", "CHÍN GIỜ SÁNG"))

    partials = [e for e in events if not e.is_final]
    finals = [e for e in events if e.is_final]
    assert partials and all(e.text == "TÔI CHỌN THỨ BẢY" for e in partials)
    assert [e.text for e in finals] == ["TÔI CHỌN THỨ SÁU"]
    assert "THỨ SÁU/CHÍN GIỜ SÁNG" in recognizer.calls


async def test_name_turn_accepts_one_word_correction() -> None:
    """Lỗi đúng kiểu Huy gặp: "NGUYỄN VĂN A" bị nghe thành "NGUYỄN VĂN ANH"."""
    recognizer = _Recognizer("TÔI TÊN LÀ NGUYỄN VĂN ANH", "TÔI TÊN LÀ NGUYỄN VĂN A")
    asr = ZipFormerASR(_config(), recognizer=recognizer)

    events = await _run(asr, _box("NGUYỄN VĂN A", name_turn=True))

    assert [e.text for e in events if e.is_final] == ["TÔI TÊN LÀ NGUYỄN VĂN A"]


async def test_name_turn_takes_hotword_however_far_from_plain() -> None:
    """Không còn chặn theo độ lệch: bản có hotword luôn thắng, Verifier vẫn đòi khớp ngày sinh."""
    recognizer = _Recognizer("TÔI TÊN LÀ GIANG A PAO", "TÔI TÊN LÀ GIÀNG A PÁO")
    asr = ZipFormerASR(_config(), recognizer=recognizer)

    events = await _run(asr, _box("GIÀNG A PÁO", name_turn=True))

    assert [e.text for e in events if e.is_final] == ["TÔI TÊN LÀ GIÀNG A PÁO"]


async def test_name_hotword_confidence_is_raised_to_pass_name_gate() -> None:
    """sherpa cho bản có hotword confidence ~0 (điểm hotword trộn vào log-prob): nâng lên 0.5."""
    recognizer = _Recognizer("TÔI LÀ NGUYỄN VĂN AN", "TÔI LÀ NGUYỄN VĂN A", biased_log_prob=-10.0)
    asr = ZipFormerASR(_config(), recognizer=recognizer)

    events = await _run(asr, _box("NGUYỄN VĂN A", name_turn=True))

    final = [e for e in events if e.is_final][0]
    assert final.text == "TÔI LÀ NGUYỄN VĂN A"
    assert final.confidence == 0.5


async def test_name_hotword_same_as_plain_uses_plain_confidence() -> None:
    recognizer = _Recognizer("TÔI LÀ NGUYỄN VĂN A", "TÔI LÀ NGUYỄN VĂN A", biased_log_prob=-10.0)
    asr = ZipFormerASR(_config(), recognizer=recognizer)

    events = await _run(asr, _box("NGUYỄN VĂN A", name_turn=True))

    final = [e for e in events if e.is_final][0]
    assert final.confidence is not None and final.confidence > 0.9


async def test_disabled_or_empty_hotwords_decode_plain() -> None:
    for config, box in ((_config(hotwords_enabled=False), _box("THỨ SÁU")), (_config(), None)):
        recognizer = _Recognizer("TÔI CHỌN THỨ BẢY", "TÔI CHỌN THỨ SÁU")
        asr = ZipFormerASR(config, recognizer=recognizer)

        events = await _run(asr, box)

        assert [e.text for e in events if e.is_final] == ["TÔI CHỌN THỨ BẢY"]
        assert set(recognizer.calls) == {None}


def test_supports_hotwords_follows_config() -> None:
    assert ZipFormerASR(_config()).supports_hotwords
    assert not ZipFormerASR(_config(hotwords_enabled=False)).supports_hotwords


def test_enabled_hotwords_need_bpe_vocab() -> None:
    with pytest.raises(ValidationError):
        _config(bpe_vocab_path="")


def test_recognizer_uses_beam_search_when_enabled(monkeypatch) -> None:
    created: dict = {}

    class _OfflineRecognizer:
        @staticmethod
        def from_transducer(**kwargs):
            created.update(kwargs)
            return object()

    monkeypatch.setitem(
        sys.modules, "sherpa_onnx", types.SimpleNamespace(OfflineRecognizer=_OfflineRecognizer)
    )

    ZipFormerASR(_config(hotwords_score=2.0))._get_recognizer()
    assert created["decoding_method"] == "modified_beam_search"
    assert created["modeling_unit"] == "bpe"
    assert created["bpe_vocab"] == "bpe.vocab"
    assert created["hotwords_score"] == 2.0

    created.clear()
    ZipFormerASR(_config(hotwords_enabled=False))._get_recognizer()
    assert created["decoding_method"] == "greedy_search"
    assert "bpe_vocab" not in created


def test_partials_and_unhinted_turns_use_greedy_when_hotwords_enabled(monkeypatch) -> None:
    """Beam search chỉ cho câu có hotword (và bản đối chứng của nó); còn lại greedy cho nhanh."""
    built: list[str] = []

    class _OfflineRecognizer:
        @staticmethod
        def from_transducer(**kwargs):
            built.append(kwargs["decoding_method"])
            return _Recognizer("XIN CHÀO", "XIN CHÀO")

    monkeypatch.setitem(
        sys.modules, "sherpa_onnx", types.SimpleNamespace(OfflineRecognizer=_OfflineRecognizer)
    )
    asr = ZipFormerASR(_config())
    asr._shared_encoder = False  # nhánh sherpa (beam) cho lượt tên

    asr._decode_stream_scored(b"\x00\x10" * 1600, 16_000)
    assert built == ["greedy_search"]
    asr._decode_stream_hinted(b"\x00\x10" * 1600, 16_000, Hotwords(("XIN CHÀO",), True))
    assert built == ["greedy_search", "modified_beam_search"]
    asr._decode_stream_scored(b"\x00\x10" * 1600, 16_000)
    assert len(built) == 2


@pytest.mark.parametrize(
    ("a", "b", "distance"),
    [
        ("NGUYỄN VĂN A", "NGUYỄN VĂN ANH", 1),
        ("NGUYỄN VĂN A", "NGUYỄN VĂN", 1),
        ("TRẦN THỊ HOA", "NGUYỄN VĂN A", 3),
        ("", "A B", 2),
        ("A B", "A B", 0),
    ],
)
def test_word_distance(a: str, b: str, distance: int) -> None:
    assert word_distance(a, b) == distance


class _SharedNBest:
    """TransducerNBest giả: một lần `encode`, `search` có/không hotword trả top cho sẵn."""

    def __init__(self, plain: list[str], biased: list[str]) -> None:
        self.plain, self.biased = plain, biased
        self.encodes = 0
        self.searches: list[tuple[int, tuple[str, ...]]] = []

    def encode(self, samples):
        self.encodes += 1
        return [0]

    def search(self, frames, k, hotwords=(), score=0.0, beam=4, cache=None):
        self.searches.append((k, tuple(hotwords)))
        texts = self.biased if hotwords else self.plain
        return [NBestHyp(t, -float(i), 0.1, confidence=0.8) for i, t in enumerate(texts[:k])]

    def search_many(self, frames, searches, cache=None):
        return [
            self.search(frames, k, hotwords, score, beam, cache)
            for k, hotwords, score, beam in searches
        ]


def _shared_case(monkeypatch, plain: list[str], biased: list[str], **config):
    asr = ZipFormerASR(_config(**config))
    fake = _SharedNBest(plain, biased)
    monkeypatch.setattr(asr, "_get_nbest", lambda: fake)
    return asr, fake


def test_shared_encoder_runs_encoder_once(monkeypatch) -> None:
    asr, fake = _shared_case(
        monkeypatch, ["TÔI LÀ NGUYỄN VĂN AN", "TÔI LÀ NGUYỄN VĂN A"], ["TÔI LÀ NGUYỄN VĂN A"]
    )
    pcm = b"\x00\x10" * 1600

    decoded = asr._decode_stream_hinted(pcm, 16_000, Hotwords(("NGUYỄN VĂN A",), True))

    assert decoded.text == "TÔI LÀ NGUYỄN VĂN A" and decoded.confidence == 0.8
    assert fake.encodes == 1
    assert fake.searches == [(4, ("NGUYỄN VĂN A",)), (1, ())]
    # Top 4 trên UI lấy lại kết quả vừa tính, không chạy encoder lần nữa.
    shown = asr.nbest(pcm, 16_000, ("NGUYỄN VĂN A",))
    assert [h.text for h in shown.hyps] == ["TÔI LÀ NGUYỄN VĂN A"] and fake.encodes == 1


def test_shared_encoder_takes_hotword_however_far_from_plain(monkeypatch) -> None:
    asr, _ = _shared_case(monkeypatch, ["TÔI LÀ GIANG A PAO"], ["TÔI LÀ GIÀNG A PÁO"])

    decoded = asr._decode_stream_hinted(
        b"\x00\x10" * 1600, 16_000, Hotwords(("GIÀNG A PÁO",), True)
    )

    assert decoded.text == "TÔI LÀ GIÀNG A PÁO" and decoded.confidence == 0.8


def test_warm_up_loads_hotword_models_before_the_first_call(monkeypatch) -> None:
    """Mỗi job LiveKit một process: model lượt tên (top N/beam) phải nạp lúc prewarm, không để
    lượt tên đầu tiên của cuộc gọi tự nạp."""
    asr, fake = _shared_case(monkeypatch, ["XIN CHÀO"], ["XIN CHÀO"])
    decoded: list[str] = []
    monkeypatch.setattr(
        asr, "_decode_scored", lambda pcm, hotwords="", *, beam=True: decoded.append(hotwords)
    )
    monkeypatch.setattr(asr, "_get_recognizer", lambda *, beam=True: None)

    asr.warm_up()

    assert decoded == ["XIN CHÀO"]
    assert fake.encodes == 1
    assert asr._nbest_ready is None
