"""ASR/VAD/input failure propagates instead of becoming an empty or silent turn."""

import asyncio

import pytest

from speech.asr.pipeline import STTPipeline
from speech.asr.vad.async_stream import AsyncStreamingVAD
from speech.asr.vad.energy import EnergyFrameClassifier


class _ASR:
    async def stream(self, frames):
        async for _frame in frames:
            pass
        if False:
            yield


class _BrokenASR:
    async def stream(self, frames):
        raise RuntimeError("asr failure")
        yield


class _BrokenVAD:
    async def process(self, frames):
        raise RuntimeError("vad failure")
        yield


async def _frames(broken=False):
    if broken:
        raise RuntimeError("input failure")
    for _ in range(5):
        yield b"\x00\x10" * 240
        await asyncio.sleep(0)


@pytest.mark.parametrize("stage", ["asr", "vad", "input"])
@pytest.mark.parametrize("queue_size", [1, 50])
async def test_stream_worker_error_propagates_without_a_caller_turn(stage, queue_size):
    pipeline = STTPipeline(
        asr=_BrokenASR() if stage == "asr" else _ASR(),
        vad=_BrokenVAD() if stage == "vad" else AsyncStreamingVAD(EnergyFrameClassifier(100)),
        queue_max_frames=queue_size,
    )
    turns = []

    async def collect():
        async for turn in pipeline.stream(_frames(broken=stage == "input")):
            turns.append(turn)

    with pytest.raises(RuntimeError, match=f"{stage} failure"):
        await asyncio.wait_for(collect(), timeout=1)
    assert turns == []
