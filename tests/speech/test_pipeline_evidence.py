import asyncio
from typing import AsyncIterator

import pytest

pytest.importorskip("rapidfuzz", reason="cần extra [speech] cài rapidfuzz")

from speech.asr.evidence import StabilityVerdict, TranscriptEvidenceTracker  # noqa: E402
from speech.asr.pipeline import STTPipeline  # noqa: E402
from speech.asr.vad.base import VadEvent  # noqa: E402
from speech.turn.evidence import TurnEvidence  # noqa: E402
from speech.types import Transcript, TranscriptEvent  # noqa: E402


class _NoSpeech:
    def is_speech(self, frame: bytes) -> bool:
        return False


class _FakeAsyncVAD:
    def __init__(self, events: list[VadEvent]) -> None:
        self._events = events

    async def process(self, frames: AsyncIterator[bytes]) -> AsyncIterator[VadEvent]:
        frame_iter = frames.__aiter__()
        for event in self._events:
            try:
                await frame_iter.__anext__()
            except StopAsyncIteration:
                pass
            yield event
        async for _ in frame_iter:
            pass


class _FakeASR:
    name = "fake"
    input_sample_rate = 8000

    def __init__(self, events: list[TranscriptEvent]) -> None:
        self._events = events

    def transcribe(self, segment) -> Transcript:
        raise NotImplementedError

    async def stream(self, frames: AsyncIterator[bytes]) -> AsyncIterator[TranscriptEvent]:
        frame_iter = frames.__aiter__()
        for event in self._events:
            try:
                await frame_iter.__anext__()
            except StopAsyncIteration:
                pass
            yield event
        async for _ in frame_iter:
            pass


async def _frames(count: int) -> AsyncIterator[bytes]:
    for _ in range(count):
        yield b"\x00\x00" * 240


async def _collect(gen):
    return [item async for item in gen]


async def test_evidence_tracker_observes_oscillating_partials() -> None:
    vad = _FakeAsyncVAD([])
    asr = _FakeASR(
        [
            TranscriptEvent(text="đây", is_final=False),
            TranscriptEvent(text="tại", is_final=False),
            TranscriptEvent(text="có", is_final=False),
            TranscriptEvent(text="đây", is_final=False),
        ]
    )
    verdicts = []

    class _SpyTracker(TranscriptEvidenceTracker):
        def observe(self, event):
            verdicts.append(super().observe(event))
            return verdicts[-1]

    tracker = _SpyTracker(oscillation_repeat_threshold=2)
    pipeline = STTPipeline(asr=asr, vad=vad, evidence=TurnEvidence(_NoSpeech(), transcript=tracker))

    await asyncio.wait_for(_collect(pipeline.stream(_frames(4))), timeout=2.0)

    assert verdicts[-1] == StabilityVerdict.OSCILLATING


async def test_evidence_tracker_none_by_default_does_not_break_stream() -> None:
    vad = _FakeAsyncVAD([])
    asr = _FakeASR([TranscriptEvent(text="xin chào", is_final=False)])
    pipeline = STTPipeline(asr=asr, vad=vad)

    turns = await asyncio.wait_for(_collect(pipeline.stream(_frames(2))), timeout=2.0)

    assert turns == []


if __name__ == "__main__":
    pytest.main([__file__])
