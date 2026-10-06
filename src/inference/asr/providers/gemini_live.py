"""Gemini dedicated live STT over the documented BidiGenerateContent WebSocket.

Manual activity boundaries use the same local classifier/endpoint as ZipFormer.
Each segment has an isolated socket, so a discarded or duplicate remote response
cannot become the next caller's transcript. Audio is streamed while speaking;
only the last small chunk is buffered. No SDK schema conversion.

Khi một đoạn lỗi (hết hạn chờ final, mất kết nối, server từ chối — kể cả hết credit) và có
`fallback` (cấu hình `fallback_provider`), PCM của chính đoạn đó được decode bằng model cục bộ
và phát final cho đúng đoạn; cuộc gọi tiếp tục với socket mới ở đoạn sau. Không có fallback thì
lỗi nổi lên như trước.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any, Optional, Protocol

from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed

from inference.asr.base import ASRResult
from inference.asr.config import GeminiLiveASRConfig
from speech.asr.stream_context import ASRStreamContext, StreamingFrame
from speech.asr.vad.base import FrameClassifier
from speech.types import AsrSegmentEnd, TranscriptEvent

logger = logging.getLogger(__name__)

LIVE_WS_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)
_DONE = object()


class _FallbackASR(Protocol):
    input_sample_rate: int

    def transcribe(self, pcm: bytes) -> ASRResult: ...


def _remote_error(message: dict) -> RuntimeError:
    # Never expose server payloads, caller text or authentication headers in logs.
    code = message.get("error", {}).get("code")
    label = str(code) if isinstance(code, int) else "unknown"
    return RuntimeError(f"Gemini Live STT rejected request (code={label})")


def _transport_error(exc: Exception) -> RuntimeError:
    if isinstance(exc, ConnectionClosed) and exc.rcvd is not None:
        code = exc.rcvd.code
        if "prepayment credits" in exc.rcvd.reason.casefold():
            return RuntimeError(
                f"Gemini Live STT unavailable: project prepayment credits are depleted (code={code})"
            )
        return RuntimeError(f"Gemini Live STT connection closed (code={code})")
    return RuntimeError(f"Gemini Live STT failed ({type(exc).__name__})")


class _PCMChunks:
    """Stateful 8k -> 16k resampling and fixed-size network chunks per segment."""

    def __init__(self, source_rate: int, chunk_ms: int) -> None:
        self._size = 16_000 * chunk_ms // 1000 * 2
        self._buffer = bytearray()
        self._resampler = None
        if source_rate != 16_000:
            import soxr

            self._resampler = soxr.ResampleStream(source_rate, 16_000, 1, dtype="int16")

    def add(self, pcm: bytes, *, last: bool = False) -> list[bytes]:
        if len(pcm) % 2:
            raise ValueError("Gemini Live STT expects PCM16 mono frames")
        if self._resampler is not None:
            import numpy as np

            samples = np.frombuffer(pcm, dtype="<i2")
            pcm = self._resampler.resample_chunk(samples, last=last).astype("<i2").tobytes()
        self._buffer.extend(pcm)
        chunks = []
        while len(self._buffer) >= self._size:
            chunks.append(bytes(self._buffer[: self._size]))
            del self._buffer[: self._size]
        if last and self._buffer:
            chunks.append(bytes(self._buffer))
            self._buffer.clear()
        return chunks


class _LiveTurn:
    def __init__(
        self,
        config: GeminiLiveASRConfig,
        connect: Callable[..., Any],
        context: ASRStreamContext,
        events: asyncio.Queue,
        generation: int,
        segment_id: int,
        source_rate: int,
    ) -> None:
        self._config = config
        self._connect = connect
        self._context = context
        self._events = events
        self.generation = generation
        self.segment_id = segment_id
        self.invalidated = context.invalidated
        self.finished = asyncio.Event()
        self.end_sent = False
        # Lỗi phát hiện ở luồng nhận; finalize() ném ra để pump xử lý theo đoạn.
        self.error: Optional[Exception] = None
        # PCM của đoạn ở tần số nguồn — decode lại bằng fallback nếu đoạn lỗi.
        self.pcm = bytearray()
        self._socket_context = None
        self._socket = None
        self._reader = None
        self.source_rate = source_rate
        self._chunks = _PCMChunks(source_rate, config.chunk_ms)
        self._context.pending.add((generation, segment_id))

    async def _send(self, message: dict) -> None:
        await asyncio.wait_for(
            self._socket.send(json.dumps(message)), timeout=self._config.connect_timeout_s
        )

    async def open(self) -> None:
        self._socket_context = self._connect(
            LIVE_WS_URL,
            additional_headers={"x-goog-api-key": self._config.api_key.get_secret_value()},
            open_timeout=self._config.connect_timeout_s,
            close_timeout=1,
            max_queue=16,
        )
        self._socket = await self._socket_context.__aenter__()
        await self._send(
            {
                "setup": {
                    "model": f"models/{self._config.model.removeprefix('models/')}",
                    "generationConfig": {"responseModalities": ["TEXT"]},
                    "inputAudioTranscription": {
                        "languageCodes": [self._config.language_code],
                        "mode": "VERBATIM",
                    },
                    "realtimeInputConfig": {"automaticActivityDetection": {"disabled": True}},
                }
            }
        )
        reply = json.loads(
            await asyncio.wait_for(self._socket.recv(), timeout=self._config.connect_timeout_s)
        )
        if "error" in reply:
            raise _remote_error(reply)
        if "setupComplete" not in reply:
            raise RuntimeError("Gemini Live STT did not acknowledge session setup")
        self._reader = asyncio.create_task(self._receive())
        await self._send({"realtimeInput": {"activityStart": {}}})

    async def _emit(self, text: str, *, final: bool, confidence: Optional[float] = None) -> None:
        await self._events.put(
            TranscriptEvent(
                text=text.strip(),
                is_final=final,
                confidence=confidence,
                generation=self.generation,
                segment_id=self.segment_id,
            )
        )

    async def _receive(self) -> None:
        try:
            while not self.finished.is_set():
                message = json.loads(await self._socket.recv())
                if "error" in message:
                    raise _remote_error(message)
                content = message.get("serverContent") or {}
                partial = content.get("interimInputTranscription")
                if partial is not None and partial.get("text"):
                    await self._emit(partial["text"], final=False)
                final = content.get("inputTranscription")
                if final is not None:
                    text = final.get("text") or ""
                    authoritative = self.end_sent and final.get("finished") is not False
                    await self._emit(text, final=authoritative)
                    if authoritative:
                        self.finished.set()
                elif content.get("turnComplete") and self.end_sent:
                    # A valid empty turn must settle instead of waiting indefinitely.
                    await self._emit("", final=True)
                    self.finished.set()
        except asyncio.CancelledError:
            raise
        except RuntimeError as exc:
            self._fail(exc)
        except Exception as exc:
            self._fail(_transport_error(exc))

    def _fail(self, exc: Exception) -> None:
        """Ghi lỗi của đoạn; pump xử lý ở `finalize()`. Không gửi tiếp nhưng vẫn giữ PCM tới
        hết đoạn để fallback decode trọn đoạn, không phát hai final cho cùng một đoạn."""
        if self.error is None:
            self.error = exc if isinstance(exc, RuntimeError) else _transport_error(exc)
        self.finished.set()

    async def start(self) -> None:
        """`open()` nhưng lỗi kết nối/setup được ghi vào đoạn thay vì ném ngay."""
        try:
            await self.open()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail(exc)

    async def audio(self, pcm: bytes, *, last: bool = False) -> None:
        self.pcm.extend(pcm)
        if self.error is not None:
            return
        try:
            await self._send_audio(pcm, last=last)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail(exc)

    async def _send_audio(self, pcm: bytes, *, last: bool) -> None:
        for chunk in self._chunks.add(pcm, last=last):
            await self._send(
                {
                    "realtimeInput": {
                        "audio": {
                            "data": base64.b64encode(chunk).decode("ascii"),
                            "mimeType": "audio/pcm;rate=16000",
                        }
                    }
                }
            )

    async def finalize(self) -> None:
        await self.audio(b"", last=True)
        if self.error is not None:
            raise self.error
        self.end_sent = True
        try:
            await self._send({"realtimeInput": {"activityEnd": {}}})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail(exc)
            raise self.error from None
        finished = asyncio.create_task(self.finished.wait())
        discarded = asyncio.create_task(self.invalidated.wait())
        try:
            done, _ = await asyncio.wait(
                {finished, discarded},
                timeout=self._config.final_timeout_s,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                raise RuntimeError("Gemini Live STT timed out waiting for final transcript")
            if self.error is not None:
                raise self.error
        finally:
            finished.cancel()
            discarded.cancel()
            await asyncio.gather(finished, discarded, return_exceptions=True)

    async def close(self) -> None:
        self._context.pending.discard((self.generation, self.segment_id))
        if self._reader is not None:
            self._reader.cancel()
            await asyncio.gather(self._reader, return_exceptions=True)
        if self._socket is not None:
            await self._socket_context.__aexit__(None, None, None)
            self._socket = None


class GeminiLiveASR:
    input_sample_rate = 16_000
    supports_stream_context = True

    def __init__(
        self,
        config: GeminiLiveASRConfig,
        *,
        connect: Callable[..., Any] | None = None,
        fallback: Optional[_FallbackASR] = None,
    ) -> None:
        """`fallback`: ASR cục bộ decode lại đoạn lỗi; mặc định dựng theo
        `config.fallback_provider` (None = không fallback)."""
        if not config.api_key.get_secret_value():
            raise ValueError("ASR_PROVIDER=gemini_live cần GEMINI_API_KEY")
        self._config = config
        self._connect = connect or ws_connect
        if fallback is None and config.fallback_provider == "zipformer":
            from inference.asr.config import ZipFormerConfig
            from inference.asr.providers.zipformer import ZipFormerASR

            fallback = ZipFormerASR(ZipFormerConfig())
        self._fallback = fallback

    def warm_up(self) -> None:
        """Nạp sẵn model fallback (lần decode đầu của ZipFormer mất ~1,8 s) trước khi nhận
        cuộc gọi, để đoạn lỗi đầu tiên không phải chờ thêm."""
        if self._fallback is not None:
            rate = self._fallback.input_sample_rate
            self._fallback.transcribe(b"\x00\x00" * (rate // 10))

    async def _recover(self, turn: "_LiveTurn", error: Exception) -> bool:
        """Đoạn `turn` lỗi: decode lại bằng fallback và phát final cho đúng đoạn. False nếu
        không có fallback hoặc đoạn đã bị bỏ (DISCARD/bot nói) — khi đó lỗi nổi lên như cũ."""
        if self._fallback is None or turn.invalidated.is_set():
            return False
        logger.warning(
            "gemini_live: segment %d lỗi (%s), decode lại bằng fallback cục bộ",
            turn.segment_id,
            error,
        )
        pcm = bytes(turn.pcm)
        if pcm and turn.source_rate != self._fallback.input_sample_rate:
            from speech.audio.codec import resample

            pcm = resample(pcm, turn.source_rate, self._fallback.input_sample_rate)
        result = await asyncio.to_thread(self._fallback.transcribe, pcm) if pcm else None
        await turn._emit(
            result.text if result else "",
            final=True,
            confidence=result.confidence if result else None,
        )
        return True

    async def _finish(self, turn: "_LiveTurn") -> None:
        try:
            await turn.finalize()
        except RuntimeError as exc:
            if not await self._recover(turn, exc):
                raise

    @property
    def model(self) -> str:
        return self._config.model

    def transcribe(self, pcm: bytes) -> Any:
        raise NotImplementedError(
            "Gemini Live chỉ hỗ trợ stream(); dùng LIVEKIT_ASR_PROVIDER=gemini_live "
            "và giữ ASR_PROVIDER cho HTTP/batch."
        )

    async def check_connection(self) -> None:
        """Validate model access/setup without uploading audio or caller data."""
        turn = _LiveTurn(
            self._config, self._connect, ASRStreamContext(), asyncio.Queue(), 0, 0, 16_000
        )
        try:
            await turn.open()
        except RuntimeError:
            raise
        except Exception as exc:
            raise _transport_error(exc) from None
        finally:
            await turn.close()

    async def stream(
        self,
        frames: AsyncIterator[bytes | StreamingFrame | AsrSegmentEnd],
        *,
        audio_sample_rate: int = 16_000,
        silence_classifier: FrameClassifier | None = None,
        end_silence_ms: int = 600,
        stream_context: ASRStreamContext | None = None,
    ) -> AsyncIterator[TranscriptEvent]:
        if audio_sample_rate not in (8_000, 16_000):
            raise ValueError("Gemini Live stream supports PCM16 mono at 8000 or 16000 Hz")
        if end_silence_ms <= 0:
            raise ValueError("end_silence_ms must be positive")
        if silence_classifier is None:
            from speech.asr.vad.energy import EnergyFrameClassifier

            silence_classifier = EnergyFrameClassifier()
        context = stream_context or ASRStreamContext()
        events: asyncio.Queue = asyncio.Queue(maxsize=256)
        turn: _LiveTurn | None = None

        async def pump() -> None:
            nonlocal turn
            pre_speech = bytearray()
            pre_speech_max = audio_sample_rate * self._config.pre_speech_ms // 1000 * 2
            silent_ms = speech_ms = 0.0
            try:
                async for item in frames:
                    if isinstance(item, AsrSegmentEnd):
                        if stream_context is None:
                            context.invalidate()
                        if turn is not None:
                            await turn.close()
                            turn = None
                        pre_speech.clear()
                        silent_ms = speech_ms = 0.0
                        continue
                    if isinstance(item, StreamingFrame):
                        if item.generation != context.generation:
                            continue
                        pcm = item.pcm
                    else:
                        pcm = item
                    if not pcm:
                        continue
                    if len(pcm) % 2:
                        raise ValueError("Gemini Live STT expects PCM16 mono frames")
                    voiced = silence_classifier.is_speech(pcm)
                    if turn is None and not voiced:
                        pre_speech.extend(pcm)
                        del pre_speech[: max(0, len(pre_speech) - pre_speech_max)]
                        continue
                    if turn is None:
                        if stream_context is None:
                            context.start_utterance()
                        turn = _LiveTurn(
                            self._config,
                            self._connect,
                            context,
                            events,
                            context.generation,
                            item.segment_id
                            if isinstance(item, StreamingFrame)
                            else context.segment_id,
                            audio_sample_rate,
                        )
                        await turn.start()
                        if turn.generation != context.generation:
                            await turn.close()
                            turn = None
                            pre_speech.clear()
                            continue
                        await turn.audio(bytes(pre_speech))
                        pre_speech.clear()
                    await turn.audio(pcm)
                    frame_ms = len(pcm) / 2 / audio_sample_rate * 1000
                    silent_ms = 0.0 if voiced else silent_ms + frame_ms
                    speech_ms += frame_ms if voiced else 0.0
                    if silent_ms >= end_silence_ms or speech_ms >= self._config.max_turn_speech_ms:
                        await self._finish(turn)
                        await turn.close()
                        turn = None
                        silent_ms = speech_ms = 0.0
                if turn is not None and turn.generation == context.generation:
                    await self._finish(turn)
            except asyncio.CancelledError:
                raise
            except (RuntimeError, ValueError) as exc:
                await events.put(exc)
            except Exception as exc:
                await events.put(_transport_error(exc))
            finally:
                if turn is not None:
                    await turn.close()
                if not asyncio.current_task().cancelling():
                    await events.put(_DONE)

        task = asyncio.create_task(pump())
        try:
            while True:
                item = await events.get()
                if item is _DONE:
                    return
                if isinstance(item, Exception):
                    raise item
                # Check again at delivery time: events may be queued before discard.
                if stream_context is None or context.accepts(item):
                    if item.generation == context.generation:
                        yield item
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            # Cancelling pump while it is closing a failed/timed-out socket can
            # interrupt that close. Complete cleanup from the consumer as well.
            if turn is not None:
                await turn.close()
