"""ASR decode chậm không được kéo VAD đứng theo, và câu không được chốt bằng partial cũ khi
ASR còn tồn audio của chính câu đó.

Log thật 24/09: decode 1,89 s nhưng cả pipeline trễ 4,38 s — `_fanout` chờ hàng đợi ASR đầy
nên VAD (và barge-in, evidence) cũng không nhận được frame mới.
"""

import asyncio
from typing import AsyncIterator

from speech.asr.pipeline import STTPipeline
from speech.asr.vad.async_stream import AsyncStreamingVAD
from speech.asr.vad.base import VadEvent
from speech.asr.vad.energy import EnergyFrameClassifier
from speech.asr.vad.streaming import StreamingVAD
from speech.turn.controller import TurnController
from speech.types import Transcript, TranscriptEvent

_LOUD = b"\x00\x10" * 240  # 30 ms @ 8 kHz
_SILENT = b"\x00\x00" * 240


class _SlowFinalASR:
    """Partial sớm, rồi một lần decode chậm 0,4 s; final chỉ tới khi đã xử lý hết câu."""

    name = "fake"
    input_sample_rate = 8000

    def __init__(self, log: list[str], final_at_frame: int) -> None:
        self._log = log
        self._final_at = final_at_frame

    def transcribe(self, segment) -> Transcript:
        raise NotImplementedError

    async def stream(self, frames: AsyncIterator) -> AsyncIterator[TranscriptEvent]:
        count = 0
        async for item in frames:
            if not isinstance(item, bytes):
                continue
            count += 1
            if count == 3:
                yield TranscriptEvent(text="tôi muốn", is_final=False)
            if count == 6:
                await asyncio.sleep(0.4)
            if count == self._final_at:
                self._log.append("asr final")
                yield TranscriptEvent(text="tôi muốn đặt lịch", is_final=True)


class _LoggingController(TurnController):
    def __init__(self, log: list[str], **kwargs) -> None:
        super().__init__(**kwargs)
        self._log = log

    async def on_vad_event(self, event: VadEvent) -> None:
        if event.kind != "speech":
            self._log.append(f"vad {event.kind}")
        await super().on_vad_event(event)


async def _realtime(frames: list[bytes]) -> AsyncIterator[bytes]:
    for frame in frames:
        yield frame
        await asyncio.sleep(0.01)


async def test_slow_asr_does_not_stall_vad_and_turn_waits_for_final() -> None:
    log: list[str] = []
    frames = [_LOUD] * 10 + [_SILENT] * 30
    pipeline = STTPipeline(
        asr=_SlowFinalASR(log, final_at_frame=len(frames)),
        vad=StreamingVAD(EnergyFrameClassifier(100.0)),
        async_vad=AsyncStreamingVAD(EnergyFrameClassifier(100.0), end_silence_ms=600),
        queue_max_frames=5,  # trước đây cũng là trần hàng đợi ASR: ASR ngủ là VAD đứng
    )
    controller = _LoggingController(log, min_speech_ms=0, max_wait_after_vad_end_ms=50)

    turns = [turn async for turn in pipeline.stream(_realtime(frames), turn_controller=controller)]

    assert log.index("vad speech_end") < log.index("asr final")
    assert [t.text for t in turns] == ["tôi muốn đặt lịch"]


async def _speak_then_end(controller: TurnController) -> None:
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="tôi muốn", is_final=False))
    await controller.on_vad_event(VadEvent("speech_end"))


async def test_turn_waits_while_asr_has_backlog_then_uses_final() -> None:
    controller = TurnController(min_speech_ms=0, max_wait_after_vad_end_ms=20)
    controller.set_asr_pending_probe(lambda: True)

    await _speak_then_end(controller)
    await asyncio.sleep(0.15)
    assert not controller.has_pending_turn()

    await controller.on_transcript_event(TranscriptEvent(text="tôi muốn đặt lịch", is_final=True))
    turn = await asyncio.wait_for(controller.get_turn(), timeout=1.0)
    assert turn.text == "tôi muốn đặt lịch"


async def test_turn_falls_back_to_partial_after_asr_wait_cap() -> None:
    controller = TurnController(
        min_speech_ms=0, max_wait_after_vad_end_ms=20, max_wait_for_asr_ms=100
    )
    controller.set_asr_pending_probe(lambda: True)

    await _speak_then_end(controller)

    turn = await asyncio.wait_for(controller.get_turn(), timeout=1.0)
    assert turn.text == "tôi muốn"


async def test_idle_asr_keeps_old_timeout_behavior() -> None:
    controller = TurnController(min_speech_ms=0, max_wait_after_vad_end_ms=20)
    controller.set_asr_pending_probe(lambda: False)

    await _speak_then_end(controller)

    turn = await asyncio.wait_for(controller.get_turn(), timeout=0.2)
    assert turn.text == "tôi muốn"
