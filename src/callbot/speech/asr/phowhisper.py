from typing import AsyncIterator

from callbot.speech.audio.codec import to_sample_rate
from callbot.speech.types import WIDEBAND_RATE, AudioSegment, Transcript, TranscriptEvent


class PhoWhisperASR:
    """PhoWhisper self-hosted qua transformers.

    Whisper chỉ nhận 16 kHz: audio 8 kHz được upsample, nhưng dải trên 4 kHz đã mất
    từ đường dây — WER sẽ cao hơn số công bố trên 16 kHz sạch. Appendix B.1: đo trên
    audio điện thoại của team trước khi chốt (ZipFormer đã vượt PhoWhisper trên tiếng Việt).
    """

    name = "phowhisper"
    input_sample_rate = WIDEBAND_RATE

    def __init__(self, model: str) -> None:
        self._model = model
        self._pipe = None

    def _get_pipe(self):
        if self._pipe is None:
            from transformers import pipeline  # pip install -e ".[speech-local]"

            self._pipe = pipeline("automatic-speech-recognition", model=self._model)
        return self._pipe

    def transcribe(self, segment: AudioSegment) -> Transcript:
        import numpy as np

        segment = to_sample_rate(segment, self.input_sample_rate)
        samples = np.frombuffer(segment.pcm, dtype=np.int16).astype(np.float32) / 32768.0
        if samples.size == 0:
            return Transcript(is_silence=True)
        output = self._get_pipe()({"raw": samples, "sampling_rate": segment.sample_rate})
        text = output.get("text", "").strip()
        return Transcript(text=text, is_silence=not text)

    async def stream(self, frames: AsyncIterator[bytes]) -> AsyncIterator[TranscriptEvent]:
        # TODO: Whisper không streaming thật — gom đoạn theo VAD rồi transcribe từng đoạn
        raise NotImplementedError
        yield  # pragma: no cover
