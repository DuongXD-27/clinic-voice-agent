"""Vbee Realtime API — `POST /v1/tts` mode=sync, audio trả về theo chunk (ADR-002 ứng viên 1).

    POST https://api.vbee.vn/v1/tts
    Authorization: Bearer <token> · App-Id: <app-id>
    {"text", "mode": "sync", "voiceCode", "outputFormat": "pcm", "sampleRate": 8000, "speed"}
    200: binary PCM 16-bit mono theo chunk · lỗi: JSON {"error": {"code", "message"}}

Giới hạn 300 ký tự/request: utterance dài hơn được cắt tại ranh giới câu/dấu phẩy, sinh tuần tự và
nối lại — không thêm/bớt/đổi chữ (§4.1.3). Không log text (ADR-002 tiêu chí 6).
"""

import logging
import re
import time
from collections.abc import Iterator
from typing import Any, Optional

import httpx

from callbot.speech.audio.codec import decode_wav
from callbot.speech.tts.base import TTSTiming
from callbot.speech.tts.errors import TTSError, TTSRejected, TTSUnavailable
from callbot.speech.types import AudioSegment

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.vbee.vn"
MAX_CHARS = 300
_REJECTED_STATUSES = frozenset({400, 401, 402, 403, 404, 422})
# Ưu tiên cắt sau dấu kết câu, rồi dấu phẩy/chấm phẩy, cuối cùng là khoảng trắng bất kỳ
_BREAKS = (re.compile(r"[.!?…]\s+"), re.compile(r"[,;:]\s+"), re.compile(r"\s+"))


def split_text(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """Cắt `text` thành các đoạn <= max_chars tại ranh giới tự nhiên; nối lại bằng khoảng trắng ra đủ từ gốc."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []
    pieces: list[str] = []
    rest = text
    while len(rest) > max_chars:
        cut = _best_break(rest, max_chars)
        pieces.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        pieces.append(rest)
    return pieces


def _best_break(text: str, max_chars: int) -> int:
    window = text[: max_chars + 1]
    for pattern in _BREAKS:
        ends = [m.end() for m in pattern.finditer(window) if 0 < m.end() <= max_chars]
        if ends:
            return ends[-1]
    return max_chars  # một "từ" dài hơn 300 ký tự — cắt cứng, không có cách nào khác


class VbeeTTS:
    name = "vbee"

    def __init__(
        self,
        access_token: str,
        app_id: str,
        voice_code: str,
        *,
        sample_rate: int = 8000,
        speed: float = 1.0,
        timeout_s: float = 4.0,
        base_url: str = DEFAULT_BASE_URL,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        if not access_token:
            raise ValueError("Vbee cần access_token")
        if not app_id:
            raise ValueError("Vbee cần app_id")
        if not voice_code:
            raise ValueError("Vbee cần voice_code")
        self._voice_code = voice_code
        self._sample_rate = sample_rate
        self._speed = speed
        self._timeout_s = timeout_s
        # Client dùng chung (keep-alive) — handler FastAPI chạy trong threadpool, httpx.Client thread-safe
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {access_token}",
                "App-Id": app_id,
                "Content-Type": "application/json",
            },
            timeout=timeout_s,
            transport=transport,
        )

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def close(self) -> None:
        self._client.close()

    # --- TTSProvider -----------------------------------------------------------------------

    def synthesize(self, text: str) -> AudioSegment:
        segment, timing = self.synthesize_timed(text)
        logger.info("tts %s: %s", self.name, timing.to_trace())
        return segment

    def synthesize_timed(self, text: str) -> tuple[AudioSegment, TTSTiming]:
        timing = TTSTiming()
        pcm = b"".join(self.stream(text, timing))
        return AudioSegment(pcm=pcm, sample_rate=self._sample_rate), timing

    # --- streaming -------------------------------------------------------------------------

    def stream(self, text: str, timing: Optional[TTSTiming] = None) -> Iterator[bytes]:
        """Yield chunk PCM khi nhận; utterance > 300 ký tự đi thành nhiều request nối tiếp."""
        pieces = split_text(text)
        if not pieces:
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
            for piece in pieces:
                for chunk in self._request(piece, remaining, timing, elapsed_ms):
                    yield chunk
        except TTSError:
            raise
        except httpx.TimeoutException as exc:
            raise TTSUnavailable(f"TTS quá {self._timeout_s:.1f}s", code="timeout") from exc
        except httpx.HTTPError as exc:
            raise TTSUnavailable(
                f"không nối được tới Vbee: {type(exc).__name__}", code="connection_failed"
            ) from exc
        finally:
            timing.total_ms = elapsed_ms()

        if timing.audio_bytes == 0:
            raise TTSUnavailable("provider không trả audio", code="no_audio")

    def _request(self, piece: str, remaining, timing: TTSTiming, elapsed_ms) -> Iterator[bytes]:
        body: dict[str, Any] = {
            "text": piece,
            "mode": "sync",
            "voiceCode": self._voice_code,
            "outputFormat": "pcm",
            "sampleRate": self._sample_rate,
            "speed": self._speed,
        }
        with self._client.stream("POST", "/v1/tts", json=body, timeout=remaining()) as response:
            if timing.connect_ms is None:
                timing.connect_ms = elapsed_ms()
            if response.status_code != 200:
                raise self._error_from(response)
            header = b""
            for chunk in response.iter_bytes():
                remaining()  # deadline tổng, kể cả khi từng chunk về đều đặn
                if not chunk:
                    continue
                # Một số server trả WAV dù xin pcm: bỏ header RIFF, giữ phần data
                if timing.audio_bytes == 0 and not header and chunk[:4] == b"RIFF":
                    header = chunk
                    continue
                if header:
                    header += chunk
                    continue
                self._count(chunk, timing, elapsed_ms)
                yield chunk
            if header:
                pcm = decode_wav(header, self._sample_rate).pcm
                if pcm:
                    self._count(pcm, timing, elapsed_ms)
                    yield pcm

    @staticmethod
    def _count(chunk: bytes, timing: TTSTiming, elapsed_ms) -> None:
        if timing.ttfa_ms is None:
            timing.ttfa_ms = elapsed_ms()
        timing.chunks += 1
        timing.audio_bytes += len(chunk)
        timing.last_chunk_ms = elapsed_ms()

    @staticmethod
    def _error_from(response: httpx.Response) -> TTSError:
        response.read()
        code, message = f"http_{response.status_code}", ""
        try:
            error = response.json().get("error") or {}
            code = str(error.get("code") or code)
            message = str(error.get("message") or "")
        except ValueError:
            pass
        detail = f"Vbee trả {response.status_code} {code}" + (f": {message}" if message else "")
        if response.status_code == 429 or response.status_code >= 500:
            return TTSUnavailable(detail, code=code)
        if response.status_code in _REJECTED_STATUSES:
            return TTSRejected(detail, code=code)
        return TTSUnavailable(detail, code=code)
