"""ElevenLabs Flash v2.5 qua WebSocket `stream-input` (kế hoạch TTS 6 tuần §2.1, TTS-1.2).

Một kết nối cho mỗi utterance:
    -> BOS   {"text": " "}                       (key gửi qua header xi-api-key)
    -> text  {"text": "<utterance> ", "flush": true}
    -> EOS   {"text": ""}
    <- n lần {"audio": "<base64 PCM>", "isFinal": null}   -> yield chunk
    <- cuối  {"isFinal": true}

`synthesize()` (contract `TTSProvider`) gom toàn bộ chunk thành một `TTSResult`. `stream()` và
`synthesize_timed()` là API mở rộng — không thuộc `TTSProvider` — cho `scripts/tts_bench.py` /
`scripts/tts_say.py` cần streaming/latency thô. Không log text: utterance có thể chứa tên / ngày
sinh bệnh nhân (ADR-002 tiêu chí 6).
"""

import asyncio
import base64
import json
import logging
import time
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import asdict, dataclass
from typing import Any, Optional
from urllib.parse import urlencode

from websockets.asyncio.client import connect as async_ws_connect
from websockets.exceptions import (
    ConnectionClosed,
    ConnectionClosedOK,
    InvalidStatus,
    InvalidURI,
    WebSocketException,
)
from websockets.sync.client import connect as ws_connect

from inference.tts.base import TTSResult
from inference.tts.config import ElevenLabsTTSConfig
from inference.tts.errors import TTSError, TTSRejected, TTSUnavailable

logger = logging.getLogger(__name__)

DEFAULT_WS_URL = "wss://api.elevenlabs.io"

# Mã lỗi ElevenLabs gửi trong message JSON -> từ chối (thử lại cũng không đổi kết quả)
_REJECTED_CODES = frozenset(
    {
        "invalid_api_key",
        "missing_permissions",
        "unauthorized",
        "payment_required",
        "paid_plan_required",
        "quota_exceeded",
        "voice_not_found",
        "model_not_found",
        "invalid_uid",
        "text_too_long",
        "invalid_text",
        "voice_limit_reached",
        "free_users_not_allowed",
    }
)

Connect = Callable[..., Any]


@dataclass
class TTSTiming:
    """Số đo một lần sinh audio (kế hoạch TTS §2.5, TTS-1.6). Không chứa text để log không rò PII."""

    chars: int = 0
    connect_ms: Optional[int] = None  # mở kết nối tới provider
    ttfa_ms: Optional[int] = None  # time-to-first-audio: chunk PCM đầu tiên
    last_chunk_ms: Optional[int] = None  # chunk cuối / isFinal
    total_ms: Optional[int] = None
    audio_bytes: int = 0
    chunks: int = 0

    def to_trace(self) -> dict[str, Any]:
        return asdict(self)


def sample_rate_of(output_format: str) -> int:
    """`pcm_8000` -> 8000. Chỉ nhận PCM: μ-law cho điện thoại là việc tuần 5, decode ở Phone Adapter."""
    prefix, _, rate = output_format.partition("_")
    if prefix != "pcm" or not rate.isdigit():
        raise ValueError(f"output_format không phải PCM: {output_format!r}")
    return int(rate)


class ElevenLabsTTS:
    def __init__(
        self,
        config: ElevenLabsTTSConfig,
        *,
        ws_url: str = DEFAULT_WS_URL,
        connect: Optional[Connect] = None,
        async_connect: Optional[Connect] = None,
    ) -> None:
        api_key = config.api_key.get_secret_value()
        if not api_key:
            raise ValueError("TTS_PROVIDER=elevenlabs cần ELEVENLABS_API_KEY")
        if not config.voice_id:
            raise ValueError("TTS_PROVIDER=elevenlabs cần ELEVENLABS_VOICE_ID")
        self._api_key = api_key
        self._voice_id = config.voice_id
        self._model = config.model
        self._timeout_s = config.timeout_s
        self._ws_url = ws_url.rstrip("/")
        self._output_format = config.output_format
        self._sample_rate = sample_rate_of(config.output_format)
        self._language_code = config.language_code or None
        # Điểm thay thế trong unit test: cùng chữ ký `websockets.sync.client.connect`
        self._connect: Connect = connect or ws_connect
        self._async_connect: Connect = async_connect or async_ws_connect
        self._cancelled = asyncio.Event()
        self._active_ws: Any = None

    @property
    def model(self) -> str:
        return self._model

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def stream_sample_rate(self) -> int:
        return self._sample_rate

    def endpoint(self) -> str:
        params: dict[str, str] = {
            "model_id": self._model,
            "output_format": self._output_format,
            # auto_mode: không gom đệm theo chunk_length_schedule — mình gửi cả câu một lần
            "auto_mode": "true",
        }
        if self._language_code:
            params["language_code"] = self._language_code
        return f"{self._ws_url}/v1/text-to-speech/{self._voice_id}/stream-input?{urlencode(params)}"

    # --- TTSProvider (inference/tts/base.py) ------------------------------------------------

    def synthesize(self, text: str) -> TTSResult:
        segment, timing = self.synthesize_timed(text)
        logger.info("tts elevenlabs: %s", timing.to_trace())
        return segment

    # --- API mở rộng (scripts/tts_bench.py, scripts/tts_say.py) -------------------------------

    def synthesize_timed(self, text: str) -> tuple[TTSResult, TTSTiming]:
        timing = TTSTiming()
        pcm = b"".join(self.stream(text, timing))
        return TTSResult(pcm=pcm, sample_rate=self._sample_rate), timing

    def stream(self, text: str, timing: Optional[TTSTiming] = None) -> Iterator[bytes]:
        """Yield từng chunk PCM khi nhận được. `timing` (nếu truyền) được điền dần trong lúc chạy."""
        if not text or not text.strip():
            raise TTSRejected("text rỗng", code="empty_text")
        timing = timing if timing is not None else TTSTiming()
        timing.chars = len(text)
        started = time.perf_counter()
        deadline = started + self._timeout_s

        def elapsed_ms() -> int:
            return int((time.perf_counter() - started) * 1000)

        def remaining() -> float:
            left = deadline - time.perf_counter()
            if left <= 0:
                raise TTSUnavailable(f"TTS quá {self._timeout_s:.1f}s", code="timeout")
            return left

        try:
            with self._connect(
                self.endpoint(),
                additional_headers={"xi-api-key": self._api_key},
                open_timeout=remaining(),
                close_timeout=1,
            ) as ws:
                timing.connect_ms = elapsed_ms()
                ws.send(json.dumps({"text": " "}))
                ws.send(json.dumps({"text": text + " ", "flush": True}))
                ws.send(json.dumps({"text": ""}))

                while True:
                    try:
                        raw = ws.recv(timeout=remaining())
                    except ConnectionClosedOK:
                        # Server đóng sau khi phát hết mà không gửi isFinal
                        break
                    message = self._parse(raw)
                    self._raise_if_error(message)
                    audio = message.get("audio")
                    if audio:
                        chunk = base64.b64decode(audio)
                        if chunk:
                            if timing.ttfa_ms is None:
                                timing.ttfa_ms = elapsed_ms()
                            timing.chunks += 1
                            timing.audio_bytes += len(chunk)
                            timing.last_chunk_ms = elapsed_ms()
                            yield chunk
                    if message.get("isFinal"):
                        break
        except TTSError:
            raise
        except TimeoutError as exc:
            raise TTSUnavailable(f"TTS quá {self._timeout_s:.1f}s", code="timeout") from exc
        except InvalidStatus as exc:
            raise _from_handshake_status(exc.response.status_code) from exc
        except ConnectionClosed as exc:
            raise TTSUnavailable(
                f"kết nối TTS đóng bất thường (code={exc.rcvd.code if exc.rcvd else None})",
                code="connection_closed",
            ) from exc
        except (InvalidURI, WebSocketException, OSError) as exc:
            raise TTSUnavailable(
                f"không nối được tới TTS: {type(exc).__name__}", code="connection_failed"
            ) from exc
        finally:
            timing.total_ms = elapsed_ms()

        if timing.audio_bytes == 0:
            raise TTSUnavailable("provider không trả audio", code="no_audio")

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """Async WebSocket stream cho LiveKit; không chạy sync `stream()` trên event loop."""
        if not text or not text.strip():
            raise TTSRejected("text rỗng", code="empty_text")
        self._cancelled.clear()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout_s

        def remaining() -> float:
            left = deadline - loop.time()
            if left <= 0:
                raise TTSUnavailable(f"TTS quá {self._timeout_s:.1f}s", code="timeout")
            return left

        try:
            async with self._async_connect(
                self.endpoint(),
                additional_headers={"xi-api-key": self._api_key},
                open_timeout=remaining(),
                close_timeout=1,
            ) as ws:
                self._active_ws = ws
                await ws.send(json.dumps({"text": " "}))
                await ws.send(json.dumps({"text": text + " ", "flush": True}))
                await ws.send(json.dumps({"text": ""}))

                while not self._cancelled.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=remaining())
                    except ConnectionClosedOK:
                        break
                    message = self._parse(raw)
                    self._raise_if_error(message)
                    audio = message.get("audio")
                    if audio:
                        chunk = base64.b64decode(audio)
                        if chunk:
                            yield chunk
                    if message.get("isFinal"):
                        break
        except TTSError:
            raise
        except TimeoutError as exc:
            raise TTSUnavailable(f"TTS quá {self._timeout_s:.1f}s", code="timeout") from exc
        except InvalidStatus as exc:
            raise _from_handshake_status(exc.response.status_code) from exc
        except ConnectionClosedOK:
            return
        except ConnectionClosed as exc:
            if self._cancelled.is_set():
                return
            raise TTSUnavailable(
                f"kết nối TTS đóng bất thường (code={exc.rcvd.code if exc.rcvd else None})",
                code="connection_closed",
            ) from exc
        except (InvalidURI, WebSocketException, OSError) as exc:
            raise TTSUnavailable(
                f"không nối được tới TTS: {type(exc).__name__}", code="connection_failed"
            ) from exc
        finally:
            self._active_ws = None

    async def cancel(self) -> None:
        """Dừng nhận audio và đóng WebSocket đang sinh để barge-in có hiệu lực ngay."""
        self._cancelled.set()
        ws = self._active_ws
        if ws is not None:
            await ws.close()

    @staticmethod
    def _parse(raw: Any) -> dict[str, Any]:
        try:
            message = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise TTSUnavailable("message TTS không phải JSON", code="bad_message") from exc
        if not isinstance(message, dict):
            raise TTSUnavailable("message TTS không đúng dạng", code="bad_message")
        return message

    @staticmethod
    def _raise_if_error(message: dict[str, Any]) -> None:
        # ElevenLabs báo lỗi trong luồng dạng {"error": "<code>", "message": "...", "code": 1008}
        error = message.get("error")
        if not error:
            return
        code = str(error)
        detail = str(message.get("message") or code)
        if code in _REJECTED_CODES:
            raise TTSRejected(f"ElevenLabs từ chối: {detail}", code=code)
        raise TTSUnavailable(f"ElevenLabs lỗi: {detail}", code=code)


def _from_handshake_status(status_code: int) -> TTSError:
    if status_code == 429 or status_code >= 500:
        return TTSUnavailable(f"ElevenLabs trả {status_code}", code=f"http_{status_code}")
    return TTSRejected(f"ElevenLabs trả {status_code}", code=f"http_{status_code}")
