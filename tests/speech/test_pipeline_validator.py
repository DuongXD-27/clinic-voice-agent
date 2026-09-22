import asyncio
from typing import AsyncIterator

import pytest

pytest.importorskip("rapidfuzz", reason="cần extra [speech] cài rapidfuzz")

from speech.asr.admission import SpeechAdmission  # noqa: E402
from speech.asr.evidence import TranscriptEvidenceTracker  # noqa: E402
from speech.asr.pipeline import STTPipeline  # noqa: E402
from speech.asr.vad.base import VadEvent  # noqa: E402
from speech.asr.vad.streaming import StreamingVAD  # noqa: E402
from speech.audio.noise_tracker import NoiseTracker  # noqa: E402
from speech.turn.controller import TurnController  # noqa: E402
from speech.turn.validator import TurnValidator  # noqa: E402
from speech.types import Transcript, TranscriptEvent  # noqa: E402


class _NullEnergyClassifier:
    def is_speech(self, frame: bytes) -> bool:
        return False


class _AlwaysSpeechClassifier:
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


async def _frames(count: int, frame: bytes = b"\x00\x00" * 240) -> AsyncIterator[bytes]:
    for _ in range(count):
        yield frame


async def _collect(gen):
    return [item async for item in gen]


async def test_hallucination_pattern_from_real_noise_is_dropped_end_to_end() -> None:
    """Tái hiện đúng mẫu hallucination thật đã quan sát qua LiveKit (docs/reference/
    livekit-architecture.md §5.4): ASR liên tục ra 1 từ ngắn khác nhau ("đây"/"tại")
    trên audio silence (rms thấp, gần noise_floor) -> toàn bộ pipeline (evidence +
    validator) phải chặn được, không emit turn giả."""
    vad = _FakeAsyncVAD([VadEvent("speech_start"), VadEvent("speech_end")])
    asr = _FakeASR(
        [
            TranscriptEvent(text="đây", is_final=False),
            TranscriptEvent(text="tại", is_final=False),
            TranscriptEvent(text="có", is_final=False),
            TranscriptEvent(text="đây", is_final=True),
        ]
    )
    evidence_tracker = TranscriptEvidenceTracker(oscillation_repeat_threshold=2)
    noise_tracker = NoiseTracker(initial_floor=50.0)
    validator = TurnValidator()
    turn_controller = TurnController(min_speech_ms=0, validator=validator)
    pipeline = STTPipeline(asr=asr, vad=StreamingVAD(_NullEnergyClassifier()), async_vad=vad)

    # Frame silence-like (biên độ thấp, gần noise_floor mặc định) — is_speech=True theo
    # classifier giả (đúng tình huống thật: VAD sai nhận noise thành speech).
    silence_like_frame = b"\x00\x05" * 240

    turns = await asyncio.wait_for(
        _collect(
            pipeline.stream(
                _frames(4, frame=silence_like_frame),
                turn_controller=turn_controller,
                evidence_tracker=evidence_tracker,
                noise_tracker=noise_tracker,
                noise_classifier=_AlwaysSpeechClassifier(),
            )
        ),
        timeout=2.0,
    )

    assert turns == [], f"phải chặn turn hallucination giả, nhưng emit: {turns}"


async def test_validator_none_by_default_keeps_old_behavior() -> None:
    vad = _FakeAsyncVAD([VadEvent("speech_start"), VadEvent("speech_end")])
    asr = _FakeASR([TranscriptEvent(text="tôi muốn đổi lịch", is_final=True)])
    turn_controller = TurnController(min_speech_ms=0)
    pipeline = STTPipeline(asr=asr, vad=StreamingVAD(_NullEnergyClassifier()), async_vad=vad)

    turns = await asyncio.wait_for(
        _collect(pipeline.stream(_frames(4), turn_controller=turn_controller)), timeout=2.0
    )

    assert len(turns) == 1
    assert turns[0].text == "tôi muốn đổi lịch"


async def test_noise_tracker_requires_classifier() -> None:
    asr = _FakeASR([])
    pipeline = STTPipeline(
        asr=asr, vad=StreamingVAD(_NullEnergyClassifier()), async_vad=_FakeAsyncVAD([])
    )

    with pytest.raises(ValueError):
        await asyncio.wait_for(
            _collect(pipeline.stream(_frames(1), noise_tracker=NoiseTracker())), timeout=2.0
        )


async def test_admission_and_validator_use_independent_trackers() -> None:
    """Speech Admission và TurnValidator's NoiseTracker là 2 instance ĐỘC LẬP (xem
    docstring stream()) — cấu hình cả 2 cùng lúc không được crash hay xung đột state."""
    vad = _FakeAsyncVAD([VadEvent("speech_start"), VadEvent("speech_end")])
    asr = _FakeASR([TranscriptEvent(text="tôi muốn đổi lịch", is_final=True)])
    admission = SpeechAdmission(min_snr_db=-100.0, min_speech_ms=0)  # luôn admit
    validator = TurnValidator()
    turn_controller = TurnController(min_speech_ms=0, validator=validator)
    pipeline = STTPipeline(
        asr=asr,
        vad=StreamingVAD(_NullEnergyClassifier()),
        async_vad=vad,
        admission=admission,
        admission_classifier=_AlwaysSpeechClassifier(),
    )

    turns = await asyncio.wait_for(
        _collect(
            pipeline.stream(
                _frames(4),
                turn_controller=turn_controller,
                noise_tracker=NoiseTracker(),
                noise_classifier=_AlwaysSpeechClassifier(),
                evidence_tracker=TranscriptEvidenceTracker(),
            )
        ),
        timeout=2.0,
    )

    assert len(turns) == 1


if __name__ == "__main__":
    pytest.main([__file__])
