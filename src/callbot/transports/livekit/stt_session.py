"""Chế độ chỉ thử STT (trang `/ui/stt`): nghe mic người dùng qua đúng STTPipeline của cuộc gọi
LiveKit (VAD, tăng âm, ASR, chốt lượt) và gửi chữ từng lượt về trình duyệt — không có bot, không
TTS, không gọi engine.

Mỗi lượt gửi qua data channel `STT_TOPIC` (JSON):
- `partial`: chữ tạm thời của lượt đang nói (ASR decode lại / gửi interim), thay dòng trước đó;
- `final`: lượt đã chốt — đúng chữ engine sẽ nhận trong cuộc gọi thật;
- `dropped`: lượt ASR có nghe ra chữ nhưng pipeline bỏ (chỉ có từ đệm, Validator DROP).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, AsyncIterator, Callable, Optional

from callbot.transports.livekit.audio_adapter import livekit_frame_to_segment
from speech.asr.pipeline import STTPipeline
from speech.asr.vad.base import VadEvent
from speech.turn.controller import TurnController
from speech.turn.events import UserTurnCompleted
from speech.types import TranscriptEvent

if TYPE_CHECKING:
    from livekit import rtc

logger = logging.getLogger(__name__)

STT_TOPIC = "callbot.stt"

_DONE = object()


class ObservedTurnController(TurnController):
    """TurnController báo chữ của lượt đang hình thành (`on_live`) và lượt bị bỏ (`on_dropped`).

    Đọc `_candidate` của lớp cha: lượt bị bỏ = lượt hiện tại bị thay bằng lượt mới mà chưa chốt
    (`_reset_candidate` khi từ đệm / Validator DROP). Việc bỏ có thể xảy ra trong hẹn giờ của lớp
    cha nên chỉ phát hiện được ở event kế tiếp hoặc khi gọi `flush_dropped()`."""

    def __init__(
        self,
        *,
        on_live: Callable[[str], None],
        on_dropped: Callable[[str], None],
        **options: object,
    ) -> None:
        super().__init__(**options)  # type: ignore[arg-type]
        self._on_live = on_live
        self._on_dropped = on_dropped
        self._watched = self._candidate

    def flush_dropped(self) -> None:
        old = self._watched
        if self._candidate is old:
            return
        self._watched = self._candidate
        if not old.finalized and old.text.strip():
            self._on_dropped(old.text.strip())

    async def on_vad_event(self, event: VadEvent) -> None:
        self.flush_dropped()
        await super().on_vad_event(event)
        self.flush_dropped()

    async def on_transcript_event(self, event: TranscriptEvent) -> None:
        self.flush_dropped()
        await super().on_transcript_event(event)
        self.flush_dropped()
        candidate = self._candidate
        if not candidate.finalized and candidate.text.strip():
            self._on_live(candidate.text.strip())


class SttSession:
    """1 instance/room. Nghe đúng một participant (người mở trang), chạy tới khi room ngắt."""

    def __init__(
        self,
        room: "rtc.Room",
        stt_pipeline: STTPipeline,
        *,
        turn_controller_options: dict[str, object],
        sample_rate: int,
        frame_ms: int,
        input_queue_ms: int,
        caller_identity: Optional[str] = None,
    ) -> None:
        self._room = room
        self._pipeline = stt_pipeline
        self._sample_rate = sample_rate
        self._frame_ms = frame_ms
        self._input_queue_frames = max(1, input_queue_ms // frame_ms)
        self._frames_queue: asyncio.Queue[object] = asyncio.Queue(maxsize=self._input_queue_frames)
        self._outbox: asyncio.Queue[object] = asyncio.Queue()
        self._caller_identity = caller_identity
        self._pump_task: Optional[asyncio.Task] = None
        self._turn = 0
        self._controller = ObservedTurnController(
            on_live=lambda text: self._send("partial", self._turn + 1, text),
            on_dropped=lambda text: self._send("dropped", self._turn + 1, text),
            **turn_controller_options,
        )

    async def run(self) -> None:
        self._room.on("track_subscribed", self._on_track_subscribed)
        self._room.on("disconnected", self._on_disconnected)
        for participant in self._room.remote_participants.values():
            for publication in participant.track_publications.values():
                if publication.track is not None:
                    self._on_track_subscribed(publication.track, publication, participant)
        logger.info("stt_session: start room=%s", self._room.name)
        sender = asyncio.create_task(self._send_loop())
        try:
            async for turn in self._pipeline.stream(
                self._frames(), turn_controller=self._controller
            ):
                self._controller.flush_dropped()
                self._turn += 1
                self._send_final(turn)
        finally:
            self._controller.flush_dropped()
            if self._pump_task is not None:
                self._pump_task.cancel()
            self._outbox.put_nowait(_DONE)
            await sender
            logger.info("stt_session: end room=%s turns=%d", self._room.name, self._turn)

    def _send(self, kind: str, turn: int, text: str, **extra: object) -> None:
        self._outbox.put_nowait({"type": "stt", "kind": kind, "turn": turn, "text": text, **extra})

    def _send_final(self, turn: UserTurnCompleted) -> None:
        self._send(
            "final",
            self._turn,
            turn.text,
            confidence=turn.confidence,
            first_partial_ms=turn.first_partial_ms,
            final_ms=turn.final_ms,
            audio_ms=turn.audio_duration_ms,
        )

    async def _send_loop(self) -> None:
        """Gửi lần lượt (partial trước final của cùng lượt). Gửi lỗi chỉ mất một dòng hiển thị."""
        while (payload := await self._outbox.get()) is not _DONE:
            try:
                await self._room.local_participant.publish_data(
                    json.dumps(payload, ensure_ascii=False), reliable=True, topic=STT_TOPIC
                )
            except Exception as exc:
                logger.warning(
                    "stt_session: không gửi được chữ room=%s: %s",
                    self._room.name,
                    type(exc).__name__,
                )

    def _on_track_subscribed(
        self, track: "rtc.Track", publication: object, participant: object
    ) -> None:
        from livekit import rtc

        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        identity = getattr(participant, "identity", None)
        source = getattr(publication, "source", rtc.TrackSource.SOURCE_UNKNOWN)
        if source not in (rtc.TrackSource.SOURCE_MICROPHONE, rtc.TrackSource.SOURCE_UNKNOWN):
            return
        if self._caller_identity is None:
            self._caller_identity = identity
        elif identity != self._caller_identity:
            return
        if self._pump_task is not None and not self._pump_task.done():
            self._pump_task.cancel()
        self._pump_task = asyncio.ensure_future(self._pump_track(track))

    async def _pump_track(self, track: "rtc.Track") -> None:
        from livekit import rtc

        stream = rtc.AudioStream.from_track(
            track=track,
            sample_rate=self._sample_rate,
            num_channels=1,
            frame_size_ms=self._frame_ms,
            capacity=self._input_queue_frames,
        )
        try:
            async for event in stream:
                segment = livekit_frame_to_segment(event.frame, target_rate=self._sample_rate)
                if segment.pcm:
                    await self._frames_queue.put(segment.pcm)
        finally:
            await stream.aclose()

    def _on_disconnected(self, *_args: object) -> None:
        # Hàng đợi có thể đầy: bỏ một frame cũ để chắc chắn tín hiệu kết thúc vào được.
        if self._frames_queue.full():
            self._frames_queue.get_nowait()
        self._frames_queue.put_nowait(_DONE)

    async def _frames(self) -> AsyncIterator[bytes]:
        while (item := await self._frames_queue.get()) is not _DONE:
            yield item  # type: ignore[misc]
