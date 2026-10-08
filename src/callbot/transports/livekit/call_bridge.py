"""CallBridge — nối 1 LiveKit room (1 cuộc gọi web) với Voice Pipeline + Core.

1 instance/call, không share state với call khác. Không import gì từ engine.session
ngoài CallStart/CallerInput/BotAction — orchestrator tự quản state nội bộ qua
SessionManager, CallBridge chỉ là caller của nó, giống transports/http/calls.py.
"""

import asyncio
import json
import logging
import os
import sys
import traceback
import uuid
from contextlib import aclosing
from dataclasses import dataclass
from time import perf_counter
from typing import TYPE_CHECKING, AsyncIterator, Awaitable, Callable, Optional

from callbot.engine import BotAction, CallerInput, CallOrchestrator, CallStart
from callbot.engine.errors import OutboundStartFailed
from callbot.engine.types import Direction
from callbot.tracing import Tracer, null_tracer
from callbot.tracing.pricing import tts_cost
from callbot.transports.input_mapping import caller_input_from_transcript
from callbot.transports.livekit.audio_adapter import (
    livekit_frame_to_segment,
    segment_to_livekit_frame,
)
from speech.asr.pipeline import STTPipeline
from speech.bundle import SpeechSynthesizer
from speech.turn.controller import TurnController
from speech.turn.events import UserTurnCompleted
from speech.turn.interruption import InterruptionController, InterruptionState
from speech.turn.validator import TurnValidator
from speech.types import AudioSegment

if TYPE_CHECKING:
    from livekit import rtc

logger = logging.getLogger(__name__)

_FRAME_DONE = object()
_TURN_DONE = object()
# Giới hạn chờ AudioSource.wait_for_playout() — xem docstring trong _speak() cho lý do.
_PLAYOUT_TIMEOUT_S = 20.0
# Độ dài mỗi frame TTS đưa vào AudioSource — xem docstring _speak().
_PLAYOUT_FRAME_MS = 20
# Nhịp kiểm tra lại khi người dùng đang nói dở (chưa thể tính là im lặng).
_SILENCE_POLL_S = 0.25
# Topic data channel mang lời thoại cho trang web /ui/livekit (hiện transcript để trace).
TRANSCRIPT_TOPIC = "callbot.transcript"


@dataclass(frozen=True)
class _SilenceTimeout:
    """Hẹn giờ im lặng đã hết. `generation` khớp lượt đang chờ; lệch nghĩa là đã có lượt khác
    được xử lý sau khi hẹn giờ bắt đầu — bỏ qua, không gửi lượt im lặng cũ cho core."""

    generation: int
    silence_ms: int


def call_start_from_room(
    room_name: str,
    participant_identity: str,
    *,
    direction: Direction = "inbound",
    caller_number: Optional[str] = None,
    appointment_id: Optional[str] = None,
    call_id: Optional[str] = None,
) -> CallStart:
    """Map LiveKit room/participant -> CallStart. SIP callers use an opaque call ID.

    Demo web không có caller ID/PBX dial-out thật (khác PSTN) — worker.py đọc
    direction/caller_number/appointment_id từ participant attribute (gắn lúc sinh token,
    xem transports/http/livekit_token.py) do người test tự khai để giả lập 2 kịch bản:
    - inbound: cần caller_number khớp hồ sơ, không có appointment_id — thiếu số thì đi
      nhánh NO_PHONE của policy engine (chuyển máy ngay lượt đầu, hành vi ĐÚNG thiết kế
      cho caller không xác định được, không phải bug).
    - outbound: cần appointment_id có sẵn trong clinic-mock, không có caller_number —
      bot chủ động gọi ra để xác nhận/nhắc lịch hẹn đã có."""
    return CallStart(
        call_id=call_id or room_name,
        direction=direction,
        caller_number=caller_number,
        appointment_id=appointment_id,
        locale="vi-VN",
    )


def caller_input_from_turn(turn_number: int, turn: UserTurnCompleted) -> CallerInput:
    """Lượt im lặng (`silence_ms > 0`, hợp đồng core: Phụ lục A) không mang text."""
    if not isinstance(turn, UserTurnCompleted):
        raise TypeError("Core accepts only completed user turns, not raw ASR events")
    return caller_input_from_transcript(
        turn_number,
        turn.text,
        silence_ms=turn.silence_ms,
        confidence=turn.confidence,
    )


class CallBridge:
    """1 instance/room — sở hữu toàn bộ state của 1 cuộc gọi (VAD, ASR stream, turn
    counter). Không class-level/module-level mutable state."""

    def __init__(
        self,
        room: "rtc.Room",
        orchestrator: CallOrchestrator,
        stt_pipeline: STTPipeline,
        tts: SpeechSynthesizer,
        *,
        turn_controller: TurnController,
        interruption_validator: Optional[TurnValidator],
        interruption_min_snr_db: Optional[float],
        sample_rate: int,
        frame_ms: int,
        input_queue_ms: int,
        output_queue_ms: int,
        silence_timeout_ms: int,
        krisp_noise_suppression_enabled: bool,
        direction: Direction = "inbound",
        caller_number: Optional[str] = None,
        appointment_id: Optional[str] = None,
        caller_identity: Optional[str] = None,
        is_sip: bool = False,
        on_close: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> None:
        """Mọi tham số cấu hình (StreamingSpeechBundle, config/livekit.yaml, config/speech.yaml)
        đều bắt buộc — worker.py truyền đủ. Chỉ thông tin của cuộc gọi là tuỳ chọn."""
        self._room = room
        # Individual SIP dispatch room names contain the caller's phone number.
        # Keep that name out of the core session key, traces, logs and debug paths.
        self._call_id = f"sip-{uuid.uuid4().hex}" if is_sip else room.name
        self._orchestrator = orchestrator
        candidate_tracer = getattr(orchestrator, "tracer", None)
        self._tracer = candidate_tracer if isinstance(candidate_tracer, Tracer) else null_tracer()
        self._stt_pipeline = stt_pipeline
        self._tts = tts
        self._sample_rate = sample_rate
        self._direction = direction
        self._caller_number = caller_number
        self._on_close = on_close
        self._appointment_id = appointment_id
        self._turn_number = 0
        self._frame_ms = frame_ms
        self._input_queue_frames = max(1, input_queue_ms // frame_ms)
        self._output_queue_ms = output_queue_ms
        self._frame_queue: "asyncio.Queue[object]" = asyncio.Queue(maxsize=self._input_queue_frames)
        self._turn_queue: "asyncio.Queue[object]" = asyncio.Queue(maxsize=4)
        self._audio_source: Optional["rtc.AudioSource"] = None
        self._tasks: list[asyncio.Task] = []
        self._pipeline_task: Optional[asyncio.Task] = None
        self._pipeline_error: Optional[BaseException] = None
        self._active_speak_task: Optional[asyncio.Task] = None
        self._closing = False
        self._input_done = False
        self._caller_gone = False
        # Chỉ nghe mic của người gọi (participant worker.py đã chờ). None: khoá vào participant
        # đầu tiên có track mic. Trước đây mọi track audio của mọi participant (người thứ hai,
        # track share màn hình) cùng đổ vào MỘT hàng đợi — hai luồng PCM xen kẽ nhau.
        self._caller_identity = caller_identity
        self._pump_task: Optional[asyncio.Task] = None
        # Core đã có luật im lặng (silence_ms > 0, max_silent_turns) nhưng LiveKit chưa từng gửi
        # lượt im lặng: người dùng im thì bot chờ mãi. 0 = tắt.
        self._silence_timeout_ms = silence_timeout_ms
        self._silence_task: Optional[asyncio.Task] = None
        self._silence_generation = 0
        # THỬ NGHIỆM (docs/evidence §8): mặc định false — đo offline cho thấy Krisp VIVA làm
        # WER tệ hơn ở gần mọi điều kiện kể cả audio sạch. Bật tạm để nghe thử qua streaming
        # thật; không phải khuyến nghị bật cho production.
        self._krisp_noise_suppression_enabled = krisp_noise_suppression_enabled
        # CallBridge giữ TurnController để báo bot đang nói/đã dứt lời (StreamingSpeechBundle
        # tạo sẵn theo SpeechSettings).
        self._turn_controller = turn_controller
        # Ngắt lời huỷ cả request TTS lẫn hàng đợi phát qua CallBridge.cancel(). Dùng chung
        # TurnValidator với turn_controller để lọc barge-in giả do nhiễu.
        self._interruption = InterruptionController(
            self, validator=interruption_validator, min_snr_db=interruption_min_snr_db
        )

    async def run(self) -> None:
        """Vòng đời 1 call: mở Core session, subscribe mic, publish TTS track, xử lý
        turn cho đến khi orchestrator báo `ended` hoặc room disconnect."""
        # Đăng ký track_subscribed TRƯỚC bất kỳ await nào khác — browser có thể publish
        # mic gần như ngay khi room.connect() (đã xảy ra trước cả entrypoint này), nên
        # đăng ký muộn (sau start_call/_speak) có thể bỏ lỡ event nếu mic đã subscribe
        # xong trước đó, khiến CallBridge không bao giờ nhận được audio user.
        try:
            self._room.on("track_subscribed", self._on_track_subscribed)
            self._room.on("disconnected", self._on_disconnected)
            self._room.on("participant_disconnected", self._on_participant_disconnected)
            for participant in self._room.remote_participants.values():
                for publication in participant.track_publications.values():
                    if publication.track is not None:
                        self._on_track_subscribed(publication.track, publication, participant)

            call_start = call_start_from_room(
                self._room.name,
                self._room.local_participant.identity,
                direction=self._direction,
                caller_number=self._caller_number,
                appointment_id=self._appointment_id,
                call_id=self._call_id,
            )
            logger.info("call_bridge: start_call call_id=%s", self._call_id)
            try:
                with self._tracer.start_trace(
                    call_id=self._call_id,
                    turn=0,
                    component="TURN",
                    operation="livekit.start_call",
                ) as root:
                    root.enrich(direction=self._direction, mode="livekit")
                    opening: BotAction = await asyncio.to_thread(
                        self._orchestrator.start_call, call_start
                    )
                    await self._publish_tts_track()
                    # Receive audio during the opening; the consumer has its own task context.
                    self._pipeline_task = asyncio.create_task(self._consume_turns())
                    await asyncio.sleep(0)
                    await self._publish_transcript("bot", opening.utterance, action=opening)
                    await self._speak(opening.utterance)
                    root.enrich(
                        state_after=opening.state, ended=opening.ended, outcome=opening.outcome
                    )
            except OutboundStartFailed as exc:
                # Core cố ý không tạo phiên/không phát lời chào khi lịch outbound không
                # dùng được. Báo lỗi qua data channel để web demo không im lặng sau khi
                # đã kết nối room; không biến lỗi nghiệp vụ dự kiến thành job crash.
                logger.warning(
                    "call_bridge: outbound start failed call_id=%s code=%s",
                    self._call_id,
                    exc.code or "UNKNOWN",
                )
                try:
                    await self._room.local_participant.publish_data(
                        json.dumps(
                            {
                                "code": "OUTBOUND_START_FAILED",
                                "message": "Không lấy được lịch hẹn hợp lệ từ Clinic. "
                                "Hãy kiểm tra mã, trạng thái lịch và kết nối Clinic.",
                            },
                            ensure_ascii=False,
                        ),
                        reliable=True,
                        topic="callbot.status",
                    )
                except Exception as publish_error:
                    logger.warning(
                        "call_bridge: không gửi được lỗi outbound tới browser (%s)",
                        type(publish_error).__name__,
                    )
                return

            if opening.ended or self._caller_gone:
                return
            self._start_silence_timer()

            while True:
                item = await self._turn_queue.get()
                if self._caller_gone:
                    return
                if item is _TURN_DONE:
                    if self._pipeline_error is not None:
                        raise self._pipeline_error
                    return
                if isinstance(item, _SilenceTimeout):
                    if item.generation != self._silence_generation:
                        continue
                    logger.info(
                        "call_bridge: im lặng %d ms -> gửi lượt im lặng cho core", item.silence_ms
                    )
                    turn = UserTurnCompleted(text="", silence_ms=item.silence_ms)
                else:
                    turn = item
                self._stop_silence_timer()
                self._turn_number += 1
                logger.info(
                    "call_bridge: turn %d completed confidence=%s",
                    self._turn_number,
                    turn.confidence,
                )
                # DEBUG only (không phải INFO): turn.text có thể chứa PII (tên, ngày
                # sinh) — tách mức log riêng để không rò rỉ ra log production mặc định,
                # nhưng vẫn bật được khi cần chẩn đoán ASR nghe sai gì (bật qua
                # `logging.getLogger("callbot.transports.livekit.call_bridge").setLevel(logging.DEBUG)`).
                logger.debug("call_bridge: turn %d text=%r", self._turn_number, turn.text)
                if not turn.silence_ms:
                    # Lượt im lặng không có lời để hiện; câu hỏi lại của bot đã đủ ngữ cảnh.
                    await self._publish_transcript("caller", turn.text, confidence=turn.confidence)
                with self._tracer.start_trace(
                    call_id=self._call_id,
                    turn=self._turn_number,
                    component="TURN",
                    operation="livekit.call_turn",
                ) as root:
                    root.enrich(direction=self._direction, mode="livekit")
                    if not turn.silence_ms:
                        with self._tracer.span(
                            component="STT", operation="speech.stt.transcribe"
                        ) as stt:
                            stt.enrich(
                                provider=getattr(self._stt_pipeline, "provider_name", None),
                                model=getattr(self._stt_pipeline, "model", None),
                                confidence=turn.confidence,
                                sample_rate_hz=self._sample_rate,
                                input_mode="streaming",
                                transcript_empty=not bool(turn.text.strip()),
                                audio_duration_ms=turn.audio_duration_ms,
                                first_partial_ms=turn.first_partial_ms,
                                final_ms=turn.final_ms,
                                partial_count=turn.partial_count,
                                vad_end_reason=turn.vad_end_reason,
                            )
                    caller = caller_input_from_turn(self._turn_number, turn)
                    if self._caller_gone:
                        return
                    action = await asyncio.to_thread(
                        self._orchestrator.handle_turn, self._call_id, caller
                    )
                    if self._caller_gone:
                        return
                    logger.info(
                        "call_bridge: turn %d action state=%s ended=%s outcome=%s",
                        self._turn_number,
                        action.state,
                        action.ended,
                        action.outcome,
                    )
                    await self._publish_transcript("bot", action.utterance, action=action)
                    await self._speak(action.utterance)
                    root.enrich(
                        state_after=action.state, ended=action.ended, outcome=action.outcome
                    )
                if action.ended or self._caller_gone:
                    return
                self._start_silence_timer()
        finally:
            logger.info(
                "call_bridge: closing dialogue, SIP callback=%s", self._on_close is not None
            )
            # SIP BYE must follow final playout, before closing the incoming media.
            # Waiting for the caller's media to close before sending BYE can leave
            # the handset connected after the dialogue has already ended.
            try:
                if self._on_close is not None:
                    await self._on_close()
            finally:
                await self.aclose()

    def _start_silence_timer(self) -> None:
        self._stop_silence_timer()
        if self._silence_timeout_ms > 0:
            self._silence_task = asyncio.create_task(self._watch_silence(self._silence_generation))

    def _stop_silence_timer(self) -> None:
        """Mọi lượt (thật hoặc im lặng) được lấy ra xử lý đều làm hẹn giờ đang chạy hết hiệu
        lực — kể cả `_SilenceTimeout` đã nằm sẵn trong hàng đợi (lệch generation)."""
        self._silence_generation += 1
        task = self._silence_task
        self._silence_task = None
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()

    async def _watch_silence(self, generation: int) -> None:
        """Chờ tới khi người dùng im đủ `silence_timeout_ms` liên tục (theo VAD, tính từ lúc bot
        dứt lời). Đang nói dở hoặc đang chờ ASR chốt câu thì chưa tính là im lặng."""
        timeout_s = self._silence_timeout_ms / 1000
        while True:
            elapsed = self._turn_controller.silence_elapsed_s()
            if elapsed is not None and elapsed >= timeout_s:
                break
            await asyncio.sleep(_SILENCE_POLL_S if elapsed is None else timeout_s - elapsed)
        if generation == self._silence_generation:
            await self._turn_queue.put(
                _SilenceTimeout(generation=generation, silence_ms=round(elapsed * 1000))
            )

    async def _publish_transcript(
        self,
        role: str,
        text: str,
        *,
        action: Optional[BotAction] = None,
        confidence: Optional[float] = None,
    ) -> None:
        """Gửi một dòng hội thoại qua data channel tới người trong phòng — chính người đang
        gọi, nên họ chỉ thấy lại lời của mình và của bot. Không log text (PII). Gửi lỗi chỉ
        mất dòng hiển thị, không được làm hỏng cuộc gọi."""
        payload: dict[str, object] = {
            "type": "transcript",
            "role": role,
            "turn": self._turn_number,
            "text": text,
        }
        if confidence is not None:
            payload["confidence"] = confidence
        if action is not None:
            payload.update(state=action.state, ended=action.ended, outcome=action.outcome)
        try:
            await self._room.local_participant.publish_data(
                json.dumps(payload, ensure_ascii=False), reliable=True, topic=TRANSCRIPT_TOPIC
            )
        except Exception as exc:
            logger.warning(
                "call_bridge: không gửi được transcript call_id=%s: %s",
                self._call_id,
                type(exc).__name__,
            )

    async def _consume_turns(self) -> None:
        try:
            async for turn in self._stt_pipeline.stream(
                self._frames(),
                turn_controller=self._turn_controller,
                interruption=self._interruption,
            ):
                await self._turn_queue.put(turn)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            self._pipeline_error = exc
            # Chỉ log vị trí frame, không format traceback (message/source có thể chứa PII).
            locations = " -> ".join(
                f"{frame.filename}:{frame.lineno}"
                for frame in traceback.extract_tb(exc.__traceback__)
            )
            logger.error(
                "call_bridge: voice pipeline failed call_id=%s error=%s locations=%s",
                self._call_id,
                type(exc).__name__,
                locations,
            )
        finally:
            await self._put_turn_done()

    def _on_track_subscribed(
        self, track: "rtc.Track", publication: "rtc.RemoteTrackPublication", participant: object
    ) -> None:
        from livekit import rtc

        if self._closing or track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        identity = getattr(participant, "identity", None)
        source = getattr(publication, "source", rtc.TrackSource.SOURCE_UNKNOWN)
        if source not in (rtc.TrackSource.SOURCE_MICROPHONE, rtc.TrackSource.SOURCE_UNKNOWN):
            logger.info("call_bridge: bỏ qua track audio nguồn %s của %s", source, identity)
            return
        if self._caller_identity is None:
            self._caller_identity = identity
        elif identity != self._caller_identity:
            logger.info("call_bridge: bỏ qua track audio của participant khác %s", identity)
            return
        # Người gọi publish lại mic (đổi thiết bị): luồng mới thay luồng cũ, không chạy song song.
        if self._pump_task is not None and not self._pump_task.done():
            self._pump_task.cancel()
        self._pump_task = asyncio.ensure_future(self._pump_track(track))
        self._tasks.append(self._pump_task)

    def _on_disconnected(self, *_args: object) -> None:
        self._caller_gone = True
        self._stop_silence_timer()
        self._signal_input_done()
        task = self._active_speak_task
        if task is not None and not task.done():
            task.cancel()

    def _on_participant_disconnected(self, participant: object) -> None:
        if getattr(participant, "identity", None) == self._caller_identity:
            self._stop_silence_timer()
            self._on_disconnected()

    def _krisp_processor(self) -> object | None:
        """THỬ NGHIỆM (docs/evidence §8) — None nếu tắt hoặc package chưa cài. Processor tạo
        mới mỗi lần pump (không tái dùng qua re-publish): auto_close mặc định của AudioStream
        đóng nó khi stream đóng, tái dùng instance đã đóng sẽ lỗi."""
        if not self._krisp_noise_suppression_enabled:
            return None
        try:
            from livekit.plugins import krisp
        except ImportError:
            logger.warning(
                "call_bridge: krisp_noise_suppression_enabled=true nhưng "
                "livekit-plugins-krisp chưa cài — bỏ qua, chạy không lọc"
            )
            return None
        return krisp.KrispVivaFilterFrameProcessor(
            mode=krisp.viva_filter.VivaMode.VOICE_ISOLATION, noise_suppression_level=90.0
        )

    async def _pump_track(self, track: "rtc.Track") -> None:
        from livekit import rtc

        stream = rtc.AudioStream.from_track(
            track=track,
            sample_rate=self._sample_rate,
            num_channels=1,
            frame_size_ms=self._frame_ms,
            capacity=self._input_queue_frames,
            noise_cancellation=self._krisp_processor(),
        )
        # LIVEKIT_DEBUG_DUMP_AUDIO=1: ghi PCM thật (đã qua livekit_frame_to_segment, đúng
        # đường dữ liệu đưa vào ASR) ra 1 file wav/call trong temp/audio/ — cách duy nhất
        # để xác nhận chắc chắn ASR hallucinate do audio bị méo (sample rate/capture sai)
        # hay do model thật sự nghe nhầm giọng nói rõ ràng. Tắt mặc định: PII + I/O per-frame
        # không nên bật ở production.
        dump_writer = (
            self._open_debug_dump() if os.environ.get("LIVEKIT_DEBUG_DUMP_AUDIO") else None
        )
        try:
            async for event in stream:
                segment = livekit_frame_to_segment(event.frame, target_rate=self._sample_rate)
                if segment.pcm:
                    if dump_writer is not None:
                        dump_writer.writeframes(segment.pcm)
                    await self._frame_queue.put(segment.pcm)
        finally:
            if dump_writer is not None:
                dump_writer.close()
            await stream.aclose()

    def _open_debug_dump(self):
        import wave

        os.makedirs("temp/audio", exist_ok=True)
        path = f"temp/audio/livekit_debug_{self._call_id}.wav"
        writer = wave.open(path, "wb")
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(self._sample_rate)
        logger.warning("call_bridge: LIVEKIT_DEBUG_DUMP_AUDIO bật — ghi PCM vào %s", path)
        return writer

    async def _frames(self) -> AsyncIterator[bytes]:
        while True:
            item = await self._frame_queue.get()
            if item is _FRAME_DONE:
                return
            yield item  # type: ignore[misc]

    async def _publish_tts_track(self) -> None:
        from livekit import rtc

        # TTS mono 24kHz (OpenAI PCM) — AudioSource cần biết trước sample_rate/channels
        # cố định của track publish; nếu provider đổi rate giữa các câu, phải resample
        # trước capture_frame (segment_to_livekit_frame không tự resample).
        self._audio_source = rtc.AudioSource(
            sample_rate=self._tts.stream_sample_rate,
            num_channels=1,
            queue_size_ms=self._output_queue_ms,
        )
        track = rtc.LocalAudioTrack.create_audio_track("bot-voice", self._audio_source)
        options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        await self._room.local_participant.publish_track(track, options)

    async def _speak(self, text: str) -> None:
        """Publish TTS theo từng frame `_PLAYOUT_FRAME_MS`, kiểm tra barge-in trước MỖI frame
        và dừng ngay (không chỉ ngừng gọi API mà vẫn phát nốt audio đã có).

        Không bao giờ đưa cả chunk TTS vào một lần `capture_frame`: provider không stream
        (Vbee) trả nguyên câu thành MỘT chunk. SDK tự chia frame lớn và đẩy dần trong task
        native — huỷ lần await phía Python không dừng được task đó, nên sau barge-in bot vẫn
        nói tiếp phần còn lại, và câu kế tiếp bị native từ chối
        ("InvalidState - failed to capture frame"), sập job. Frame nhỏ thì phần còn treo sau
        khi huỷ tối đa một frame, xong ngay khi `clear_queue()` xả hàng đợi."""
        if self._caller_gone or not text.strip() or self._audio_source is None:
            return

        self._turn_controller.on_bot_speaking_changed(True)
        self._interruption.on_bot_started_speaking(text)
        self._active_speak_task = asyncio.current_task()
        sample_rate = self._tts.stream_sample_rate
        frame_bytes = sample_rate * _PLAYOUT_FRAME_MS // 1000 * 2
        # Chunk TTS cắt theo byte HTTP tuỳ ý; gom lại rồi cắt đúng ranh giới frame PCM16.
        pending = bytearray()
        interrupted = False
        total_bytes = 0
        started = perf_counter()
        first_audio_ms = None
        scope = self._tracer.span(component="TTS", operation="speech.tts.synthesize")
        tts_span = scope.__enter__()
        tts_span.enrich(
            provider_requested=getattr(self._tts, "name", None),
            provider=getattr(self._tts, "name", None),
            model=getattr(self._tts, "model", None),
            character_count=len(text),
            audio_format="pcm16",
            sample_rate_hz=sample_rate,
        )
        try:
            # aclosing: thoát vòng lặp (barge-in) thì đóng stream TTS ngay tại đây. Để GC đóng
            # muộn thì phần dọn dẹp của câu cũ có thể chạy khi câu mới đã phát.
            async with aclosing(self._tts.synthesize_stream(text)) as chunks:
                async for chunk in chunks:
                    if chunk and first_audio_ms is None:
                        first_audio_ms = (perf_counter() - started) * 1000
                    total_bytes += len(chunk)
                    if self._is_interrupted():
                        break
                    pending.extend(chunk)
                    while len(pending) >= frame_bytes and not self._is_interrupted():
                        await self._capture(bytes(pending[:frame_bytes]), sample_rate)
                        del pending[:frame_bytes]
                    if self._is_interrupted():
                        break
            # Đuôi câu ngắn hơn một frame; bỏ byte lẻ vì rtc.AudioFrame cần PCM16 trọn mẫu.
            tail = len(pending) - len(pending) % 2
            if tail and not self._is_interrupted():
                await self._capture(bytes(pending[:tail]), sample_rate)
            interrupted = self._is_interrupted()
            if interrupted:
                # Chỉ dừng đẩy chunk MỚI là chưa đủ — chunk đã capture nhưng chưa phát
                # ra loa vẫn còn trong hàng đợi playout của AudioSource, phải xoá luôn
                # để barge-in không bị trễ nghe được.
                self._audio_source.clear_queue()
            else:
                wait_for_playout = getattr(self._audio_source, "wait_for_playout", None)
                if wait_for_playout is not None:
                    try:
                        await asyncio.wait_for(wait_for_playout(), timeout=_PLAYOUT_TIMEOUT_S)
                    except TimeoutError:
                        # SDK _join_fut tracks local AudioSource queue time, not
                        # acknowledgement of client playback. Bound that local wait;
                        # SIP hangup adds a separate remote-media grace period.
                        logger.warning(
                            "call_bridge: wait_for_playout timeout sau %.0fs, tiếp tục turn tiếp theo",
                            _PLAYOUT_TIMEOUT_S,
                        )
        except asyncio.CancelledError:
            interrupted = self._is_interrupted() or self._caller_gone
            if not interrupted:
                raise
        finally:
            interrupted = interrupted or self._is_interrupted()
            actual = getattr(self._tts, "last_stream_result", None)
            actual_provider = getattr(actual, "provider_actual", None) or getattr(
                self._tts, "name", None
            )
            voice = getattr(actual, "voice", None)
            # Provider lỗi giữa câu: gateway dừng êm (không đọc lại) và chỉ ghi mã lỗi — người
            # gọi nghe thiếu câu, nên span phải là ERROR + truncated, không tính tiền (§4.1.3).
            stream_error = None if interrupted else getattr(actual, "error_code", None)
            failed = sys.exc_info()[0] is not None or stream_error is not None
            tts_span.enrich(
                provider_actual=actual_provider,
                voice=voice,
                fallback_used=getattr(actual, "fallback_used", False),
                ttfa_ms=getattr(actual, "ttfa_ms", None) or first_audio_ms,
                latency_ms=(perf_counter() - started) * 1000,
                audio_duration_ms=total_bytes / (2 * sample_rate) * 1000,
                bytes=total_bytes,
                interrupted=interrupted,
                truncated=interrupted or stream_error is not None,
                barge_in=interrupted,
                result="ERROR" if failed else "CANCELLED" if interrupted else "OK",
            )
            if stream_error is not None:
                tts_span.enrich(provider_error_code=stream_error)
                if stream_error == "timeout":
                    tts_span.set_error_code("TIMEOUT", "TTS_TIMEOUT")
                else:
                    tts_span.set_error_code("PROVIDER", "TTS_PROVIDER_ERROR")
            if not interrupted and not failed:
                cost = tts_cost(actual_provider, voice, len(text))
                if cost is not None:
                    tts_span.enrich(cost_usd=cost)
            scope.__exit__(*sys.exc_info())
            self._turn_controller.on_bot_speaking_changed(False, preserve_candidate=interrupted)
            self._interruption.on_bot_stopped_speaking()
            self._active_speak_task = None

    def _is_interrupted(self) -> bool:
        return self._caller_gone or self._interruption.state == InterruptionState.INTERRUPTED

    async def _capture(self, pcm: bytes, sample_rate: int) -> None:
        segment = AudioSegment(pcm=pcm, sample_rate=sample_rate)
        await self._audio_source.capture_frame(segment_to_livekit_frame(segment))

    async def cancel(self) -> None:
        """Interruption target: dừng network TTS và audio đã queue ngay lập tức."""
        await self._tts.cancel()
        if self._audio_source is not None:
            self._audio_source.clear_queue()
        task = self._active_speak_task
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()

    def _signal_input_done(self) -> None:
        if self._input_done:
            return
        self._input_done = True
        try:
            self._frame_queue.put_nowait(_FRAME_DONE)
        except asyncio.QueueFull:
            # Disconnect phải thắng audio backlog: bỏ frame cũ nhất để sentinel luôn vào được.
            self._frame_queue.get_nowait()
            self._frame_queue.put_nowait(_FRAME_DONE)

    async def _put_turn_done(self) -> None:
        if self._pipeline_error is None and not self._closing:
            # EOF bình thường phải đứng SAU mọi lượt đã chốt, không bỏ lượt khi queue đầy.
            await self._turn_queue.put(_TURN_DONE)
            return
        try:
            self._turn_queue.put_nowait(_TURN_DONE)
        except asyncio.QueueFull:
            # Pipeline đã kết thúc/lỗi: sentinel quan trọng hơn turn backlog chưa xử lý.
            self._turn_queue.get_nowait()
            self._turn_queue.put_nowait(_TURN_DONE)

    async def aclose(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._stop_silence_timer()
        self._signal_input_done()
        if self._pipeline_task is not None and self._pipeline_task is not asyncio.current_task():
            self._pipeline_task.cancel()
        for task in self._tasks:
            task.cancel()
        pending = list(self._tasks)
        if self._pipeline_task is not None and self._pipeline_task is not asyncio.current_task():
            pending.append(self._pipeline_task)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if self._audio_source is not None:
            await self._audio_source.aclose()
