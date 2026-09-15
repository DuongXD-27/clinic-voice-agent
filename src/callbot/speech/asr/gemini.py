from typing import AsyncIterator

from callbot.speech.audio.codec import encode_wav
from callbot.speech.types import NARROWBAND_RATE, AudioSegment, Transcript, TranscriptEvent

TRANSCRIBE_PROMPT = (
    "Chép lại chính xác lời người nói tiếng Việt trong đoạn ghi âm cuộc gọi điện thoại. "
    "Chỉ trả về văn bản, không giải thích. Nếu không có lời nói, trả về chuỗi rỗng."
)


class GeminiASR:
    name = "gemini"
    # Gemini nhận wav ở tần số bất kỳ — gửi thẳng 8 kHz, không upsample (payload nhỏ hơn)
    input_sample_rate = NARROWBAND_RATE

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google import genai  # pip install -e ".[speech]"

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def transcribe(self, segment: AudioSegment) -> Transcript:
        from google.genai import types

        response = self._get_client().models.generate_content(
            model=self._model,
            contents=[
                TRANSCRIBE_PROMPT,
                types.Part.from_bytes(data=encode_wav(segment), mime_type="audio/wav"),
            ],
        )
        text = (response.text or "").strip()
        return Transcript(text=text, is_silence=not text)

    async def stream(self, frames: AsyncIterator[bytes]) -> AsyncIterator[TranscriptEvent]:
        # TODO: Gemini Live API — kiểm tra tần số PCM Live API nhận, upsample frame 8 kHz nếu cần
        raise NotImplementedError
        yield  # pragma: no cover
