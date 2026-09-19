"""Fake ASR/TTS cho test HTTP transport — không đụng provider thật (Gemini/OpenAI/ZipFormer)."""

from pathlib import Path
from typing import AsyncIterator, Callable, Optional

from callbot.speech.tts.storage import AudioArtifactStore
from callbot.speech.types import AudioSegment, Transcript, TranscriptEvent
from callbot.transports.http.speech import SpeechBundle

_SILENT_SEGMENT = AudioSegment(pcm=b"\x00\x00" * 100, sample_rate=8000)


class FakeASR:
    name = "fake"
    input_sample_rate = 16000

    def __init__(self, transcript: str = "") -> None:
        self.transcript = transcript
        self.received: list[AudioSegment] = []

    def transcribe(self, segment: AudioSegment) -> Transcript:
        self.received.append(segment)
        return Transcript(text=self.transcript, is_silence=not self.transcript)

    async def stream(self, frames: AsyncIterator[bytes]) -> AsyncIterator[TranscriptEvent]:
        raise NotImplementedError
        yield  # pragma: no cover


class FakeTTS:
    name = "fake"

    def __init__(self, respond: bool = True) -> None:
        self.respond = respond
        self.spoken: list[str] = []

    def synthesize(self, text: str) -> Optional[AudioSegment]:
        self.spoken.append(text)
        if not self.respond or not text.strip():
            return None
        return _SILENT_SEGMENT


def make_speech_bundle(
    audio_dir: Path,
    *,
    base_url: str = "http://test",
    asr: Optional[FakeASR] = None,
    tts: Optional[FakeTTS] = None,
    audio_loader: Optional[Callable[[str], AudioSegment]] = None,
) -> SpeechBundle:
    """Bundle an toàn cho test — không import/gọi sherpa-onnx, openai hay Gemini thật.

    Fake nên `respond=True` mặc định không có rủi ro (không gọi network) — cứ trả
    audio giả, để test contract mode=audio dùng client fixture chung vẫn thấy đúng
    hành vi thật (audio_url khác None) mà không cần dựng riêng một app.
    """
    return SpeechBundle(
        asr=asr or FakeASR(),
        tts=tts if tts is not None else FakeTTS(respond=True),
        audio_store=AudioArtifactStore(str(audio_dir), base_url),
        audio_loader=audio_loader or (lambda url: _SILENT_SEGMENT),
    )
