"""Realtime STT pipeline: Audio Input (PCM 8 kHz băng hẹp) -> VAD -> ASR -> Streaming Transcript."""

from typing import AsyncIterator, Optional

from callbot.speech.audio.codec import to_sample_rate
from callbot.speech.audio.loader import load_from_url
from callbot.speech.types import NARROWBAND_RATE, AudioSegment, Transcript, TranscriptEvent
from callbot.speech.vad.streaming import StreamingVAD, split_frames
from inference.asr.base import ASRProvider


class STTPipeline:
    def __init__(
        self, asr: ASRProvider, vad: StreamingVAD, sample_rate: int = NARROWBAND_RATE
    ) -> None:
        self._asr = asr
        self._vad = vad
        self._sample_rate = sample_rate

    def transcribe_turn(
        self, text: Optional[str], audio_url: Optional[str], silence_ms: int
    ) -> Transcript:
        """Một lượt của harness (§4.1): text mode, audio mode, hoặc im lặng."""
        if silence_ms > 0:
            return Transcript(is_silence=True)
        if text is not None:
            return Transcript(text=text.strip(), is_silence=not text.strip())
        if audio_url:
            return self.transcribe_segment(load_from_url(audio_url, self._sample_rate))
        return Transcript(is_silence=True)

    def transcribe_segment(self, segment: AudioSegment) -> Transcript:
        segment = to_sample_rate(segment, self._sample_rate)
        has_speech = any(
            event.kind == "speech"
            for event in self._vad.process(split_frames(segment.pcm, segment.sample_rate))
        )
        # Không có tiếng nói thì bỏ qua ASR — giảm cost per session (§5)
        if not has_speech:
            return Transcript(is_silence=True)
        return self._asr.transcribe(segment)

    async def stream(self, frames: AsyncIterator[bytes]) -> AsyncIterator[TranscriptEvent]:
        """Phone leg (§1.3.2): adapter giải mã G.711 (audio.g711) rồi đẩy frame PCM 8 kHz vào đây.

        TODO: VAD streaming + barge-in (dừng TTS, dừng LLM, giữ partial, reset lượt).
        """
        async for event in self._asr.stream(frames):
            yield event
