import io
import wave

from inference.asr.base import ASRResult
from inference.asr.config import GeminiASRConfig

TRANSCRIBE_PROMPT = (
    "Chép lại chính xác lời người nói tiếng Việt trong đoạn ghi âm cuộc gọi điện thoại. "
    "Chỉ trả về văn bản, không giải thích. Nếu không có lời nói, trả về chuỗi rỗng."
)


def _wav(pcm: bytes, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(pcm)
    return buffer.getvalue()


class GeminiASR:
    # Gemini nhận wav ở tần số bất kỳ — gửi thẳng 8 kHz, không upsample (payload nhỏ hơn)
    input_sample_rate = 8_000

    def __init__(self, config: GeminiASRConfig) -> None:
        self._config = config
        self._client = None

    @property
    def model(self) -> str:
        return self._config.model

    def _get_client(self):
        if self._client is None:
            from google import genai  # pip install -e ".[speech]"

            self._client = genai.Client(api_key=self._config.api_key.get_secret_value())
        return self._client

    def transcribe(self, pcm: bytes) -> ASRResult:
        from google.genai import types

        response = self._get_client().models.generate_content(
            model=self._config.model,
            contents=[
                TRANSCRIBE_PROMPT,
                types.Part.from_bytes(
                    data=_wav(pcm, self.input_sample_rate), mime_type="audio/wav"
                ),
            ],
        )
        return ASRResult(text=(response.text or "").strip())
