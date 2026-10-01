"""SharedSpeechDetector: mỗi frame phân loại đúng một lần, mọi consumer đọc cùng kết quả."""

import asyncio
from typing import AsyncIterator

from speech.asr.pipeline import STTPipeline
from speech.asr.vad.async_stream import AsyncStreamingVAD
from speech.asr.vad.shared import SharedSpeechDetector
from speech.asr.vad.streaming import StreamingVAD
from speech.turn.controller import TurnController
from speech.types import Transcript, TranscriptEvent


class _CountingClassifier:
    """Có trạng thái như Silero: kết quả phụ thuộc thứ tự frame đã thấy."""

    def __init__(self) -> None:
        self.calls = 0
        self.seen: list[bytes] = []

    def is_speech(self, frame: bytes) -> bool:
        self.calls += 1
        self.seen.append(frame)
        return frame[0] == 0x10


class _ViewCheckingASR:
    name = "fake"
    input_sample_rate = 8000

    def __init__(self, view) -> None:
        self._view = view
        self.flags: list[bool] = []

    def transcribe(self, segment) -> Transcript:
        raise NotImplementedError

    async def stream(self, frames: AsyncIterator, **_kwargs) -> AsyncIterator[TranscriptEvent]:
        async for item in frames:
            if isinstance(item, bytes):
                self.flags.append(self._view.is_speech(item))
        if False:
            yield


def _frames(pattern: str) -> list[bytes]:
    # Mỗi frame một đối tượng riêng (như PCM thật từ LiveKit), "S" = có tiếng, "." = im lặng.
    return [
        bytes([0x10 if c == "S" else 0x00, index % 256]) * 240 for index, c in enumerate(pattern)
    ]


async def _aiter(frames: list[bytes]) -> AsyncIterator[bytes]:
    for frame in frames:
        yield frame
        await asyncio.sleep(0)


async def test_each_frame_is_classified_once_for_all_consumers() -> None:
    classifier = _CountingClassifier()
    detector = SharedSpeechDetector(classifier)
    frames = _frames("..SSSSS" + "." * 25)
    asr = _ViewCheckingASR(detector.view())
    pipeline = STTPipeline(
        asr=asr,
        vad=StreamingVAD(classifier),
        async_vad=AsyncStreamingVAD(detector.view(), end_silence_ms=600),
        speech_detector=detector,
    )

    await asyncio.wait_for(
        _collect(pipeline.stream(_aiter(frames), turn_controller=TurnController())), 2.0
    )

    assert classifier.calls == len(frames)
    assert classifier.seen == frames  # đúng thứ tự thời gian, không lặp
    assert asr.flags == [f[0] == 0x10 for f in frames]


async def _collect(gen) -> list:
    return [item async for item in gen]


def test_view_returns_cached_result_for_replayed_frame_and_false_for_unknown() -> None:
    classifier = _CountingClassifier()
    detector = SharedSpeechDetector(classifier, capacity=3)
    first, *rest = _frames("SS..")
    detector.classify(first)
    view = detector.view()

    assert view.is_speech(first) is True  # phát lại từ pre-roll: không suy luận lại
    assert classifier.calls == 1
    for frame in rest:
        detector.classify(frame)
    assert view.is_speech(first) is False  # đã quá cũ (capacity=3): không đoán
    assert view.is_speech(b"\x10" * 480) is False  # chưa từng qua classify()
    assert classifier.calls == 4


def test_probe_runs_once_per_classified_frame_and_is_read_back() -> None:
    class _Probe:
        def __init__(self) -> None:
            self.seen: list[bytes] = []

        def probability(self, frame: bytes) -> float:
            self.seen.append(frame)
            return 0.9 if frame[0] == 0x10 else 0.1

    probe = _Probe()
    detector = SharedSpeechDetector(_CountingClassifier(), probe=probe)
    speech, silence = _frames("S.")
    detector.classify(speech)
    detector.classify(silence)

    assert (detector.probability(speech), detector.probability(silence)) == (0.9, 0.1)
    assert detector.probability(b"\x10" * 480) is None  # chưa từng qua classify()
    assert probe.seen == [speech, silence]  # có trạng thái: đúng một lần, đúng thứ tự


def test_broken_probe_is_disabled_without_affecting_classification() -> None:
    class _Broken:
        def probability(self, frame: bytes) -> float:
            raise RuntimeError("onnx")

    detector = SharedSpeechDetector(_CountingClassifier(), probe=_Broken())
    speech, other = _frames("SS")

    assert detector.classify(speech) is True
    assert detector.classify(other) is True
    assert detector.probability(speech) is None
    assert detector.has_probe is False
