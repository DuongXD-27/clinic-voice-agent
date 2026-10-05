import asyncio
from typing import AsyncIterator

import pytest

from speech.asr.pipeline import STTPipeline
from speech.asr.vad.base import VadEvent
from speech.turn.controller import TurnController
from speech.turn.interruption import InterruptionController, InterruptionState
from speech.types import Transcript, TranscriptEvent


def _as_delays(events: list, emit_delay) -> list[float]:
    if isinstance(emit_delay, (int, float)):
        return [emit_delay] * len(events)
    return list(emit_delay)


class _FakeAsyncVAD:
    """Phát 1 chuỗi VadEvent cố định, không phụ thuộc nội dung `frames` — cô lập test
    khỏi thuật toán VAD thật, chỉ kiểm tra STTPipeline.stream() wiring đúng.

    `emit_delay` là 1 số (áp cho mọi event) hoặc 1 list độ trễ riêng từng event — dùng
    list khi test cần kiểm soát interleaving chính xác giữa VAD và ASR task song song."""

    def __init__(self, events: list[VadEvent], emit_delay=0.0) -> None:
        self._events = events
        self._delays = _as_delays(events, emit_delay)
        self.consumed_frame_count = 0

    async def process(self, frames: AsyncIterator[bytes]) -> AsyncIterator[VadEvent]:
        frame_iter = frames.__aiter__()
        for event, delay in zip(self._events, self._delays, strict=True):
            try:
                await frame_iter.__anext__()
                self.consumed_frame_count += 1
            except StopAsyncIteration:
                pass
            if delay:
                await asyncio.sleep(delay)
            yield event
        # Tiêu thụ nốt phần còn lại để _fanout không bị put() treo mãi.
        async for _ in frame_iter:
            self.consumed_frame_count += 1


class _FakeASR:
    name = "fake"
    input_sample_rate = 8000

    def __init__(self, events: list[TranscriptEvent], emit_delay=0.0) -> None:
        self._events = events
        self._delays = _as_delays(events, emit_delay)
        self.consumed_frame_count = 0

    def transcribe(self, segment) -> Transcript:
        raise NotImplementedError

    async def stream(self, frames: AsyncIterator[bytes]) -> AsyncIterator[TranscriptEvent]:
        frame_iter = frames.__aiter__()
        for event, delay in zip(self._events, self._delays, strict=True):
            try:
                await frame_iter.__anext__()
                self.consumed_frame_count += 1
            except StopAsyncIteration:
                pass
            if delay:
                await asyncio.sleep(delay)
            yield event
        async for _ in frame_iter:
            self.consumed_frame_count += 1


async def _frames(count: int) -> AsyncIterator[bytes]:
    for _ in range(count):
        yield b"\x00\x00" * 10


async def _realtime_frames(count: int) -> AsyncIterator[bytes]:
    for _ in range(count):
        yield b"\x00\x00" * 10
        await asyncio.sleep(0.01)


async def test_stream_combines_vad_and_asr_into_user_turn_completed() -> None:
    vad = _FakeAsyncVAD([VadEvent("speech_start"), VadEvent("speech_end")])
    asr = _FakeASR([TranscriptEvent(text="xin chào bác sĩ", is_final=True)])
    pipeline = STTPipeline(asr=asr, vad=vad)

    turns = await asyncio.wait_for(
        _collect(pipeline.stream(_frames(5), turn_controller=TurnController(min_speech_ms=0))),
        timeout=2.0,
    )

    assert len(turns) == 1
    assert turns[0].text == "xin chào bác sĩ"


async def test_stream_stops_after_frames_exhausted_with_no_pending_turn() -> None:
    """Không có VAD/ASR event nào dẫn đến turn — generator vẫn phải kết thúc khi audio
    hết, không treo vô hạn chờ turn không bao giờ tới."""
    vad = _FakeAsyncVAD([])
    asr = _FakeASR([])
    pipeline = STTPipeline(asr=asr, vad=vad)

    turns = await asyncio.wait_for(_collect(pipeline.stream(_frames(3))), timeout=2.0)

    assert turns == []


async def test_stream_vad_and_asr_run_concurrently_not_sequentially() -> None:
    """Nếu code vô tình await VAD xong rồi mới chạy ASR (tuần tự), thời gian chạy sẽ
    là tổng 2 delay; chạy song song thật thì chỉ xấp xỉ delay lớn nhất."""
    delay = 0.05
    vad = _FakeAsyncVAD([VadEvent("speech_start"), VadEvent("speech_end")], emit_delay=delay)
    asr = _FakeASR([TranscriptEvent(text="song song", is_final=True)], emit_delay=delay)
    pipeline = STTPipeline(asr=asr, vad=vad)

    start = asyncio.get_event_loop().time()
    turns = await asyncio.wait_for(
        _collect(pipeline.stream(_frames(5), turn_controller=TurnController(min_speech_ms=0))),
        timeout=2.0,
    )
    elapsed = asyncio.get_event_loop().time() - start

    assert len(turns) == 1
    # Tuần tự sẽ mất >= 2*2*delay (2 event mỗi luồng); song song chỉ mất ~2*delay.
    assert elapsed < delay * 5


class _FakeCancellableTTS:
    def __init__(self) -> None:
        self.cancel_calls = 0

    async def cancel(self) -> None:
        self.cancel_calls += 1


async def test_stream_feeds_interruption_controller_with_same_vad_and_asr_events() -> None:
    """interruption nhận CÙNG event với TurnController — input pipeline không bị tạm dừng
    khi bot nói, ở đây giả lập bot đang nói khi speech_start tới, xác nhận interruption
    chuyển state và gọi tts.cancel() mà không ảnh hưởng turn vẫn được emit."""
    # Thứ tự cần cho kịch bản test: speech_start (t=0) -> final "dừng lại" (t=0.02) ->
    # speech_end (t=0.04). Dùng list emit_delay để kiểm soát interleaving chính xác
    # giữa 2 task song song thay vì phụ thuộc lịch trình mặc định của event loop.
    vad = _FakeAsyncVAD([VadEvent("speech_start"), VadEvent("speech_end")], emit_delay=[0.0, 0.04])
    asr = _FakeASR([TranscriptEvent(text="dừng lại", is_final=True)], emit_delay=[0.02])
    pipeline = STTPipeline(asr=asr, vad=vad)
    tts = _FakeCancellableTTS()
    # min_speech_ms=0: final ASR đến ở t=0.02s — dưới ngưỡng mặc định 200ms của
    # InterruptionController; test này kiểm tra wiring event, không phải ngưỡng duration
    # (đã có test riêng cho duration gate trong test_interruption.py).
    interruption = InterruptionController(tts, min_speech_ms=0)
    interruption.on_bot_started_speaking()

    turns = await asyncio.wait_for(
        _collect(
            pipeline.stream(
                _frames(5),
                turn_controller=TurnController(min_speech_ms=0),
                interruption=interruption,
            )
        ),
        timeout=2.0,
    )

    assert len(turns) == 1
    assert turns[0].text == "dừng lại"
    # ASR final "dừng lại" đến trong lúc INTERRUPTION_CANDIDATE -> confirm ngay.
    assert interruption.state == InterruptionState.INTERRUPTED
    assert tts.cancel_calls == 1


async def test_stream_blocks_asr_frames_while_bot_speaking() -> None:
    """Bug thật đã gặp qua LiveKit: echo câu bot vừa nói vọng lại qua mic bị
    ZipFormerASR.stream() tích luỹ vào buffer nội bộ (không biết trạng thái
    bot_speaking của TurnController), hallucinate ra cùng 1 văn bản cố định ở MỌI
    cuộc gọi. Fix: _fanout() không đẩy frame vào asr_queue khi
    turn_controller.is_bot_speaking — ASR không được nhận frame nào trong lúc đó,
    dù VAD vẫn nhận đủ (để InterruptionController phát hiện barge-in)."""
    vad = _FakeAsyncVAD([VadEvent("speech_start"), VadEvent("speech_end")])
    asr = _FakeASR([])
    pipeline = STTPipeline(asr=asr, vad=vad)
    controller = TurnController(min_speech_ms=0)
    controller.on_bot_speaking_changed(True)

    await asyncio.wait_for(
        _collect(pipeline.stream(_frames(5), turn_controller=controller)), timeout=2.0
    )

    assert asr.consumed_frame_count == 0, "ASR không được nhận frame nào khi bot đang nói"
    assert vad.consumed_frame_count > 0, "VAD vẫn phải nhận frame để phát hiện barge-in"


async def test_confirmed_barge_in_replays_bounded_preroll_to_asr() -> None:
    # ASR phải trả về 1 partial có nghĩa để interruption confirm được (không còn đường
    # xác nhận thuần-duration — xem speech/turn/interruption.py). emit_delay=0.015 đặt
    # partial đó SAU speech_end (t=0.02, do _realtime_frames sleep 0.01/frame) nhưng vẫn
    # trong lúc còn INTERRUPTION_CANDIDATE.
    vad = _FakeAsyncVAD(
        [VadEvent("speech_start"), VadEvent("speech", b"x"), VadEvent("speech_end")]
    )
    asr = _FakeASR([TranscriptEvent(text="dừng lại", is_final=False)], emit_delay=0.015)
    pipeline = STTPipeline(
        asr=asr,
        vad=vad,
        barge_in_preroll_frames=3,
    )
    controller = TurnController(min_speech_ms=0)
    controller.on_bot_speaking_changed(True)
    tts = _FakeCancellableTTS()
    interruption = InterruptionController(tts, min_speech_ms=0)
    interruption.on_bot_started_speaking()

    await asyncio.wait_for(
        _collect(
            pipeline.stream(
                _realtime_frames(6),
                turn_controller=controller,
                interruption=interruption,
            )
        ),
        timeout=2.0,
    )

    assert tts.cancel_calls == 1  # ngắt lời được xác nhận đúng một lần
    assert 0 < asr.consumed_frame_count <= 4


async def _collect(agen):
    result = []
    async for item in agen:
        result.append(item)
    return result


if __name__ == "__main__":
    pytest.main([__file__])
