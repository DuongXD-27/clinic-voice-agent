from inference.asr.base import ASRResult
from inference.asr.config import PhoWhisperConfig


class PhoWhisperASR:
    """PhoWhisper self-hosted qua transformers.

    Whisper chỉ nhận 16 kHz: audio 8 kHz được upsample, nhưng dải trên 4 kHz đã mất
    từ đường dây — WER sẽ cao hơn số công bố trên 16 kHz sạch. Appendix B.1: đo trên
    audio điện thoại của team trước khi chốt (ZipFormer đã vượt PhoWhisper trên tiếng Việt).
    """

    input_sample_rate = 16_000

    def __init__(self, config: PhoWhisperConfig) -> None:
        self._config = config
        self._pipe = None

    @property
    def model(self) -> str:
        return self._config.model

    def _get_pipe(self):
        if self._pipe is None:
            from transformers import pipeline  # pip install -e ".[speech-local]"

            self._pipe = pipeline("automatic-speech-recognition", model=self._config.model)
        return self._pipe

    def transcribe(self, pcm: bytes) -> ASRResult:
        import numpy as np

        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        output = self._get_pipe()({"raw": samples, "sampling_rate": self.input_sample_rate})
        return ASRResult(text=output.get("text", "").strip())
