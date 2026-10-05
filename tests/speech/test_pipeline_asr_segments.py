"""STTPipeline báo cho ASR mỗi khi ngừng đưa audio (AsrSegmentEnd).

Bug thật (cuộc gọi LiveKit 2026-09-26): ASR chỉ tự chốt câu khi thấy đủ khoảng lặng trong
các frame nó nhận. Bot bắt đầu nói giữa câu người dùng — câu dở nằm lại buffer, thành lượt
"ANH SINH ANH SINH NGÀY ...". (Nhánh Speech Admission — ngừng gửi im lặng lúc ASR mới thấy
570/600 ms — đã gỡ cùng Admission 28/09.)
"""

import asyncio
from typing import AsyncIterator

from speech.asr.pipeline import STTPipeline
from speech.asr.vad.base import VadEvent
from speech.turn.controller import TurnController
from speech.turn.interruption import InterruptionController, InterruptionState
from speech.types import AsrSegmentEnd, Transcript, TranscriptEvent


class _FakeAsyncVAD:
    """Phát một VadEvent sau mỗi frame nhận được, theo thứ tự cho sẵn."""

    def __init__(self, events: list[VadEvent]) -> None:
        self._events = events

    async def process(self, frames: AsyncIterator[bytes]) -> AsyncIterator[VadEvent]:
        frame_iter = frames.__aiter__()
        for event in self._events:
            try:
                await frame_iter.__anext__()
            except StopAsyncIteration:
                return
            yield event
        async for _ in frame_iter:
            pass


class _RecordingASR:
    """Ghi lại mọi phần tử ASR nhận (frame và AsrSegmentEnd) theo đúng thứ tự; tuỳ chọn
    phát một partial sau `partial_after` frame để xác nhận barge-in."""

    name = "fake"
    input_sample_rate = 8000

    def __init__(self, partial_after: int | None = None) -> None:
        self.items: list = []
        self._partial_after = partial_after

    def transcribe(self, segment) -> Transcript:
        raise NotImplementedError

    async def stream(self, frames: AsyncIterator) -> AsyncIterator[TranscriptEvent]:
        async for item in frames:
            self.items.append(item)
            if len(self.items) == self._partial_after:
                yield TranscriptEvent(text="dừng lại", is_final=False)


class _FakeCancellableTTS:
    def __init__(self) -> None:
        self.cancel_calls = 0

    async def cancel(self) -> None:
        self.cancel_calls += 1


def _make_frame(tag: int) -> bytes:
    return bytes([tag, 0x7F]) * 240


async def _realtime(frames: list[bytes], before_frame=None) -> AsyncIterator[bytes]:
    for index, frame in enumerate(frames):
        if before_frame is not None:
            before_frame(index)
        yield frame
        await asyncio.sleep(0.01)


async def _collect(gen) -> list:
    return [item async for item in gen]


async def test_bot_starting_to_speak_discards_pending_asr_segment() -> None:
    """Bot bắt đầu nói giữa câu người dùng: phần đã gửi ASR bị bỏ, không nằm lại để ghép
    vào câu sau."""
    frames = [_make_frame(i) for i in range(1, 7)]
    controller = TurnController(min_speech_ms=0)
    asr = _RecordingASR()
    pipeline = STTPipeline(asr=asr, vad=_FakeAsyncVAD([]))

    def _bot_starts_at_frame_3(index: int) -> None:
        if index == 3:
            controller.on_bot_speaking_changed(True)

    await asyncio.wait_for(
        _collect(
            pipeline.stream(_realtime(frames, _bot_starts_at_frame_3), turn_controller=controller)
        ),
        timeout=2.0,
    )

    assert asr.items == frames[:3] + [AsrSegmentEnd.DISCARD]


async def test_rejected_barge_in_candidate_discards_asr_segment() -> None:
    """Ứng viên ngắt lời không được xác nhận (VAD speech_end trước khi ASR có chữ): audio đã
    gửi ASR phải bị bỏ, không thành tiền tố của câu người dùng nói sau khi bot dứt lời."""
    controller = TurnController(min_speech_ms=0)
    controller.on_bot_speaking_changed(True)
    tts = _FakeCancellableTTS()
    interruption = InterruptionController(tts, min_speech_ms=0)
    interruption.on_bot_started_speaking()
    vad = _FakeAsyncVAD(
        [VadEvent("speech_start"), VadEvent("speech", b"x"), VadEvent("speech_end")]
    )
    asr = _RecordingASR()
    pipeline = STTPipeline(asr=asr, vad=vad)

    frames = [_make_frame(i) for i in range(1, 8)]
    await asyncio.wait_for(
        _collect(
            pipeline.stream(
                _realtime(frames), turn_controller=controller, interruption=interruption
            )
        ),
        timeout=2.0,
    )

    assert tts.cancel_calls == 0  # không xác nhận ngắt lời
    assert asr.items.count(AsrSegmentEnd.DISCARD) == 1
    assert len(asr.items) > 1 and asr.items[-1] is AsrSegmentEnd.DISCARD


async def test_confirmed_barge_in_keeps_asr_segment() -> None:
    """Sau khi xác nhận ngắt lời (INTERRUPTED), bot chưa dừng hẳn nên frame tạm không vào
    ASR — nhưng phần người dùng đã nói phải được GIỮ để chốt thành turn, không bị bỏ."""
    controller = TurnController(min_speech_ms=0)
    controller.on_bot_speaking_changed(True)
    interruption = InterruptionController(_FakeCancellableTTS(), min_speech_ms=0)
    interruption.on_bot_started_speaking()
    vad = _FakeAsyncVAD([VadEvent("speech_start")] + [VadEvent("speech", b"x")] * 7)
    asr = _RecordingASR(partial_after=2)
    pipeline = STTPipeline(asr=asr, vad=vad)

    frames = [_make_frame(i) for i in range(1, 9)]
    await asyncio.wait_for(
        _collect(
            pipeline.stream(
                _realtime(frames), turn_controller=controller, interruption=interruption
            )
        ),
        timeout=2.0,
    )

    assert interruption.state == InterruptionState.INTERRUPTED
    assert AsrSegmentEnd.DISCARD not in asr.items


async def test_no_marker_when_asr_received_nothing() -> None:
    """Chưa gửi frame nào vào ASR thì không có gì để chốt/bỏ — không gửi tín hiệu thừa."""
    controller = TurnController(min_speech_ms=0)
    controller.on_bot_speaking_changed(True)
    asr = _RecordingASR()
    pipeline = STTPipeline(asr=asr, vad=_FakeAsyncVAD([]))

    frames = [_make_frame(i) for i in range(1, 5)]
    await asyncio.wait_for(
        _collect(pipeline.stream(_realtime(frames), turn_controller=controller)), timeout=2.0
    )

    assert asr.items == []
