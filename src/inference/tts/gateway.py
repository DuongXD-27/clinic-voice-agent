"""Single entry point for configured TTS calls; no retries, optional one-step failover.

Cả hai đường đều đi qua đây: `synthesize` (HTTP, gom cả câu) và `synthesize_stream` (LiveKit,
phát từng chunk). Dự phòng chỉ đọc lại **đúng câu đó** và chỉ khi chưa phát gì: đã phát một
phần mà lỗi thì dừng, vì đọc lại từ đầu sẽ lặp câu, audio khác `utterance` (§4.1.3).
"""

import asyncio
import logging
import time
from contextlib import aclosing
from dataclasses import dataclass, replace
from typing import AsyncIterator, Optional

from inference.common.errors import UnsupportedProviderError
from inference.tts.base import (
    ProviderName,
    StreamHandle,
    TTSProvider,
    TTSResult,
    TTSStreamInfo,
)
from inference.tts.config import ElevenLabsTTSConfig, OpenAITTSConfig, TTSConfig, VbeeTTSConfig

logger = logging.getLogger(__name__)


@dataclass
class _GatewayStream(StreamHandle):
    """Một câu đang/vừa stream: `close` trỏ tới `cancel` của provider đang phát (chính hoặc dự
    phòng), `info` là thứ `last_stream` trả về."""

    info: Optional[TTSStreamInfo] = None


class TTSGateway:
    def __init__(
        self,
        provider: TTSProvider,
        *,
        provider_name: ProviderName,
        fallback: Optional["TTSGateway"] = None,
    ) -> None:
        self._provider = provider
        self.provider_name = provider_name
        self.fallback = fallback
        # Câu stream gần nhất. Một gateway stream chỉ thuộc một cuộc gọi (worker LiveKit dựng
        # bundle riêng mỗi job); state từng câu nằm trên handle, không trên gateway.
        self._stream: Optional[_GatewayStream] = None

    @property
    def model(self) -> str:
        return self._provider.model

    @property
    def last_stream(self) -> Optional[TTSStreamInfo]:
        """Câu stream gần nhất; None nếu chưa phát được chunk nào."""
        return self._stream.info if self._stream is not None else None

    @property
    def provider(self) -> TTSProvider:
        """Instance provider chính đã tạo (vd. để đọc `stream_sample_rate`). Stream và hủy
        đi qua `synthesize_stream()` / `cancel()` của gateway để có dự phòng, không gọi
        thẳng provider."""
        return self._provider

    def synthesize(self, text: str) -> Optional[TTSResult]:
        text = text.strip()
        if not text:
            return None
        if self.fallback is None:
            result = self._provider.synthesize(text)
            return replace(result, provider_actual=self.provider_name)
        try:
            result = self._provider.synthesize(text)
            return replace(result, provider_actual=self.provider_name)
        except Exception as exc:
            # Mọi lỗi của provider chính đều chuyển sang dự phòng; chỉ log loại lỗi/mã, không log text
            logger.warning(
                "TTS %s lỗi [%s %s], chuyển sang %s",
                self.provider_name,
                type(exc).__name__,
                getattr(exc, "code", "-"),
                self.fallback.provider_name,
            )
            result = self.fallback.synthesize(text)
            return replace(result, fallback_used=True) if result is not None else None

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """Phát một câu theo chunk. Provider chính lỗi trước chunk đầu → dự phòng đọc đúng
        câu đó; lỗi khi đã phát → dừng, không đọc lại; cả hai lỗi trước chunk đầu → ném lỗi.
        Sau `cancel()` thì dừng êm, không chuyển dự phòng."""
        stream = _GatewayStream()
        self._stream = stream
        text = text.strip()
        if not text:
            return
        started = time.perf_counter()
        info = TTSStreamInfo(
            provider_actual=self.provider_name,
            voice=getattr(self._provider, "voice", None),
            sample_rate=getattr(self._provider, "stream_sample_rate", 0),
        )
        sent = False
        stream.close = getattr(self._provider, "cancel", None)
        try:
            async with aclosing(self._provider_stream(text, info)) as chunks:
                async for chunk in chunks:
                    if stream.cancelled:
                        return
                    if not sent:
                        sent = True
                        info.ttfa_ms = (time.perf_counter() - started) * 1000
                        stream.info = info
                    yield chunk
            return
        except Exception as exc:
            if stream.cancelled:
                return
            code = getattr(exc, "code", None) or type(exc).__name__
            if sent:
                info.error_code = code
                logger.warning(
                    "TTS %s lỗi giữa câu [%s %s], dừng, không đọc lại",
                    self.provider_name,
                    type(exc).__name__,
                    code,
                )
                return
            if self.fallback is None:
                raise
            # Cùng mẫu log với synthesize(): đếm tỉ lệ fallback bằng "chuyển sang"
            logger.warning(
                "TTS %s lỗi [%s %s], chuyển sang %s",
                self.provider_name,
                type(exc).__name__,
                code,
                self.fallback.provider_name,
            )
        finally:
            stream.close = None

        stream.close = self.fallback.cancel
        try:
            async with aclosing(self.fallback.synthesize_stream(text)) as chunks:
                async for chunk in chunks:
                    if stream.cancelled:
                        return
                    backup = self.fallback.last_stream
                    if stream.info is None and backup is not None:
                        stream.info = replace(
                            backup,
                            fallback_used=True,
                            ttfa_ms=(time.perf_counter() - started) * 1000,
                        )
                    yield chunk
        finally:
            stream.close = None
            backup = self.fallback.last_stream
            if stream.info is not None and backup is not None:
                stream.info.error_code = backup.error_code

    async def _provider_stream(self, text: str, info: TTSStreamInfo) -> AsyncIterator[bytes]:
        stream = getattr(self._provider, "synthesize_stream", None)
        if stream is not None:
            async with aclosing(stream(text)) as chunks:
                async for chunk in chunks:
                    if chunk:
                        yield chunk
            return
        # Provider chỉ có synthesize: gom cả câu trong thread rồi phát một khối
        result = await asyncio.to_thread(self._provider.synthesize, text)
        info.sample_rate = result.sample_rate
        info.voice = info.voice or result.voice
        if result.pcm:
            yield result.pcm

    async def cancel(self) -> None:
        """Khách nói chen: dừng stream đang chạy (provider chính hoặc dự phòng) và đóng request."""
        if self._stream is not None:
            await self._stream.cancel()

    def close(self) -> None:
        """Đóng kết nối giữ sẵn của provider chính và dự phòng (gọi khi app/worker tắt)."""
        try:
            close = getattr(self._provider, "close", None)
            if close is not None:
                close()
        finally:
            if self.fallback is not None:
                self.fallback.close()

    async def aclose(self) -> None:
        """Như `close()`, nhưng đóng được cả client stream (async) của provider; dùng ở LiveKit."""
        try:
            aclose = getattr(self._provider, "aclose", None)
            if aclose is not None:
                await aclose()
            else:
                close = getattr(self._provider, "close", None)
                if close is not None:
                    close()
        finally:
            if self.fallback is not None:
                await self.fallback.aclose()


def _provider_types() -> dict[str, tuple[type[TTSConfig], type]]:
    from inference.tts.providers.elevenlabs import ElevenLabsTTS
    from inference.tts.providers.openai import OpenAITTS
    from inference.tts.providers.vbee import VbeeTTS

    return {
        "openai": (OpenAITTSConfig, OpenAITTS),
        "elevenlabs": (ElevenLabsTTSConfig, ElevenLabsTTS),
        "vbee": (VbeeTTSConfig, VbeeTTS),
    }


def create_tts_gateway(
    provider_name: ProviderName,
    *,
    config: TTSConfig | None = None,
    fallback: Optional[ProviderName] = None,
) -> TTSGateway:
    """`fallback` dựng từ env như provider chính; trùng provider chính thì bỏ qua."""
    registry = _provider_types()
    if provider_name not in registry:
        raise UnsupportedProviderError("TTS", provider_name)
    config_type, provider_type = registry[provider_name]
    if config is not None and not isinstance(config, config_type):
        raise ValueError("Configuration does not match the selected provider")
    provider = provider_type(config if config is not None else config_type())
    backup = None
    if fallback is not None and fallback != provider_name:
        backup = create_tts_gateway(fallback)
    return TTSGateway(provider, provider_name=provider_name, fallback=backup)
