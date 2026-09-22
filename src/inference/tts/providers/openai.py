"""OpenAI TTS provider.

`synthesize_stream()`/`cancel()` phục vụ đường LiveKit streaming/barge-in
(transports/livekit/call_bridge.py) — nằm ngoài Protocol `TTSProvider` chung và được
gọi qua `TTSGateway.provider`.
"""

import asyncio
from typing import AsyncIterator

from inference.tts.base import TTSResult
from inference.tts.config import OpenAITTSConfig

_PCM_SAMPLE_RATE = 24_000  # khớp response_format="pcm" của OpenAI (PCM 16-bit, 24kHz, mono)


class OpenAITTS:
    stream_sample_rate = _PCM_SAMPLE_RATE

    def __init__(self, config: OpenAITTSConfig) -> None:
        self._config = config
        self._client = None
        self._async_client = None
        # 1 instance PHẢI thuộc về đúng 1 call (worker.py dựng 1 OpenAITTS/job, không
        # share qua factory singleton) — _cancelled là state per-call, không phải
        # per-request; nếu instance bị share giữa nhiều call, cancel() của call A sẽ
        # cắt luôn audio của call B.
        self._cancelled = asyncio.Event()

    @property
    def model(self) -> str:
        return self._config.model

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI  # pip install -e ".[speech-zipformer]"

            self._client = OpenAI(api_key=self._config.api_key.get_secret_value())
        return self._client

    def _get_async_client(self):
        if self._async_client is None:
            from openai import AsyncOpenAI

            self._async_client = AsyncOpenAI(api_key=self._config.api_key.get_secret_value())
        return self._async_client

    def synthesize(self, text: str) -> TTSResult:
        response = self._get_client().audio.speech.create(
            model=self._config.model,
            voice=self._config.voice,
            input=text,
            response_format="pcm",
        )
        return TTSResult(pcm=response.read(), sample_rate=_PCM_SAMPLE_RATE)

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        if not text.strip():
            return
        self._cancelled.clear()
        client = self._get_async_client()
        async with client.audio.speech.with_streaming_response.create(
            model=self._config.model,
            voice=self._config.voice,
            input=text,
            response_format="pcm",
        ) as response:
            async for chunk in response.iter_bytes():
                if self._cancelled.is_set():
                    return
                if chunk:
                    yield chunk

    async def cancel(self) -> None:
        """Đặt cờ hủy — vòng lặp `synthesize_stream` đang chạy sẽ dừng ở chunk kế tiếp.

        Không có API "abort request" thật ở tầng OpenAI SDK cho streaming response; đây
        chỉ dừng việc tiếp tục đọc/yield thêm chunk, không hủy request phía network. Caller
        (CallBridge) phải đồng thời dừng publish audio đã yield — dừng ở đây không tự xoá
        playback buffer phía LiveKit."""
        self._cancelled.set()
