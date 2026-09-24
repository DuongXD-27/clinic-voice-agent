"""Vbee Realtime TTS qua HTTP: `POST /v1/tts`, `mode=sync` — provider chính, ElevenLabs dự phòng.

Vbee trả thẳng byte audio theo từng chunk (không phải JSON). Với `outputFormat=pcm` +
`sampleRate=8000` là PCM 16-bit LE mono 8 kHz không header — phát thẳng, không resample
(đã kiểm bằng benchmark Vbee vs ElevenLabs 23/9). Text Realtime tối đa 300 ký tự.
Không log text: utterance có thể chứa tên / ngày sinh bệnh nhân (ADR-002 tiêu chí 6).
"""

import time
from typing import Any, Optional

import httpx

from inference.common.transport import HttpClientFactory, build_http_timeout
from inference.tts.base import TTSResult
from inference.tts.config import VbeeTTSConfig
from inference.tts.errors import TTSRejected, TTSUnavailable

MAX_TEXT_CHARS = 300


class VbeeTTS:
    def __init__(
        self, config: VbeeTTSConfig, *, client_factory: Optional[HttpClientFactory] = None
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
        # Điểm thay thế trong unit test: httpx.Client(transport=httpx.MockTransport(...))
        self._client_factory = client_factory or httpx.Client

    @property
    def model(self) -> str:
        # Vbee không có model id riêng; mã giọng là thứ quyết định audio
        return self._config.voice_code

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
        if len(text) > MAX_TEXT_CHARS:
            raise TTSRejected(
                f"text dài {len(text)} ký tự, Vbee tối đa {MAX_TEXT_CHARS}", "text_too_long"
            )
        # httpx chỉ có timeout theo pha; tự giữ trần tổng như adapter ElevenLabs
        deadline = time.perf_counter() + self._config.timeout_s
        audio = bytearray()
        try:
            with self._client_factory() as client:
                with client.stream(
                    "POST",
                    self._config.endpoint,
                    headers=self._headers,
                    json=self._payload(text),
                    timeout=self._timeout,
                ) as response:
                    if response.status_code != 200:
                        raise _from_status(response.status_code)
                    content_type = response.headers.get("content-type", "")
                    if content_type.startswith(("application/json", "text/")):
                        # Lỗi bọc trong 200: không đọc body vào message để tránh lộ dữ liệu
                        raise TTSUnavailable("Vbee trả JSON thay vì audio", code="bad_response")
                    for chunk in response.iter_bytes():
                        audio.extend(chunk)
                        if time.perf_counter() > deadline:
                            raise _timeout(self._config.timeout_s)
        except httpx.TimeoutException as exc:
            raise _timeout(self._config.timeout_s) from exc
        except httpx.HTTPError as exc:
            raise TTSUnavailable(
                f"không nối được tới Vbee: {type(exc).__name__}", code="connection_failed"
            ) from exc

        # PCM 16-bit: bỏ byte lẻ cuối nếu luồng bị cắt giữa một mẫu
        pcm = bytes(audio[: len(audio) - len(audio) % 2])
        if not pcm:
            raise TTSUnavailable("Vbee không trả audio", code="no_audio")
        return TTSResult(pcm=pcm, sample_rate=self._config.sample_rate)


def _timeout(timeout_s: float) -> TTSUnavailable:
    return TTSUnavailable(f"TTS quá {timeout_s:.1f}s", code="timeout")


def _from_status(status_code: int) -> TTSUnavailable | TTSRejected:
    if status_code == 429 or status_code >= 500:
        return TTSUnavailable(f"Vbee trả {status_code}", code=f"http_{status_code}")
    return TTSRejected(f"Vbee trả {status_code}", code=f"http_{status_code}")
