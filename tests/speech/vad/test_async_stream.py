from typing import AsyncIterator, Iterable

from speech.asr.vad import AsyncStreamingVAD, EnergyFrameClassifier
from speech.asr.vad.base import VadEvent
from speech.asr.vad.streaming import FRAME_MS, split_frames

_LOUD = b"\x00\x10" * 120  # ~30ms @ 8kHz, RMS cao hơn threshold mặc định
_SILENT = b"\x00\x00" * 120


async def _aiter(frames: Iterable[bytes]) -> AsyncIterator[bytes]:
    for frame in frames:
        yield frame


def _classifier() -> EnergyFrameClassifier:
    return EnergyFrameClassifier(rms_threshold=500.0)


async def _run_async(frames: list[bytes], end_silence_ms: int = 600) -> list[VadEvent]:
    vad = AsyncStreamingVAD(_classifier(), end_silence_ms=end_silence_ms)
    return [event async for event in vad.process(_aiter(frames))]


async def test_emits_start_and_end_around_each_utterance() -> None:
    frames = [_LOUD] * 5 + [_SILENT] * 25 + [_LOUD] * 3
    kinds = [event.kind for event in await _run_async(frames)]
    assert kinds == (
        ["speech_start"]
        + ["speech"] * 5
        + ["speech_end"]
        + ["speech_start"]
        + ["speech"] * 3
        + ["speech_end"]
    )


async def test_pause_inside_utterance_does_not_cut_turn() -> None:
    # Im lặng ngắn (< end_silence_frames) giữa 2 đoạn nói không được phát speech_end
    # ngay tại chỗ pause — chỉ có 1 speech_start và không có speech_end giữa dòng sự kiện.
    end_silence_ms = 600
    short_pause_frames = (end_silence_ms // FRAME_MS) - 1
    frames = [_LOUD] * 4 + [_SILENT] * short_pause_frames + [_LOUD] * 4

    events = await _run_async(frames, end_silence_ms=end_silence_ms)

    kinds = [event.kind for event in events]
    assert kinds.count("speech_start") == 1
    # speech_end duy nhất (nếu có) chỉ được phép là event cuối cùng — do stream kết thúc
    # trong lúc vẫn "in_speech", không phải do pause giữa câu kích hoạt.
    end_indices = [i for i, k in enumerate(kinds) if k == "speech_end"]
    assert end_indices in ([], [len(kinds) - 1])


async def test_noise_shorter_than_frame_is_not_speech() -> None:
    frames = [_SILENT] * 10

    events = await _run_async(frames)

    assert events == []


async def test_split_frames_produces_expected_frame_count() -> None:
    frame_bytes = int(8000 * FRAME_MS / 1000) * 2  # PCM16 mono @ 8kHz
    pcm = b"\x00\x10" * (frame_bytes // 2) * 10
    frames = list(split_frames(pcm, sample_rate=8000))
    assert len(frames) == 10
    assert all(len(f) == frame_bytes for f in frames)
