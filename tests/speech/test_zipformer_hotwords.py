"""Hotword theo lượt trên ZipFormer (callbot/engine/asr_hints.py): chỉ final, chặn SF-03 ở lượt tên."""

import asyncio
import sys
import types
from typing import AsyncIterator, Iterable, Optional

import pytest
from pydantic import ValidationError

from inference.asr.config import ZipFormerConfig
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

    def __init__(self, plain: str, biased: str) -> None:
        self.plain, self.biased = plain, biased
        self.calls: list[Optional[str]] = []

    def create_stream(self, hotwords: Optional[str] = None) -> _Stream:
        return _Stream(self, hotwords)

    def decode_stream(self, stream: _Stream) -> None:
        self.calls.append(stream.hotwords)
        text = self.biased if stream.hotwords else self.plain
        stream.result = types.SimpleNamespace(text=text, ys_log_probs=[-0.1])


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


def _box(*phrases: str, guard: bool = False) -> HotwordBox:
    box = HotwordBox()
    box.set(Hotwords(phrases, guard))
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


async def test_name_guard_accepts_one_word_correction() -> None:
    """Lỗi đúng kiểu Huy gặp: "NGUYỄN VĂN A" bị nghe thành "NGUYỄN VĂN ANH"."""
    recognizer = _Recognizer("TÔI TÊN LÀ NGUYỄN VĂN ANH", "TÔI TÊN LÀ NGUYỄN VĂN A")
    asr = ZipFormerASR(_config(), recognizer=recognizer)

    events = await _run(asr, _box("NGUYỄN VĂN A", guard=True))

    assert [e.text for e in events if e.is_final] == ["TÔI TÊN LÀ NGUYỄN VĂN A"]


async def test_name_guard_rejects_pulling_a_different_name() -> None:
    """SF-03: tên khác hẳn (lệch > 1 từ) không được kéo về tên hồ sơ."""
    recognizer = _Recognizer("TÔI TÊN LÀ TRẦN THỊ HOA", "TÔI TÊN LÀ NGUYỄN VĂN A")
    asr = ZipFormerASR(_config(), recognizer=recognizer)

    events = await _run(asr, _box("NGUYỄN VĂN A", guard=True))

    assert [e.text for e in events if e.is_final] == ["TÔI TÊN LÀ TRẦN THỊ HOA"]


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
