"""Vbee Realtime TTS qua HTTP: `POST /v1/tts`, `mode=sync` — provider chính, ElevenLabs dự phòng.

Vbee trả thẳng byte audio theo từng chunk (không phải JSON). Với `outputFormat=pcm` +
`sampleRate=8000` là PCM 16-bit LE mono 8 kHz không header — phát thẳng, không resample
(đã kiểm bằng benchmark Vbee vs ElevenLabs 23/9). Text Realtime tối đa 300 ký tự.
Không log text: utterance có thể chứa tên / ngày sinh bệnh nhân (ADR-002 tiêu chí 6).

`synthesize` (đường HTTP) gom cả câu; `synthesize_stream` + `cancel` (đường LiveKit) phát từng
chunk ngay khi về và đóng hẳn request khi khách nói chen.
"""

import asyncio
import time
from typing import Any, AsyncIterator, Awaitable, Callable, Optional, TypeVar

import httpx

from inference.common.transport import HttpClientFactory, build_http_timeout
from inference.tts.base import StreamHandle, TTSResult
from inference.tts.config import VbeeTTSConfig
from inference.tts.errors import TTSError, TTSRejected, TTSUnavailable
from inference.tts.static_identity import vbee_audio_identity

MAX_TEXT_CHARS = 300

AsyncHttpClientFactory = Callable[[], httpx.AsyncClient]

T = TypeVar("T")


class VbeeTTS:
    def __init__(
        self,
        config: VbeeTTSConfig,
        *,
        client_factory: Optional[HttpClientFactory] = None,
        async_client_factory: Optional[AsyncHttpClientFactory] = None,
    ) -> None:
        token = config.api_token.get_secret_value()
        if not token:
            raise ValueError("TTS_PROVIDER=vbee cần VBEE_API_TOKEN")
        if not config.app_id:
            raise ValueError("TTS_PROVIDER=vbee cần VBEE_APP_ID")
        self._config = config
        self._headers = {
            "Authorization": f"Bearer {token}",
            "App-id": config.app_id,
            "Accept": "audio/*, application/json",
        }
        self._timeout = build_http_timeout(config.timeout_s, config.connect_timeout_s)
        # Một client cho mọi câu: giữ kết nối TCP + TLS tới Vbee giữa các lượt thay vì bắt tay
        # lại mỗi câu. httpx.Client an toàn khi nhiều thread cùng gọi (HTTP chạy synthesize
        # trong asyncio.to_thread). Điểm thay thế trong unit test: client_factory trả
        # httpx.Client(transport=httpx.MockTransport(...)).
        self._client = (client_factory or self._default_client)()
        # Client async cho stream: tạo ở lần stream đầu tiên, nên đường HTTP (chỉ gọi
        # synthesize) không mở thêm gì. Cùng keepalive với client sync.
        self._async_client_factory = async_client_factory or self._default_async_client
        self._async_client: Optional[httpx.AsyncClient] = None
        # Câu đang stream; state từng câu nằm trên handle (xem StreamHandle)
        self._stream: Optional[StreamHandle] = None

    def _limits(self) -> httpx.Limits:
        # keepalive_expiry mặc định của httpx là 5 s — ngắn hơn khoảng cách giữa hai lượt
        # nói, gần như lượt nào cũng phải bắt tay lại.
        return httpx.Limits(keepalive_expiry=self._config.keepalive_s)

    def _default_client(self) -> httpx.Client:
        return httpx.Client(timeout=self._timeout, limits=self._limits())

    def _default_async_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout, limits=self._limits())

    def close(self) -> None:
        """Đóng kết nối sync giữ sẵn tới Vbee; gọi khi app tắt. Client stream đóng bằng `aclose`."""
        self._client.close()

    async def aclose(self) -> None:
        """Đóng cả client stream lẫn client sync; gọi khi job LiveKit kết thúc."""
        try:
            if self._async_client is not None:
                await self._async_client.aclose()
                self._async_client = None
        finally:
            self._client.close()

    @property
    def model(self) -> str:
        # Vbee không có model id riêng; mã giọng là thứ quyết định audio
        return self._config.voice_code

    @property
    def voice(self) -> str:
        return self._config.voice_code

    @property
    def audio_identity(self) -> dict:
        """Settings affecting audio only; never exposes API credentials."""
        return vbee_audio_identity(self._config)

    @property
    def stream_sample_rate(self) -> int:
        return self._config.sample_rate

    def _payload(self, text: str) -> dict[str, Any]:
        return {
            "text": text,
            "mode": "sync",
            "voiceCode": self._config.voice_code,
            "outputFormat": "pcm",
            "sampleRate": self._config.sample_rate,
            "bitrate": self._config.bitrate,
            "speed": self._config.speed,
        }

    def synthesize(self, text: str) -> TTSResult:
        _check_length(text)
        # httpx chỉ có timeout theo pha; tự giữ trần tổng như adapter ElevenLabs
        deadline = time.perf_counter() + self._config.timeout_s
        started = time.perf_counter()
        ttfa_ms = None
        audio = bytearray()
        try:
            with self._client.stream(
                "POST",
                self._config.endpoint,
                headers=self._headers,
                json=self._payload(text),
                timeout=self._timeout,
            ) as response:
                _check_response(response)
                for chunk in response.iter_bytes():
                    if chunk and ttfa_ms is None:
                        ttfa_ms = (time.perf_counter() - started) * 1000
                    audio.extend(chunk)
                    if time.perf_counter() > deadline:
                        raise _timeout(self._config.timeout_s)
        except httpx.TimeoutException as exc:
            raise _timeout(self._config.timeout_s) from exc
        except httpx.HTTPError as exc:
            raise _connection_failed(exc) from exc

        # PCM 16-bit: bỏ byte lẻ cuối nếu luồng bị cắt giữa một mẫu
        pcm = bytes(audio[: len(audio) - len(audio) % 2])
        if not pcm:
            raise _no_audio()
        return TTSResult(
            pcm=pcm,
            sample_rate=self._config.sample_rate,
            voice=self._config.voice_code,
            ttfa_ms=ttfa_ms,
        )

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """Yield PCM16 từng chunk ngay khi Vbee trả về; `cancel()` thì dừng êm, không ném lỗi."""
        text = text.strip()
        if not text:
            raise TTSRejected("text rỗng", code="empty_text")
        _check_length(text)
        stream = StreamHandle()
        self._stream = stream
        if self._async_client is None:
            self._async_client = self._async_client_factory()
        # Trần tổng chỉ tính thời gian chờ Vbee (kết nối, header, byte đầu, các chunk sau), không
        # tính lúc bên phát giữ generator: CallBridge kéo chunk theo nhịp phát audio thật, đo
        # đồng hồ treo tường thì câu nào dài hơn timeout_s giây audio cũng bị cắt giữa chừng.
        # Mỗi lần chờ bị chặn bởi phần trần còn lại, nên chưa có byte đầu thì cũng không chờ
        # quá timeout_s (timeout từng pha của httpx cộng lại dài hơn).
        waited = 0.0

        async def wait(step: Awaitable[T]) -> T:
            nonlocal waited
            mark = time.perf_counter()
            try:
                # Hết trần (<= 0) thì hủy ngay ở lần chờ đầu tiên của bước này
                async with asyncio.timeout(self._config.timeout_s - waited):
                    return await step
            except TimeoutError as exc:
                raise _timeout(self._config.timeout_s) from exc
            finally:
                waited += time.perf_counter() - mark

        carry = b""
        sent = 0
        response: Optional[httpx.Response] = None
        try:
            request = self._async_client.build_request(
                "POST",
                self._config.endpoint,
                headers=self._headers,
                json=self._payload(text),
                timeout=self._timeout,
            )
            response = await wait(self._async_client.send(request, stream=True))
            stream.close = response.aclose
            _check_response(response)
            chunks = response.aiter_bytes()
            while not stream.cancelled:
                try:
                    chunk = await wait(anext(chunks))
                except StopAsyncIteration:
                    break
                if stream.cancelled:
                    break
                # Chunk HTTP cắt tuỳ ý (vd. 4090 B rồi 6 B): giữ byte lẻ ghép vào chunk sau
                data = carry + chunk
                even = len(data) - len(data) % 2
                carry = data[even:]
                if even:
                    sent += even
                    yield data[:even]
        except TTSError:
            raise
        except (httpx.HTTPError, httpx.StreamError) as exc:
            # cancel() đóng response khi task khác đang đọc: lỗi đọc đó là dừng chủ động
            if stream.cancelled:
                return
            if isinstance(exc, httpx.TimeoutException):
                raise _timeout(self._config.timeout_s) from exc
            raise _connection_failed(exc) from exc
        finally:
            stream.close = None
            if response is not None:
                await response.aclose()
        if not sent and not stream.cancelled:
            raise _no_audio()

    async def cancel(self) -> None:
        """Dừng stream đang chạy và đóng hẳn request tới Vbee (khách nói chen)."""
        if self._stream is not None:
            await self._stream.cancel()


def _check_length(text: str) -> None:
    if len(text) > MAX_TEXT_CHARS:
        raise TTSRejected(
            f"text dài {len(text)} ký tự, Vbee tối đa {MAX_TEXT_CHARS}", "text_too_long"
        )


def _check_response(response: httpx.Response) -> None:
    if response.status_code != 200:
        raise _from_status(response.status_code)
    content_type = response.headers.get("content-type", "")
    if content_type.startswith(("application/json", "text/")):
        # Lỗi bọc trong 200: không đọc body vào message để tránh lộ dữ liệu
        raise TTSUnavailable("Vbee trả JSON thay vì audio", code="bad_response")


def _timeout(timeout_s: float) -> TTSUnavailable:
    return TTSUnavailable(f"TTS quá {timeout_s:.1f}s", code="timeout")


def _connection_failed(exc: Exception) -> TTSUnavailable:
    return TTSUnavailable(
        f"không nối được tới Vbee: {type(exc).__name__}", code="connection_failed"
    )


def _no_audio() -> TTSUnavailable:
    return TTSUnavailable("Vbee không trả audio", code="no_audio")


def _from_status(status_code: int) -> TTSUnavailable | TTSRejected:
    if status_code == 429 or status_code >= 500:
        return TTSUnavailable(f"Vbee trả {status_code}", code=f"http_{status_code}")
    return TTSRejected(f"Vbee trả {status_code}", code=f"http_{status_code}")
