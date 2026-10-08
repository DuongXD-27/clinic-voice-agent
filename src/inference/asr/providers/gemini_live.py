"""Gemini dedicated live STT over the documented BidiGenerateContent WebSocket.

Manual activity boundaries use the same local classifier/endpoint as ZipFormer.
Each segment has an isolated socket, so a discarded or duplicate remote response
cannot become the next caller's transcript. Audio is streamed while speaking;
only the last small chunk is buffered. No SDK schema conversion. The next segment's
socket is opened and set up in the background, so the handshake is off the speech path.

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
from websockets.protocol import State

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
# Socket setup xong rồi để rảnh: 30 s vẫn dùng được, 60 s vẫn báo OPEN nhưng audio gửi vào bị
# server cắt 1008 (đo 07/10). Quá tuổi này thì mở socket khác.
_SPARE_MAX_AGE_S = 25.0


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


class _Session:
    """Socket Live đã setup xong nhưng chưa có activity nào. Mở trước được để handshake
    (0,65–4 s mỗi lần, đo 07/10) không nằm trên đường nói; chưa nhận audio nên vẫn giữ nguyên
    nguyên tắc mỗi đoạn một socket."""

    def __init__(self, config: GeminiLiveASRConfig, connect: Callable[..., Any]) -> None:
        self._config = config
        self.context = connect(
            LIVE_WS_URL,
            additional_headers={"x-goog-api-key": config.api_key.get_secret_value()},
            open_timeout=config.connect_timeout_s,
            close_timeout=1,
            max_queue=16,
        )
        self.socket = None

    async def open(self) -> "_Session":
        timeout = self._config.connect_timeout_s
        try:
            self.socket = await self.context.__aenter__()
            setup = {
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
            await asyncio.wait_for(self.socket.send(json.dumps(setup)), timeout=timeout)
            reply = json.loads(await asyncio.wait_for(self.socket.recv(), timeout=timeout))
            if "error" in reply:
                raise _remote_error(reply)
            if "setupComplete" not in reply:
                raise RuntimeError("Gemini Live STT did not acknowledge session setup")
        except BaseException:
            await self.close()
            raise
        return self

    @property
    def usable(self) -> bool:
        """Server có thể đã đóng socket chờ quá lâu."""
        state = getattr(self.socket, "state", State.OPEN)
        return self.socket is not None and state is State.OPEN

    async def close(self) -> None:
        if self.socket is not None:
            self.socket = None
            await self.context.__aexit__(None, None, None)


async def _open_session(config: GeminiLiveASRConfig, connect: Callable[..., Any]) -> _Session:
    return await _Session(config, connect).open()


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
        self._last_text = ""
        # Câu dài bị tách ở `max_turn_speech_ms` thành nhiều phần cùng segment_id: chữ các phần
        # trước (`prefix`) đi kèm mọi event của phần này, và final của phần chưa phải phần cuối
        # (`more_follows`) phát thành partial — TurnController giữ một đoạn, final mới ghi đè.
        self.prefix = ""
        self.more_follows = False
        # Đoạn đã có kết quả (final của Gemini hoặc fallback) — chỉ một lần.
        self.result_text: Optional[str] = None
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

    async def open(self, session: Optional[_Session] = None) -> None:
        """`session`: socket đã setup sẵn (`_open_session`), None = mở mới."""
        if session is None:
            session = await _open_session(self._config, self._connect)
        self._socket_context, self._socket = session.context, session.socket
        self._reader = asyncio.create_task(self._receive())
        await self._send({"realtimeInput": {"activityStart": {}}})

    async def _emit(self, text: str, *, final: bool, confidence: Optional[float] = None) -> None:
        text = " ".join(part for part in (self.prefix, text.strip()) if part)
        if final:
            self.result_text = text
        await self._events.put(
            TranscriptEvent(
                text=text,
                is_final=final and not self.more_follows,
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
                    self._last_text = text
                    authoritative = self.end_sent and final.get("finished") is not False
                    await self._emit(text, final=authoritative)
                    if authoritative:
                        self.finished.set()
                elif content.get("turnComplete") and self.end_sent:
                    # A valid empty turn must settle instead of waiting indefinitely.
                    await self._emit("", final=True)
                    self.finished.set()
                activity = message.get("voiceActivity") or {}
                if (
                    activity.get("type") == "ACTIVITY_END"
                    and self.end_sent
                    and not self.finished.is_set()
                ):
                    # transcribe-live không gửi turnComplete. Đoạn không có lời (tiếng ồn,
                    # tiếng vọng) chỉ nhận ACTIVITY_END; có lời thì final tới trước hoặc cùng
                    # message (đo 07/10: 43/43 đoạn). Không chốt ở đây thì đoạn rỗng nào cũng
                    # chờ hết final_timeout_s rồi rơi xuống fallback.
                    await self._emit(self._last_text, final=True)
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

    async def start(self, session: Optional[_Session] = None) -> None:
        """`open()` nhưng lỗi kết nối/setup được ghi vào đoạn thay vì ném ngay."""
        try:
            await self.open(session)
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

    async def stop_receiving(self) -> None:
        """Không phát thêm event nào từ Gemini cho đoạn này."""
        if self._reader is not None:
            self._reader.cancel()
            await asyncio.gather(self._reader, return_exceptions=True)

    async def close(self) -> None:
        self._context.pending.discard((self.generation, self.segment_id))
        await self.stop_receiving()
        if self._socket is not None:
            await self._socket_context.__aexit__(None, None, None)
            self._socket = None


class GeminiLiveASR:
    input_sample_rate = 16_000
    supports_stream_context = True
    supports_preroll_frames = True

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
        # Luồng nhận còn chạy thì final Gemini tới muộn (trong lúc fallback decode) vẫn được
        # phát rồi bị final fallback ghi đè: một đoạn ra hai final.
        await turn.stop_receiving()
        if turn.result_text is not None:
            return True  # final của Gemini đã tới ngay trước khi dừng nhận
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
        pre_speech_ms: int | None = None,
    ) -> AsyncIterator[TranscriptEvent]:
        """`pre_speech_ms`: audio giữ trước lúc nhận ra tiếng nói, None = config."""
        if audio_sample_rate not in (8_000, 16_000):
            raise ValueError("Gemini Live stream supports PCM16 mono at 8000 or 16000 Hz")
        if end_silence_ms <= 0:
            raise ValueError("end_silence_ms must be positive")
        if silence_classifier is None:
            from speech.asr.vad.energy import EnergyFrameClassifier

            silence_classifier = EnergyFrameClassifier()
        context = stream_context or ASRStreamContext()
        pre_roll_ms = self._config.pre_speech_ms if pre_speech_ms is None else pre_speech_ms
        events: asyncio.Queue = asyncio.Queue(maxsize=256)
        turn: _LiveTurn | None = None
        # Socket setup sẵn cho đoạn kế tiếp; lỗi thì đoạn đó tự mở socket mới.
        spare: asyncio.Task | None = None
        loop = asyncio.get_running_loop()
        spare_born = 0.0

        def prewarm() -> None:
            nonlocal spare, spare_born
            spare = asyncio.create_task(_open_session(self._config, self._connect))
            spare_born = loop.time()

        def spare_stale() -> bool:
            return loop.time() - spare_born > _SPARE_MAX_AGE_S

        async def take_spare() -> _Session | Exception | None:
            """Socket mở sẵn, hoặc lỗi lúc mở (đoạn đi thẳng xuống fallback, không mở lại để
            khỏi chờ handshake hai lần khi Gemini đang lỗi), None = tự mở mới."""
            nonlocal spare
            task, spare, stale = spare, None, spare_stale()
            prewarm()
            if task is None:
                return None
            try:
                session = await task
            except Exception as exc:
                return exc
            if session.usable and not stale:
                return session
            await session.close()
            return None

        async def drop_spare() -> None:
            nonlocal spare
            task, spare = spare, None
            if task is None:
                return
            task.cancel()
            (result,) = await asyncio.gather(task, return_exceptions=True)
            if isinstance(result, _Session):
                await result.close()

        async def open_turn(segment_id: int, *, prefix: str = "") -> _LiveTurn | None:
            """None nếu đoạn đã bị bỏ (DISCARD) trong lúc mở socket."""
            opened = _LiveTurn(
                self._config,
                self._connect,
                context,
                events,
                context.generation,
                segment_id,
                audio_sample_rate,
            )
            opened.prefix = prefix
            session = await take_spare()
            if isinstance(session, Exception):
                opened._fail(session)
            else:
                await opened.start(session)
            if opened.generation != context.generation:
                await opened.close()
                return None
            return opened

        async def pump() -> None:
            nonlocal turn
            prewarm()
            pre_speech = bytearray()
            pre_speech_max = audio_sample_rate * pre_roll_ms // 1000 * 2
            pre_speech_limit = pre_speech_max
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
                        pre_speech_limit = pre_speech_max
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
                    if turn is None and not voiced and spare_stale():
                        await drop_spare()
                        prewarm()
                    if turn is None and not voiced:
                        pre_speech.extend(pcm)
                        if isinstance(item, StreamingFrame) and item.is_preroll:
                            pre_speech_limit = max(
                                pre_speech_limit, len(pre_speech) + pre_speech_max
                            )
                        del pre_speech[: max(0, len(pre_speech) - pre_speech_limit)]
                        continue
                    if turn is None:
                        if stream_context is None:
                            context.start_utterance()
                        turn = await open_turn(
                            item.segment_id
                            if isinstance(item, StreamingFrame)
                            else context.segment_id
                        )
                        if turn is None:
                            pre_speech.clear()
                            pre_speech_limit = pre_speech_max
                            continue
                        await turn.audio(bytes(pre_speech))
                        pre_speech.clear()
                        pre_speech_limit = pre_speech_max
                    await turn.audio(pcm)
                    frame_ms = len(pcm) / 2 / audio_sample_rate * 1000
                    silent_ms = 0.0 if voiced else silent_ms + frame_ms
                    speech_ms += frame_ms if voiced else 0.0
                    too_long = speech_ms >= self._config.max_turn_speech_ms
                    if silent_ms >= end_silence_ms or too_long:
                        turn.more_follows = too_long and silent_ms < end_silence_ms
                        await self._finish(turn)
                        await turn.close()
                        done, turn = turn, None
                        silent_ms = speech_ms = 0.0
                        if done.more_follows:
                            # Câu chưa hết: mở ngay phần sau, kể cả khi người gọi ngừng đúng lúc
                            # tách — phần sau phát final của cả câu.
                            turn = await open_turn(done.segment_id, prefix=done.result_text or "")
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
                await drop_spare()
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
            await drop_spare()
