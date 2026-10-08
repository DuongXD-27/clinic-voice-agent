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
from speech.audio.noise_tracker import NoiseEvidence
from speech.audio.speaker_gate import SpeakerGate
from speech.turn.controller import TurnController, strip_echo_prefix
from speech.turn.events import UserTurnCompleted
from speech.turn.evidence import TurnEvidence
from speech.turn.interruption import InterruptionController, InterruptionState
from speech.types import AsrSegmentEnd, AudioSegment

_QUEUE_DONE = object()
# ASR tồn quá mức này (ms audio chưa decode) thì log cảnh báo; hết cảnh báo khi còn một nửa.
_ASR_LAG_WARN_MS = 1_000.0
# Cổng giọng người gọi: giữ thêm chừng này frame trước speech_start (VAD báo trễ), và tối đa
# chừng này giây audio của một lượt.
_TURN_AUDIO_LEAD_FRAMES = 10
_TURN_AUDIO_MAX_S = 20

logger = logging.getLogger(__name__)


@dataclass
class _QueuedVadFrame:
    pcm: bytes
    processed: asyncio.Event


@dataclass
class _HeldAudio:
    pcm: bytes
    heard_from: float
    lookback_s: float
    speech_ms: float
    noise_evidence: Optional[NoiseEvidence]
    echo_text: str = ""


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
        speaker_gate: Optional[SpeakerGate] = None,
        keep_unconfirmed_barge_in: bool = False,
    ) -> None:
        """Kích thước hàng đợi/pre-roll tính bằng frame, `build_streaming_bundle` quy đổi từ
        config/livekit.yaml. `speaker_gate`: THỬ NGHIỆM, bỏ lượt dài không phải giọng người gọi.
        `keep_unconfirmed_barge_in`: lời chen lúc bot nói chưa được xác nhận ngắt lời được giữ
        riêng (không qua ASR streaming), decode khi bot dứt lời (`_CallStream._decode_held`)."""
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
        self.speaker_gate = speaker_gate
        self.keep_unconfirmed_barge_in = keep_unconfirmed_barge_in

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
        # Đã gửi ASR audio lúc bot nói (ứng viên ngắt lời) mà chưa được xác nhận.
        self._unconfirmed_barge_in_audio = False
        # Thời lượng pre-roll đã phát lại vào ASR cho ứng viên ngắt lời gần nhất (giây).
        self._replayed_pre_roll_s = 0.0
        self._context = (
            ASRStreamContext() if getattr(pipeline.asr, "supports_stream_context", False) else None
        )
        # Audio của lượt đang hình thành, cho cổng giọng người gọi (None = tắt cổng).
        self._turn_audio: Optional[bytearray] = (
            None if pipeline.speaker_gate is None else bytearray()
        )
        self._turn_audio_open = False
        self._before_speech: deque[bytes] = deque(maxlen=_TURN_AUDIO_LEAD_FRAMES)
        # `keep_unconfirmed_barge_in`: audio ứng viên ngắt lời đang mở (pre-roll + các frame lúc
        # ứng viên), và các ứng viên đã đóng mà chưa xác nhận trong câu bot này —
        # (pcm, lúc VAD báo ứng viên, pre-roll giây). Chỉ thành lượt sau khi bot dứt lời.
        self._held_open: Optional[bytearray] = None
        self._held_meta = (0.0, 0.0)
        self._held_speech_ms = 0.0
        self._held: list[_HeldAudio] = []
        self._held_tasks: set[asyncio.Task] = set()
        self._held_failure = asyncio.get_running_loop().create_future()

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
            return (
                vad_task.done()
                and asr_task.done()
                and not self._held_tasks
                and not controller.has_pending_turn()
            )

        def raise_worker_errors() -> None:
            for task in workers:
                if task.done():
                    task.result()
            if self._held_failure.done() and not self._held_failure.cancelled():
                self._held_failure.result()

        next_turn = None
        try:
            while True:
                # Lỗi của transport/VAD/ASR nổi lên trước khi trả lượt đang chờ.
                raise_worker_errors()
                if finished():
                    return
                next_turn = asyncio.ensure_future(controller.get_turn())
                done, _ = await asyncio.wait(
                    {
                        next_turn,
                        self._held_failure,
                        *(task for task in workers if not task.done()),
                        *self._held_tasks,
                    },
                    return_when=asyncio.FIRST_COMPLETED,
                )
                raise_worker_errors()
                if next_turn in done:
                    turn = next_turn.result()
                    if await self._speaker_gate_allows(turn):
                        yield turn
                    continue
                # Một worker vừa xong (hết audio): bỏ lượt chờ dở, vòng sau kiểm tra kết thúc.
                next_turn.cancel()
                await asyncio.gather(next_turn, return_exceptions=True)
        finally:
            self._held_failure.cancel()
            controller.set_asr_pending_probe(None)
            if next_turn is not None:
                next_turn.cancel()
            for task in (*workers, *self._held_tasks):
                task.cancel()
            await asyncio.gather(
                *workers,
                *self._held_tasks,
                *([next_turn] if next_turn else []),
                return_exceptions=True,
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
                if self._interruption is not None:
                    self._interruption.on_caller_audio(frame)
                if self._turn_audio is not None and not self._controller.is_bot_speaking:
                    # Không giữ audio lúc bot nói: tiếng bot vọng lại không được thành giọng mẫu.
                    self._keep_turn_audio(frame)
                if self._controller.is_bot_speaking:
                    await self._route_while_bot_speaking(frame)
                else:
                    if self._unconfirmed_barge_in_audio and self._interruption is not None:
                        # Bot dứt lời khi ứng viên ngắt lời còn mở (tiếng bot vọng lại giữ VAD
                        # "đang nói" suốt câu): final của đoạn ASR đó bắt đầu bằng câu bot. Giữ
                        # đoạn — có thể có lời người gọi chen vào — nhưng bỏ phần câu bot.
                        self._unconfirmed_barge_in_audio = False
                        self._expect_echo()
                    # Ứng viên còn mở lúc bot dứt lời đi tiếp trong đoạn ASR trên, không giữ riêng.
                    self._held_open = None
                    if self._held:
                        self._release_held()
                    # Speech can start just before the bot stops, before VAD announces it.
                    # These frames have not reached ASR yet; replay them instead of losing them.
                    if self._pre_roll:
                        lookback_s = sum(map(len, self._pre_roll)) / 2 / pipeline.sample_rate
                        if self._interruption is not None:
                            self._controller.expect_echo(
                                self._interruption.echo_text(
                                    lookback_s, heard_from=self._interruption.bot_stopped_at
                                )
                            )
                        for buffered in self._pre_roll:
                            await self._send_to_asr(buffered, is_preroll=True)
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
                self._replayed_pre_roll_s = (
                    sum(len(buffered) for buffered in self._pre_roll)
                    / 2
                    / self._pipeline.sample_rate
                )
                if self._pipeline.keep_unconfirmed_barge_in and self._interruption is not None:
                    self._held_open = bytearray(b"".join(self._pre_roll))
                    self._held_meta = (self._interruption.heard_from, self._replayed_pre_roll_s)
                    self._held_speech_ms = 0.0
                for buffered in self._pre_roll:
                    await self._send_to_asr(buffered, is_preroll=True)
                self._pre_roll.clear()
                self._replayed_pre_roll = True
            self._unconfirmed_barge_in_audio = True
            if self._held_open is not None:
                self._held_open.extend(frame)
                detector = self._pipeline.detector
                if detector is None or detector.view().is_speech(frame):
                    self._held_speech_ms += len(frame) / 2 / self._pipeline.sample_rate * 1000
                # Keep the start of the candidate; never grow a recording without a bound.
                limit = _TURN_AUDIO_MAX_S * self._pipeline.sample_rate * 2
                del self._held_open[limit:]
            await self._send_to_asr(frame)
            return
        if self._held_open is not None:
            if self._interruption_state() != InterruptionState.INTERRUPTED:
                # Ứng viên kết thúc (VAD hết câu) mà chưa được xác nhận: đoạn ASR sắp bị bỏ, giữ
                # audio riêng tới khi bot dứt lời. Đã xác nhận thì đoạn ASR đi tiếp như thường.
                evidence = self._pipeline.evidence
                self._held.append(
                    _HeldAudio(
                        bytes(self._held_open),
                        *self._held_meta,
                        speech_ms=self._held_speech_ms,
                        noise_evidence=evidence.utterance_noise if evidence is not None else None,
                    )
                )
            self._held_open = None
        # Chưa có dấu hiệu ngắt lời: giữ trong pre-roll, không decode tiếng bot vọng lại.
        self._replayed_pre_roll = False
        self._pre_roll.append(frame)
        if self._interruption_state() != InterruptionState.INTERRUPTED:
            # Bỏ câu dở trong ASR, nếu không nó bị ghép vào câu sau
            # ("ANH SINH" + "ANH SINH NGÀY ..."). Câu ngắt lời đã xác nhận thì giữ.
            self._unconfirmed_barge_in_audio = False
            await self._discard_asr_segment()

    def _release_held(self) -> None:
        held, self._held = self._held, []
        # Snapshot the bot reference before another utterance starts while decode is running.
        for segment in held:
            segment.echo_text = self._interruption.echo_text(
                segment.lookback_s, heard_from=segment.heard_from
            )
        self._controller.begin_barge_in_recovery()
        task = asyncio.ensure_future(self._decode_held(held))
        self._held_tasks.add(task)

        def finished(done: asyncio.Task) -> None:
            self._held_tasks.discard(done)
            if not done.cancelled() and (error := done.exception()) is not None:
                if not self._held_failure.done():
                    self._held_failure.set_exception(error)

        task.add_done_callback(finished)

    async def _decode_held(self, held: list[_HeldAudio]) -> None:
        """Bot đã dứt lời: decode các ứng viên giữ riêng, bỏ tiếng bot vọng lại (cùng cách như
        lượt thường), phần còn lại đưa TurnController. Tiếng bot chỉ tới Core nếu lọt cả bước
        bỏ vọng — như lượt thường."""
        try:
            for held_audio in held:
                segment = AudioSegment(pcm=held_audio.pcm, sample_rate=self._pipeline.sample_rate)
                try:
                    transcript = await asyncio.to_thread(self._pipeline.asr.transcribe, segment)
                except NotImplementedError:
                    logger.warning("stt_pipeline: ASR không decode được đoạn rời — bỏ lời chen")
                    return
                text = strip_echo_prefix(transcript.text.strip(), held_audio.echo_text)
                self._controller.on_held_barge_in(
                    text,
                    confidence=transcript.confidence,
                    speech_ms=held_audio.speech_ms,
                    noise_evidence=held_audio.noise_evidence,
                )
        finally:
            self._controller.end_barge_in_recovery()

    def _keep_turn_audio(self, frame: bytes) -> None:
        # Luôn giữ các frame gần nhất: lượt mới mở (speech_start, VAD báo trễ) lấy làm phần đầu.
        self._before_speech.append(frame)
        if not self._turn_audio_open:
            return
        self._turn_audio.extend(frame)
        overflow = len(self._turn_audio) - _TURN_AUDIO_MAX_S * self._pipeline.sample_rate * 2
        if overflow > 0:
            del self._turn_audio[:overflow]

    async def _speaker_gate_allows(self, turn: UserTurnCompleted) -> bool:
        gate = self._pipeline.speaker_gate
        if gate is None:
            return True
        pcm = bytes(self._turn_audio)
        self._turn_audio.clear()
        self._turn_audio_open = False
        speech_ms = turn.audio_duration_ms
        if speech_ms is not None:
            # Lượt ngắt lời: phần nói chồng lúc bot nói không được giữ.
            speech_ms = min(speech_ms, len(pcm) / 2 / self._pipeline.sample_rate * 1000)
        return await asyncio.to_thread(gate.allows, pcm, self._pipeline.sample_rate, speech_ms)

    def _interruption_state(self) -> Optional[InterruptionState]:
        return self._interruption.state if self._interruption is not None else None

    # --- Hàng đợi ASR -----------------------------------------------------------------

    async def _send_to_asr(self, frame: bytes, *, is_preroll: bool = False) -> None:
        item = (
            StreamingFrame(
                frame, self._context.generation, self._context.segment_id, is_preroll=is_preroll
            )
            if self._context is not None
            else StreamingFrame(frame, 0, 0, is_preroll=True)
            if is_preroll and getattr(self._pipeline.asr, "supports_preroll_frames", False)
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
                self._context.start_utterance(continues_turn=self._controller.continues_turn())
            if (
                event.kind == "speech_start"
                and self._turn_audio is not None
                and not (self._turn_audio_open and self._controller.continues_turn())
            ):
                # Lượt mới: bỏ audio của lượt trước đã bị bỏ (từ đệm, quá ngắn, rỗng, bot dứt lời).
                self._turn_audio_open = True
                self._turn_audio[:] = b"".join(self._before_speech)
            if event.kind != "speech":
                logger.debug("main_vad: %s", event.kind)
            await self._controller.on_vad_event(event)
            if event.kind == "speech_start" and self._context is not None:
                self._controller.expect_final(self._context.segment_id)
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
                        noise_evidence=evidence.utterance_noise, stability=stability
                    )
            await self._controller.on_transcript_event(event)
            if self._interruption is not None:
                if await self._interruption.on_partial_transcript(event):
                    self._unconfirmed_barge_in_audio = False
                    self._expect_echo()

    def _expect_echo(self) -> None:
        """ASR đã nghe audio lúc bot nói: chỉ chữ bot phát trong khoảng đó mới có thể vọng vào."""
        self._controller.expect_echo(self._interruption.echo_text(self._replayed_pre_roll_s))


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
