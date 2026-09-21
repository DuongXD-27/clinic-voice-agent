"""OpenAI TTS provider."""

from inference.tts.base import TTSResult
from inference.tts.config import OpenAITTSConfig

_PCM_SAMPLE_RATE = 24_000  # khớp response_format="pcm" của OpenAI (PCM 16-bit, 24kHz, mono)


class OpenAITTS:
    def __init__(self, config: OpenAITTSConfig) -> None:
        self._config = config
        self._client = None

    @property
    def model(self) -> str:
        return self._config.model

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI  # pip install -e ".[speech-zipformer]"

            self._client = OpenAI(api_key=self._config.api_key.get_secret_value())
        return self._client

    def synthesize(self, text: str) -> TTSResult:
        response = self._get_client().audio.speech.create(
            model=self._config.model,
            voice=self._config.voice,
            input=text,
            response_format="pcm",
        )
        return TTSResult(pcm=response.read(), sample_rate=_PCM_SAMPLE_RATE)
