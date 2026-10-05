import asyncio
from typing import AsyncIterator

import pytest

pytest.importorskip("rapidfuzz", reason="cần extra [speech] cài rapidfuzz")

from tests.speech.pipeline_factory import make_stt_pipeline  # noqa: E402

from speech.asr.evidence import StabilityVerdict, TranscriptEvidenceTracker  # noqa: E402
from speech.asr.vad.base import VadEvent  # noqa: E402
from speech.audio.noise_tracker import NoiseTracker  # noqa: E402
from speech.turn.controller import TurnController  # noqa: E402
from speech.turn.evidence import TurnEvidence  # noqa: E402
from speech.turn.validator import TurnValidator  # noqa: E402
from speech.types import Transcript, TranscriptEvent  # noqa: E402


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
    # Classifier giả luôn báo có tiếng nói (đúng tình huống thật: VAD nhận nhầm nhiễu).
    evidence = TurnEvidence(
        _AlwaysSpeechClassifier(), frame_ms=30, transcript=evidence_tracker, noise=noise_tracker
    )
    pipeline = make_stt_pipeline(asr=asr, vad=vad, evidence=evidence)

    # Frame gần như im lặng (biên độ thấp, gần noise_floor mặc định).
    silence_like_frame = b"\x00\x05" * 240

    turns = await asyncio.wait_for(
        _collect(
            pipeline.stream(_frames(4, frame=silence_like_frame), turn_controller=turn_controller)
        ),
        timeout=2.0,
    )

    assert turns == [], f"phải chặn turn hallucination giả, nhưng emit: {turns}"


async def test_validator_none_by_default_keeps_old_behavior() -> None:
    vad = _FakeAsyncVAD([VadEvent("speech_start"), VadEvent("speech_end")])
    asr = _FakeASR([TranscriptEvent(text="tôi muốn đổi lịch", is_final=True)])
    turn_controller = TurnController(min_speech_ms=0)
    pipeline = make_stt_pipeline(asr=asr, vad=vad)

    turns = await asyncio.wait_for(
        _collect(pipeline.stream(_frames(4), turn_controller=turn_controller)), timeout=2.0
    )

    assert len(turns) == 1
    assert turns[0].text == "tôi muốn đổi lịch"


class _ByFrameClassifier:
    def __init__(self, speech_frame: bytes) -> None:
        self._speech_frame = speech_frame

    def is_speech(self, frame: bytes) -> bool:
        return frame == self._speech_frame


class _FinalAfterFramesASR:
    """Phát final sau khi đã nhận đủ số frame — như ZipFormer chỉ chốt câu sau ~1 s im lặng."""

    name = "fake"
    input_sample_rate = 8000

    def __init__(self, finals: list[tuple[int, str]]) -> None:
        self._finals = finals

    def transcribe(self, segment) -> Transcript:
        raise NotImplementedError

    async def stream(self, frames: AsyncIterator[bytes]) -> AsyncIterator[TranscriptEvent]:
        received = 0
        pending = list(self._finals)
        async for _ in frames:
            received += 1
            while pending and received >= pending[0][0]:
                yield TranscriptEvent(text=pending.pop(0)[1], is_final=True)


async def _sequence(frames: list[bytes]) -> AsyncIterator[bytes]:
    for frame in frames:
        yield frame
        await asyncio.sleep(0)


async def test_short_answer_final_after_silence_is_not_dropped() -> None:
    """Hồi quy: "DẠ KHÔNG" nói rõ trên audio sạch từng bị DROP.

    Final tới sau đoạn im lặng; validator từng đọc SNR của frame im lặng mới nhất (đo được
    snr=-13.6 dB) và áp luật "<= 2 từ + SNR thấp". Phải đọc SNR của chính câu nói."""
    loud, silence = b"\x00\x40" * 240, b"\x01\x00" * 240
    frames = [silence] * 10 + [loud] * 15 + [silence] * 35
    asr = _FinalAfterFramesASR([(len(frames), "dạ không")])
    vad = _FakeAsyncVAD([VadEvent("speech")] * 10 + [VadEvent("speech_start")])
    controller = TurnController(min_speech_ms=0, validator=TurnValidator(min_snr_db=3.0))
    evidence = TurnEvidence(_ByFrameClassifier(loud), frame_ms=30)
    pipeline = make_stt_pipeline(asr=asr, vad=vad, evidence=evidence)

    turns = await asyncio.wait_for(
        _collect(pipeline.stream(_sequence(frames), turn_controller=controller)),
        timeout=2.0,
    )

    assert [turn.text for turn in turns] == ["dạ không"]


async def test_stability_is_judged_per_utterance() -> None:
    """Hồi quy: tracker không reset giữa các câu nên chuỗi trả lời thật "vâng" -> "có" ->
    "vâng" khớp mẫu dao động, câu thứ ba bị coi là ảo giác."""

    class _SpyTracker(TranscriptEvidenceTracker):
        def __init__(self) -> None:
            super().__init__()
            self.final_verdicts = []

        def observe(self, event):
            verdict = super().observe(event)
            if event.is_final:
                self.final_verdicts.append(verdict)
            return verdict

    tracker = _SpyTracker()
    asr = _FinalAfterFramesASR([(5, "vâng"), (10, "có"), (15, "vâng")])
    pipeline = make_stt_pipeline(
        asr=asr,
        vad=_FakeAsyncVAD([]),
        evidence=TurnEvidence(_AlwaysSpeechClassifier(), frame_ms=30, transcript=tracker),
    )

    await asyncio.wait_for(
        _collect(
            pipeline.stream(
                _sequence([b"\x00\x40" * 240] * 20),
                turn_controller=TurnController(min_speech_ms=0),
            )
        ),
        timeout=2.0,
    )

    assert StabilityVerdict.OSCILLATING not in tracker.final_verdicts


if __name__ == "__main__":
    pytest.main([__file__])
