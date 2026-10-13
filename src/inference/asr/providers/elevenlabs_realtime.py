"""ElevenLabs Scribe v2 Realtime qua WebSocket — streaming THẬT (không phải chunked-offline
như ZipFormer): server giữ state của chính nó giữa các audio chunk, trả partial_transcript
tăng dần trong lúc nói và committed_transcript khi chốt segment. Khác ZipFormer/gipformer1.5
(offline, decode lại toàn bộ buffer mỗi lần) — ở đây KHÔNG có buffer phía client, mỗi chunk
PCM chỉ gửi 1 lần, không giữ lại.

`input_sample_rate = 8000` là mặc định cho `transcribe()`/warm-up (khớp băng hẹp điện thoại,
`speech.types.NARROWBAND_RATE`), nhưng `stream()` tự nhận cả 8000 (điện thoại) và 16000
(LiveKit web/WebRTC, xem `callbot/transports/livekit/settings.py::input_sample_rate`) — SDK
ElevenLabs hỗ trợ thẳng cả `AudioFormat.PCM_8000` và `PCM_16000`, không cần resample về một
rate cố định như ZipFormer (vốn luôn cần 16kHz nội bộ).

Dùng `CommitStrategy.MANUAL` (không phải `VAD` của chính ElevenLabs): endpoint hoá turn đã
là trách nhiệm của `TurnController`/VAD ở tầng `speech.asr.pipeline` — để ElevenLabs tự VAD
song song sẽ tạo 2 nguồn quyết định "hết câu" độc lập, không đồng bộ với nhau. `stream()`
tự gọi `connection.commit()` khi phát hiện khoảng lặng qua CÙNG `silence_classifier` mà
ZipFormer dùng (mặc định energy-based), giữ hành vi endpoint nhất quán giữa các provider.

Bug thật cần tránh khi maintain: `_start_message_handler()` của SDK (elevenlabs.realtime.
connection) chạy trong task riêng, gọi callback đồng bộ (`connection.on(...)`) — callback ở
đây CHỈ được `queue.put_nowait()`, không được làm việc nặng hay await trực tiếp, để không
chặn message handler và làm rớt event của các message tới sau.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any, AsyncIterator

from inference.asr.base import AsrAuthError
from inference.asr.config import ElevenLabsRealtimeConfig
from speech.asr.vad.base import FrameClassifier
from speech.types import NARROWBAND_RATE, AsrSegmentEnd, TranscriptEvent

_QUEUE_DONE = object()
_SUPPORTED_RATES = (8_000, 16_000)
# message_type server trả khi không nhận key (sai, hết hạn, thiếu quyền speech_to_text).
_AUTH_ERRORS = frozenset({"auth_error"})


class ElevenLabsRealtimeASR:
    input_sample_rate = NARROWBAND_RATE

    def __init__(self, config: ElevenLabsRealtimeConfig) -> None:
        self._config = config

    @property
    def model(self) -> str:
        return self._config.model

    def transcribe(self, pcm: bytes) -> Any:
        raise NotImplementedError(
            "ElevenLabsRealtimeASR chỉ hỗ trợ stream() — không có chế độ transcribe() "
            "1 lượt đơn lẻ qua REST (dùng ElevenLabsSTTAdapter trong eval/stt-bench cho "
            "batch transcribe với scribe_v2)."
        )

    async def stream(
        self,
        frames: AsyncIterator[bytes | AsrSegmentEnd],
        *,
        audio_sample_rate: int = NARROWBAND_RATE,
        silence_classifier: FrameClassifier | None = None,
        end_silence_ms: int = 600,
        pre_speech_ms: int | None = None,
    ) -> AsyncIterator[TranscriptEvent]:
        """`frames`: PCM liên tục ở `audio_sample_rate` (8000 hoặc 16000 — xem
        `_SUPPORTED_RATES`, không resample, gửi thẳng ở rate nguồn). Endpoint hoá turn
        bằng cùng chiến lược energy/webrtc classifier như ZipFormer.stream(), KHÔNG dùng
        VAD nội bộ của ElevenLabs (xem docstring module).

        `pre_speech_ms` không áp dụng: mọi frame đều đã gửi lên server.

        `AsrSegmentEnd.DISCARD` bị bỏ qua: audio đã gửi lên server không rút lại được, và
        commit để rồi bỏ kết quả có thể trả về sau khi bot dứt lời, thành turn giả."""
        if audio_sample_rate not in _SUPPORTED_RATES:
            raise ValueError(
                f"ElevenLabsRealtimeASR stream không hỗ trợ sample rate {audio_sample_rate} "
                f"(chỉ {_SUPPORTED_RATES})"
            )
        if silence_classifier is None:
            from speech.asr.vad.energy import EnergyFrameClassifier

            silence_classifier = EnergyFrameClassifier()

        from elevenlabs.client import AsyncElevenLabs
        from elevenlabs.realtime.connection import RealtimeEvents
        from elevenlabs.realtime.scribe import AudioFormat, CommitStrategy

        audio_format = AudioFormat.PCM_8000 if audio_sample_rate == 8_000 else AudioFormat.PCM_16000
        client = AsyncElevenLabs(api_key=self._config.api_key.get_secret_value())
        keyterms = [t.strip() for t in self._config.keyterms.split(",") if t.strip()]
        connection = await client.speech_to_text.realtime.connect(
            {
                "model_id": self._config.model,
                "audio_format": audio_format,
                "sample_rate": audio_sample_rate,
                "commit_strategy": CommitStrategy.MANUAL,
                "language_code": self._config.language_code,
                "keyterms": keyterms or None,
            }
        )

        event_queue: "asyncio.Queue[object]" = asyncio.Queue()
        # `connection.commit()` chỉ GỬI message commit — server trả `committed_transcript`
        # qua một round-trip network riêng, không đồng bộ với awaitable của commit(). Bug
        # thật đã gặp: đẩy _QUEUE_DONE ngay sau await commit() làm consumer thoát vòng lặp
        # trước khi event committed kịp tới, generator kết thúc rỗng dù audio đã gửi đủ.
        # `_pending_commits` đếm số commit đã gửi mà chưa thấy committed_transcript tương
        # ứng — _pump_audio() chỉ đẩy _QUEUE_DONE khi về 0 (hoặc timeout an toàn).
        pending_commits = 0
        commit_settled = asyncio.Event()
        commit_settled.set()

        def _on_partial(data: dict) -> None:
            event_queue.put_nowait(TranscriptEvent(text=data.get("text", ""), is_final=False))

        def _on_committed(data: dict) -> None:
            nonlocal pending_commits
            event_queue.put_nowait(TranscriptEvent(text=data.get("text", ""), is_final=True))
            pending_commits = max(0, pending_commits - 1)
            if pending_commits == 0:
                commit_settled.set()

        def _on_error(data: dict) -> None:
            if data.get("message_type") in _AUTH_ERRORS:
                event_queue.put_nowait(
                    AsrAuthError("ElevenLabs từ chối ELEVENLABS_API_KEY (auth_error)")
                )
                return
            event_queue.put_nowait(RuntimeError(f"ElevenLabs realtime STT error: {data}"))

        connection.on(RealtimeEvents.PARTIAL_TRANSCRIPT, _on_partial)
        connection.on(RealtimeEvents.COMMITTED_TRANSCRIPT, _on_committed)
        connection.on(RealtimeEvents.ERROR, _on_error)

        async def _commit() -> None:
            nonlocal pending_commits
            pending_commits += 1
            commit_settled.clear()
            await connection.commit()

        async def _pump_audio() -> None:
            in_speech = False
            silent_ms = 0.0
            try:
                async for frame in frames:
                    if isinstance(frame, AsrSegmentEnd):
                        continue
                    frame_ms = len(frame) / 2 / audio_sample_rate * 1000
                    if frame_ms <= 0:
                        continue
                    is_speech = silence_classifier.is_speech(frame)
                    if not in_speech and not is_speech:
                        continue
                    in_speech = True
                    await connection.send({"audio_base_64": base64.b64encode(frame).decode()})
                    if is_speech:
                        silent_ms = 0.0
                    else:
                        silent_ms += frame_ms
                    if silent_ms >= end_silence_ms:
                        await _commit()
                        in_speech = False
                        silent_ms = 0.0
                if in_speech:
                    await _commit()
                try:
                    await asyncio.wait_for(commit_settled.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
            except Exception as exc:  # noqa: BLE001 — propagate qua queue, xem docstring
                await event_queue.put(exc)
            finally:
                await event_queue.put(_QUEUE_DONE)

        pump_task = asyncio.ensure_future(_pump_audio())
        try:
            last_emitted_text = ""
            while True:
                item = await event_queue.get()
                if item is _QUEUE_DONE:
                    return
                if isinstance(item, Exception):
                    raise item
                event: TranscriptEvent = item
                if not event.text or event.text == last_emitted_text:
                    if event.is_final:
                        last_emitted_text = ""
                    continue
                if not event.is_final:
                    last_emitted_text = event.text
                else:
                    last_emitted_text = ""
                yield event
        finally:
            pump_task.cancel()
            await asyncio.gather(pump_task, return_exceptions=True)
            await connection.close()
