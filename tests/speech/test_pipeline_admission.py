import asyncio
from typing import AsyncIterator

from speech.asr.admission import SpeechAdmission
from speech.asr.pipeline import STTPipeline
from speech.asr.vad.base import VadEvent
from speech.asr.vad.streaming import StreamingVAD
from speech.turn.controller import TurnController
from speech.types import Transcript, TranscriptEvent


class _NullEnergyClassifier:
    def is_speech(self, frame: bytes) -> bool:
        return False


class _AlwaysSpeechClassifier:
    """Admission classifier độc lập — luôn báo speech để cô lập test khỏi thuật toán
    phân loại thật, chỉ kiểm tra wiring Admission trong _fanout()."""

    def is_speech(self, frame: bytes) -> bool:
        return True


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

    def __init__(self) -> None:
        self.consumed_frame_count = 0

    def transcribe(self, segment) -> Transcript:
        raise NotImplementedError

    async def stream(self, frames: AsyncIterator[bytes]) -> AsyncIterator[TranscriptEvent]:
        async for _ in frames:
            self.consumed_frame_count += 1
        return
        yield  # pragma: no cover - hàm generator, không có event nào emit trong test này


async def _frames(count: int, frame: bytes = b"\x00\x00" * 240) -> AsyncIterator[bytes]:
    for _ in range(count):
        yield frame


async def _collect(gen):
    return [item async for item in gen]


async def test_admission_blocks_low_snr_frames_from_reaching_asr() -> None:
    """Frame is_speech=True nhưng SNR quá thấp (silence thuần -> rms=noise_floor -> snr=0)
    bị Admission chặn — không tới ASR dù classifier báo speech."""
    vad = _FakeAsyncVAD([])
    asr = _FakeASR()
    admission = SpeechAdmission(min_snr_db=6.0, min_speech_ms=0)
    pipeline = STTPipeline(
        asr=asr,
        vad=StreamingVAD(_NullEnergyClassifier()),
        async_vad=vad,
        admission=admission,
        admission_classifier=_AlwaysSpeechClassifier(),
    )

    await asyncio.wait_for(
        _collect(pipeline.stream(_frames(5, frame=b"\x00\x00" * 240))), timeout=2.0
    )

    assert asr.consumed_frame_count == 0


async def test_admission_admits_high_snr_frames_after_min_duration() -> None:
    """Frame biên độ lớn (SNR cao so với noise_floor mặc định) đủ min_speech_ms -> admit,
    tới được ASR."""
    vad = _FakeAsyncVAD([])
    asr = _FakeASR()
    admission = SpeechAdmission(min_snr_db=6.0, min_speech_ms=30)
    loud_frame = b"\x00\x7f" * 240  # amplitude lớn -> SNR cao so với noise_floor mặc định
    pipeline = STTPipeline(
        asr=asr,
        vad=StreamingVAD(_NullEnergyClassifier()),
        async_vad=vad,
        admission=admission,
        admission_classifier=_AlwaysSpeechClassifier(),
    )

    await asyncio.wait_for(_collect(pipeline.stream(_frames(5, frame=loud_frame))), timeout=2.0)

    assert asr.consumed_frame_count > 0


async def test_admission_disabled_by_default_keeps_old_behavior() -> None:
    vad = _FakeAsyncVAD([])
    asr = _FakeASR()
    pipeline = STTPipeline(asr=asr, vad=StreamingVAD(_NullEnergyClassifier()), async_vad=vad)

    await asyncio.wait_for(_collect(pipeline.stream(_frames(5))), timeout=2.0)

    assert asr.consumed_frame_count == 5


async def test_stream_with_min_speech_ms_zero_still_works_with_turn_controller() -> None:
    """Sanity: pipeline vẫn hoạt động bình thường khi admission=None (mặc định) dù dùng
    TurnController tuỳ chỉnh — không có hồi quy khi wiring mới không được kích hoạt."""
    vad = _FakeAsyncVAD([VadEvent("speech_start"), VadEvent("speech_end")])

    class _AsrWithFinal:
        name = "fake"
        input_sample_rate = 8000

        def transcribe(self, segment) -> Transcript:
            raise NotImplementedError

        async def stream(self, frames: AsyncIterator[bytes]) -> AsyncIterator[TranscriptEvent]:
            frame_iter = frames.__aiter__()
            await frame_iter.__anext__()
            yield TranscriptEvent(text="ok", is_final=True)
            async for _ in frame_iter:
                pass

    asr = _AsrWithFinal()
    pipeline = STTPipeline(asr=asr, vad=StreamingVAD(_NullEnergyClassifier()), async_vad=vad)

    turns = await asyncio.wait_for(
        _collect(pipeline.stream(_frames(5), turn_controller=TurnController(min_speech_ms=0))),
        timeout=2.0,
    )

    assert len(turns) == 1
    assert turns[0].text == "ok"
