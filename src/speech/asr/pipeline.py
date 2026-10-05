"""STT đường LiveKit: frame PCM liên tục -> VAD + ASR song song -> TurnController -> lượt nói.

Mỗi frame đi qua `_CallStream._fanout`:
  1. Bộ phân loại dùng chung gán nhãn có/không tiếng nói (đúng một lần mỗi frame).
  2. Vào hàng đợi VAD (luôn luôn) và cập nhật bằng chứng SNR (khi bật Validator).
  3. Vào hàng đợi ASR — trừ lúc bot đang nói: giữ trong pre-roll, chỉ đưa vào ASR khi
     người gọi có dấu hiệu ngắt lời (barge-in).
Hai worker chạy song song: `_drain_vad` -> TurnController.on_vad_event,
`_drain_asr` -> TurnController.on_transcript_event. TurnController quyết định lúc chốt lượt;
`STTPipeline.stream()` trả từng lượt đã chốt.
"""

import asyncio
import logging
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from speech.asr.recognizer import Recognizer
from speech.asr.stream_context import ASRStreamContext, StreamingFrame
from speech.asr.vad.async_stream import AsyncStreamingVAD
from speech.asr.vad.shared import SharedSpeechDetector
from speech.turn.controller import TurnController
from speech.turn.events import UserTurnCompleted
from speech.turn.evidence import TurnEvidence
from speech.turn.interruption import InterruptionController, InterruptionState
from speech.types import AsrSegmentEnd

_QUEUE_DONE = object()
# ASR tồn quá mức này (ms audio chưa decode) thì log cảnh báo; hết cảnh báo khi còn một nửa.
_ASR_LAG_WARN_MS = 1_000.0

logger = logging.getLogger(__name__)


@dataclass
class _QueuedVadFrame:
    pcm: bytes
    processed: asyncio.Event


class STTPipeline:
    """Một instance cho một cuộc gọi (detector và evidence có trạng thái)."""

    def __init__(
        self,
        asr: Recognizer,
        vad: AsyncStreamingVAD,
        *,
        sample_rate: int,
        queue_max_frames: int,
        asr_queue_max_frames: int,
        barge_in_preroll_frames: int,
        detector: Optional[SharedSpeechDetector] = None,
        evidence: Optional[TurnEvidence] = None,
        asr_stream_options: Optional[Mapping[str, object]] = None,
    ) -> None:
        """Kích thước hàng đợi/pre-roll tính bằng frame, `build_streaming_bundle` quy đổi từ
        config/livekit.yaml."""
        for name, value in (
            ("queue_max_frames", queue_max_frames),
            ("asr_queue_max_frames", asr_queue_max_frames),
            ("barge_in_preroll_frames", barge_in_preroll_frames),
        ):
            if value <= 0:
                raise ValueError(f"{name} phải lớn hơn 0")
        self.asr = asr
        self.vad = vad
        self.sample_rate = sample_rate
        self.detector = detector
        self.evidence = evidence
        self.asr_stream_options = dict(asr_stream_options or {})
        self.queue_max_frames = queue_max_frames
        # Hàng đợi ASR rộng hơn hàng đợi VAD nhiều: decode chậm không được chặn _fanout, nếu
        # không VAD và barge-in đứng theo ASR.
        self.asr_queue_max_frames = asr_queue_max_frames
        self.barge_in_preroll_frames = barge_in_preroll_frames

    @property
    def provider_name(self) -> Optional[str]:
        return getattr(self.asr, "name", None)

    @property
    def model(self) -> Optional[str]:
        return getattr(self.asr, "model", None)

    async def stream(
        self,
        frames: AsyncIterator[bytes],
        turn_controller: TurnController,
        interruption: Optional[InterruptionController] = None,
    ) -> AsyncIterator[UserTurnCompleted]:
        """`frames`: PCM ở `sample_rate`, liên tục suốt cuộc gọi. `interruption` nhận cùng
        event VAD/ASR với TurnController để xác nhận barge-in."""
        call = _CallStream(self, turn_controller, interruption)
        async for turn in call.turns(frames):
            yield turn


class _CallStream:
    """Trạng thái của một lần `STTPipeline.stream()`."""

    def __init__(
        self,
        pipeline: STTPipeline,
        controller: TurnController,
        interruption: Optional[InterruptionController],
    ) -> None:
        self._pipeline = pipeline
        self._controller = controller
        self._interruption = interruption
        self._vad_queue: "asyncio.Queue[object]" = asyncio.Queue(maxsize=pipeline.queue_max_frames)
        self._asr_queue: "asyncio.Queue[object]" = asyncio.Queue(
            maxsize=pipeline.asr_queue_max_frames
        )
        # ASR đang chờ frame mới (không decode). TurnController hỏi trước khi chốt câu
        # bằng partial: ASR còn tồn audio của câu thì final sắp tới.
        self._asr_idle = True
        self._asr_lag_warned = False
        # Đã gửi frame vào ASR từ lần báo AsrSegmentEnd gần nhất.
        self._asr_segment_open = False
        # Audio lúc bot đang nói, phát lại vào ASR khi nghi người gọi ngắt lời.
        self._pre_roll: deque[bytes] = deque(maxlen=pipeline.barge_in_preroll_frames)
        self._replayed_pre_roll = False
        self._context = (
            ASRStreamContext() if getattr(pipeline.asr, "supports_stream_context", False) else None
        )

    async def turns(self, frames: AsyncIterator[bytes]) -> AsyncIterator[UserTurnCompleted]:
        controller = self._controller
        controller.set_asr_pending_probe(self._asr_has_backlog)
        if self._context is not None:
            controller.set_asr_final_required(True)
        fanout_task = asyncio.ensure_future(self._fanout(frames))
        vad_task = asyncio.ensure_future(self._drain_vad())
        asr_task = asyncio.ensure_future(self._drain_asr())
        workers = (fanout_task, vad_task, asr_task)

        def finished() -> bool:
            return vad_task.done() and asr_task.done() and not controller.has_pending_turn()

        def raise_worker_errors() -> None:
            for task in workers:
                if task.done():
                    task.result()

        next_turn = None
        try:
            while True:
                # Lỗi của transport/VAD/ASR nổi lên trước khi trả lượt đang chờ.
                raise_worker_errors()
                if finished():
                    return
                next_turn = asyncio.ensure_future(controller.get_turn())
                done, _ = await asyncio.wait(
                    {next_turn, *(task for task in workers if not task.done())},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                raise_worker_errors()
                if next_turn in done:
                    yield next_turn.result()
                    continue
                # Một worker vừa xong (hết audio): bỏ lượt chờ dở, vòng sau kiểm tra kết thúc.
                next_turn.cancel()
                await asyncio.gather(next_turn, return_exceptions=True)
        finally:
            controller.set_asr_pending_probe(None)
            if next_turn is not None:
                next_turn.cancel()
            for task in workers:
                task.cancel()
            await asyncio.gather(
                *workers, *([next_turn] if next_turn else []), return_exceptions=True
            )
            if self._context is not None:
                await controller.aclose()
                controller.set_asr_final_required(False)

    # --- Bước 1: phân phối từng frame -------------------------------------------------

    async def _fanout(self, frames: AsyncIterator[bytes]) -> None:
        pipeline = self._pipeline
        try:
            async for frame in frames:
                if pipeline.detector is not None:
                    pipeline.detector.classify(frame)
                if self._context is None:
                    await self._vad_queue.put(frame)
                else:
                    processed = asyncio.Event()
                    await self._vad_queue.put(_QueuedVadFrame(frame, processed))
                    # Assign the VAD segment before stamping frames sent to remote ASR.
                    await processed.wait()
                if pipeline.evidence is not None:
                    pipeline.evidence.observe_frame(frame)
                if self._controller.is_bot_speaking:
                    await self._route_while_bot_speaking(frame)
                else:
                    self._pre_roll.clear()
                    self._replayed_pre_roll = False
                    await self._send_to_asr(frame)
        finally:
            # Đang huỷ thì consumer cũng đang dừng: chờ đặt sentinel vào hàng đợi đầy sẽ treo.
            task = asyncio.current_task()
            if task is None or not task.cancelling():
                await self._vad_queue.put(_QUEUE_DONE)
                await self._asr_queue.put(_QUEUE_DONE)

    async def _route_while_bot_speaking(self, frame: bytes) -> None:
        # Nhường lịch để VAD xử lý frame vừa vào hàng đợi — có thể chuyển sang CANDIDATE.
        await asyncio.sleep(0)
        if self._interruption_state() == InterruptionState.INTERRUPTION_CANDIDATE:
            # Nghi người gọi ngắt lời: ASR phải nghe audio thật để tự xác nhận
            # (on_partial_transcript). Phát lại pre-roll một lần, rồi gửi tiếp từng frame.
            if not self._replayed_pre_roll:
                # Phần còn trong ASR là audio trước lúc bot nói, không thuộc lần ngắt lời này.
                await self._discard_asr_segment()
                for buffered in self._pre_roll:
                    await self._send_to_asr(buffered)
                self._pre_roll.clear()
                self._replayed_pre_roll = True
            await self._send_to_asr(frame)
            return
        # Chưa có dấu hiệu ngắt lời: giữ trong pre-roll, không decode tiếng bot vọng lại.
        self._replayed_pre_roll = False
        self._pre_roll.append(frame)
        if self._interruption_state() != InterruptionState.INTERRUPTED:
            # Bỏ câu dở trong ASR, nếu không nó bị ghép vào câu sau
            # ("ANH SINH" + "ANH SINH NGÀY ..."). Câu ngắt lời đã xác nhận thì giữ.
            await self._discard_asr_segment()

    def _interruption_state(self) -> Optional[InterruptionState]:
        return self._interruption.state if self._interruption is not None else None

    # --- Hàng đợi ASR -----------------------------------------------------------------

    async def _send_to_asr(self, frame: bytes) -> None:
        item = (
            StreamingFrame(frame, self._context.generation, self._context.segment_id)
            if self._context is not None
            else frame
        )
        await self._asr_queue.put(item)
        self._asr_segment_open = True
        lag_ms = self._asr_queue.qsize() * len(frame) / 2 / self._pipeline.sample_rate * 1000
        if lag_ms >= _ASR_LAG_WARN_MS and not self._asr_lag_warned:
            logger.warning("stt_pipeline: ASR tồn %.0f ms audio chưa decode", lag_ms)
            self._asr_lag_warned = True
        elif lag_ms < _ASR_LAG_WARN_MS / 2 and self._asr_lag_warned:
            logger.info("stt_pipeline: ASR đã bắt kịp (tồn %.0f ms)", lag_ms)
            self._asr_lag_warned = False

    async def _discard_asr_segment(self) -> None:
        """ASR chỉ tự chốt câu khi thấy đủ khoảng lặng; ngừng đưa frame thì phải báo bỏ câu
        dở, nếu không nó nằm lại buffer (xem AsrSegmentEnd)."""
        if self._asr_segment_open:
            if self._context is not None:
                self._context.invalidate()
            await self._asr_queue.put(AsrSegmentEnd.DISCARD)
            self._asr_segment_open = False

    def _asr_has_backlog(self) -> bool:
        return (
            not self._asr_idle
            or not self._asr_queue.empty()
            or bool(self._context is not None and self._context.pending)
        )

    async def _asr_frames(self) -> AsyncIterator[object]:
        while True:
            self._asr_idle = True
            item = await self._asr_queue.get()
            self._asr_idle = False
            if item is _QUEUE_DONE:
                return
            yield item

    # --- Bước 2: hai worker tiêu thụ song song ----------------------------------------

    async def _drain_vad(self) -> None:
        async for event in self._pipeline.vad.process(_dequeue(self._vad_queue)):
            if event.kind == "speech_start" and self._context is not None:
                self._context.start_utterance()
            if event.kind != "speech":
                logger.debug("main_vad: %s", event.kind)
            await self._controller.on_vad_event(event)
            if self._interruption is not None:
                if event.kind == "speech_start":
                    await self._interruption.on_speech_started(event)
                elif event.kind == "speech_end":
                    await self._interruption.on_speech_ended_without_confirmation()

    async def _drain_asr(self) -> None:
        pipeline = self._pipeline
        options = dict(pipeline.asr_stream_options)
        if self._context is not None:
            options["stream_context"] = self._context
        async for event in pipeline.asr.stream(self._asr_frames(), **options):
            if self._context is not None and not self._context.accepts(event):
                continue
            evidence = pipeline.evidence
            if evidence is not None:
                stability = evidence.observe_transcript(event)
                self._controller.on_evidence_updated(
                    noise_evidence=evidence.utterance_noise, stability=stability
                )
                if self._interruption is not None:
                    self._interruption.on_evidence_updated(
                        noise_evidence=evidence.frame_noise, stability=stability
                    )
            await self._controller.on_transcript_event(event)
            if self._interruption is not None:
                await self._interruption.on_partial_transcript(event)


async def _dequeue(queue: "asyncio.Queue[object]") -> AsyncIterator[bytes]:
    while True:
        item = await queue.get()
        if item is _QUEUE_DONE:
            return
        if isinstance(item, _QueuedVadFrame):
            try:
                yield item.pcm
            finally:
                item.processed.set()
        else:
            yield item  # type: ignore[misc]
