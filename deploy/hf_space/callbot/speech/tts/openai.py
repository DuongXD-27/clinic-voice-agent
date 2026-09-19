"""OpenAI TTS — provider TẠM THỜI để nghe thử giọng nói khi chưa chốt provider chính thức.

Port từ nhánh `prototype` (đã verify chạy được ở đó qua prototype/test_tts.py) sang
`main` để dùng cho scripts/voice_gateway.py (temp/plan_mvp_zipformer.md Phase 4).
"""

from typing import Optional

from callbot.speech.types import AudioSegment

_PCM_SAMPLE_RATE = 24_000  # khớp response_format="pcm" của OpenAI (PCM 16-bit, 24kHz, mono)


class OpenAITTS:
    name = "openai"

    def __init__(self, api_key: str, model: str, voice: str) -> None:
        self._api_key = api_key
        self._model = model
        self._voice = voice
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI  # pip install -e ".[speech-zipformer]"

            self._client = OpenAI(api_key=self._api_key)
        return self._client

    def synthesize(self, text: str) -> Optional[AudioSegment]:
        if not text.strip():
            return None
        response = self._get_client().audio.speech.create(
            model=self._model,
            voice=self._voice,
            input=text,
            response_format="pcm",
        )
        return AudioSegment(pcm=response.read(), sample_rate=_PCM_SAMPLE_RATE)
