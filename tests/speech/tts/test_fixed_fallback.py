"""Câu chuyển máy ghi sẵn khi TTS lỗi (R-39): thiếu asset một lần không được làm mất câu này cho cả
process (trước đây `lru_cache` giữ luôn kết quả None tới khi khởi động lại worker)."""

import pytest

from callbot.engine.dialogue.templates import TRANSFER
from speech.tts import fixed_fallback
from speech.tts.static_cache import load_release


@pytest.fixture(autouse=True)
def _empty_process_cache(monkeypatch):
    monkeypatch.setattr(fixed_fallback, "_loaded", {})


def test_missing_release_is_retried_on_the_next_tts_error(monkeypatch) -> None:
    calls = []

    def release_not_mounted_yet(settings=None):
        calls.append(settings)
        return None if len(calls) == 1 else load_release(settings)

    monkeypatch.setattr(fixed_fallback, "load_release", release_not_mounted_yet)

    assert fixed_fallback.fixed_utterance_pcm(TRANSFER, 8000) is None
    pcm = fixed_fallback.fixed_utterance_pcm(TRANSFER, 8000)

    assert pcm  # lần sau đọc lại được, không trả None đã cache
    assert len(calls) == 2


def test_loaded_audio_is_reused_without_reading_the_release_again(monkeypatch) -> None:
    calls = []

    def counting(settings=None):
        calls.append(settings)
        return load_release(settings)

    monkeypatch.setattr(fixed_fallback, "load_release", counting)

    first = fixed_fallback.fixed_utterance_pcm(TRANSFER, 24000)
    second = fixed_fallback.fixed_utterance_pcm(TRANSFER, 24000)

    assert first and second is first
    assert len(calls) == 1


def test_unknown_text_has_no_audio() -> None:
    assert fixed_fallback.fixed_utterance_pcm("Một câu không có trong release", 8000) is None
    assert fixed_fallback._loaded == {}
