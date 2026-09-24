"""CallBridge — nối 1 LiveKit room (1 cuộc gọi web) với Voice Pipeline + Core.

1 instance/call, không share state với call khác. Không import gì từ engine.session
ngoài CallStart/CallerInput/BotAction — orchestrator tự quản state nội bộ qua
SessionManager, CallBridge chỉ là caller của nó, giống transports/http/calls.py.
"""

import asyncio
import logging
import os
from typing import TYPE_CHECKING, AsyncIterator, Optional

from callbot.engine import BotAction, CallerInput, CallOrchestrator, CallStart
from callbot.engine.types import Direction
from callbot.transports.livekit.audio_adapter import (
    livekit_frame_to_segment,
    segment_to_livekit_frame,
)
from speech.asr.evidence import TranscriptEvidenceTracker
from speech.asr.pipeline import STTPipeline
from speech.asr.vad.base import FrameClassifier
from speech.audio.noise_tracker import NoiseTracker
from speech.bundle import SpeechSynthesizer
from speech.turn.controller import TurnController
from speech.turn.events import UserTurnCompleted
from speech.turn.interruption import InterruptionController, InterruptionState
from speech.turn.validator import TurnValidator
from speech.types import NARROWBAND_RATE, AudioSegment

if TYPE_CHECKING:
    from livekit import rtc

logger = logging.getLogger(__name__)

_FRAME_DONE = object()
_TURN_DONE = object()
# Giới hạn chờ AudioSource.wait_for_playout() — xem docstring trong _speak() cho lý do.
_PLAYOUT_TIMEOUT_S = 20.0


def call_start_from_room(
    room_name: str,
    participant_identity: str,
    *,
    direction: Direction = "inbound",
    caller_number: Optional[str] = None,
    appointment_id: Optional[str] = None,
) -> CallStart:
    """Map LiveKit room/participant -> CallStart (room name đã unique per call, dùng
    thẳng làm call_id — không cần map qua UUID riêng).

    Demo web không có caller ID/PBX dial-out thật (khác PSTN) — worker.py đọc
    direction/caller_number/appointment_id từ participant attribute (gắn lúc sinh token,
    xem transports/http/livekit_token.py) do người test tự khai để giả lập 2 kịch bản:
    - inbound: cần caller_number khớp hồ sơ, không có appointment_id — thiếu số thì đi
      nhánh NO_PHONE của policy engine (chuyển máy ngay lượt đầu, hành vi ĐÚNG thiết kế
      cho caller không xác định được, không phải bug).
    - outbound: cần appointment_id có sẵn trong clinic-mock, không có caller_number —
      bot chủ động gọi ra để xác nhận/nhắc lịch hẹn đã có."""
    return CallStart(
        call_id=room_name,
        direction=direction,
        caller_number=caller_number,
        appointment_id=appointment_id,
        locale="vi-VN",
    )


def caller_input_from_turn(turn_number: int, turn: UserTurnCompleted) -> CallerInput:
    return CallerInput(
        turn=turn_number,
        text=turn.text,
        silence_ms=0,
        audio_url=None,
        asr_confidence=turn.confidence,
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
        sample_rate: int = NARROWBAND_RATE,
        direction: Direction = "inbound",
        caller_number: Optional[str] = None,
        appointment_id: Optional[str] = None,
        turn_controller: Optional[TurnController] = None,
        evidence_tracker: Optional[TranscriptEvidenceTracker] = None,
        noise_tracker: Optional[NoiseTracker] = None,
        noise_classifier: Optional[FrameClassifier] = None,
        interruption_validator: Optional[TurnValidator] = None,
        interruption_min_snr_db: Optional[float] = None,
        frame_ms: int = 30,
        input_queue_ms: int = 1_500,
        output_queue_ms: int = 200,
    ) -> None:
        self._room = room
        self._orchestrator = orchestrator
        self._stt_pipeline = stt_pipeline
        self._tts = tts
        self._sample_rate = sample_rate
        self._direction = direction
        self._caller_number = caller_number
        self._appointment_id = appointment_id
        self._turn_number = 0
        # Turn Validator (xem StreamingSpeechBundle) — None khi turn_validator_enabled=False,
        # truyền thẳng xuống stt_pipeline.stream() mỗi lần _consume_turns() gọi.
        self._evidence_tracker = evidence_tracker
        self._noise_tracker = noise_tracker
        self._noise_classifier = noise_classifier
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
        # 1 TurnController + 1 InterruptionController riêng cho call này — không tạo
        # qua default của STTPipeline.stream() để CallBridge điều khiển được
        # bot-speaking state của TurnController khi barge-in xảy ra. worker.py truyền
        # instance đã cấu hình từ SpeechSettings (turn_min_speech_ms, ...); nếu không
        # truyền thì dùng default của TurnController (giữ tương thích test cũ).
        self._turn_controller = turn_controller or TurnController()
        # Interruption hủy cả request TTS lẫn playout queue qua CallBridge.cancel().
        # `interruption_validator` dùng CHUNG TurnValidator với turn_controller (nếu
        # turn_validator_enabled) — xem docstring InterruptionController.__init__ #3 và
        # module speech/turn/interruption.py: barge-in false-positive từ noise trong lúc
        # bot nói KHÔNG được Speech Admission chặn (audio phải tới ASR thật để tự confirm),
        # nên cần lớp phòng thủ riêng ở đây.
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
            )
            logger.info("call_bridge: start_call room=%s", self._room.name)
            opening: BotAction = await asyncio.to_thread(self._orchestrator.start_call, call_start)

            await self._publish_tts_track()
            # Bắt đầu VAD/ASR trước câu chào: barge-in hoạt động ngay từ lượt 0 và mic
            # audio không bị tồn trong queue rồi decode nhầm sau khi bot nói xong.
            self._pipeline_task = asyncio.create_task(self._consume_turns())
            await asyncio.sleep(0)

            await self._speak(opening.utterance)
            if opening.ended:
                return

            while True:
                item = await self._turn_queue.get()
                if item is _TURN_DONE:
                    if self._pipeline_error is not None:
                        raise self._pipeline_error
                    return
                turn = item
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
                caller = caller_input_from_turn(self._turn_number, turn)
                action = await asyncio.to_thread(
                    self._orchestrator.handle_turn, self._room.name, caller
                )
                logger.info(
                    "call_bridge: turn %d action state=%s ended=%s outcome=%s",
                    self._turn_number,
                    action.state,
                    action.ended,
                    action.outcome,
                )
                await self._speak(action.utterance)
                if action.ended:
                    return
        finally:
            await self.aclose()

    async def _consume_turns(self) -> None:
        try:
            async for turn in self._stt_pipeline.stream(
                self._frames(),
                turn_controller=self._turn_controller,
                interruption=self._interruption,
                evidence_tracker=self._evidence_tracker,
                noise_tracker=self._noise_tracker,
                noise_classifier=self._noise_classifier,
            ):
                await self._turn_queue.put(turn)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            self._pipeline_error = exc
            logger.exception("call_bridge: voice pipeline failed room=%s", self._room.name)
        finally:
            await self._put_turn_done()

    def _on_track_subscribed(
        self, track: "rtc.Track", publication: "rtc.RemoteTrackPublication", participant: object
    ) -> None:
        from livekit import rtc

        if self._closing or track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        self._tasks.append(asyncio.ensure_future(self._pump_track(track)))

    def _on_disconnected(self, *_args: object) -> None:
        self._signal_input_done()
        task = self._active_speak_task
        if task is not None and not task.done():
            task.cancel()

    async def _pump_track(self, track: "rtc.Track") -> None:
        from livekit import rtc

        stream = rtc.AudioStream.from_track(
            track=track,
            sample_rate=self._sample_rate,
            num_channels=1,
            frame_size_ms=self._frame_ms,
            capacity=self._input_queue_frames,
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
        path = f"temp/audio/livekit_debug_{self._room.name}.wav"
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
        """Publish TTS streaming từng chunk thay vì chờ đủ câu. Interruption có thể
        cancel() giữa chừng — kiểm tra cờ trước MỖI chunk và dừng publish ngay (không
        chỉ ngừng gọi API mà vẫn phát nốt chunk đã có)."""
        if not text.strip() or self._audio_source is None:
            return

        self._turn_controller.on_bot_speaking_changed(True)
        self._interruption.on_bot_started_speaking(text)
        self._active_speak_task = asyncio.current_task()
        # rtc.AudioFrame đòi len(data) chẵn (PCM16 = 2 byte/sample) — chunk từ
        # synthesize_stream() cắt theo byte HTTP tuỳ ý, không đảm bảo ranh giới sample;
        # giữ lại byte lẻ cuối chunk cho lần capture_frame kế tiếp thay vì cắt bỏ (mất
        # audio) hay publish frame không hợp lệ (SDK raise ValueError, sập cả job).
        pending = bytearray()
        interrupted = False
        try:
            async for chunk in self._tts.synthesize_stream(text):
                if self._interruption.state == InterruptionState.INTERRUPTED:
                    break
                pending.extend(chunk)
                usable_len = len(pending) - (len(pending) % 2)
                if usable_len == 0:
                    continue
                pcm, pending = bytes(pending[:usable_len]), pending[usable_len:]
                segment = AudioSegment(pcm=pcm, sample_rate=self._tts.stream_sample_rate)
                await self._audio_source.capture_frame(segment_to_livekit_frame(segment))
            interrupted = self._interruption.state == InterruptionState.INTERRUPTED
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
                        # wait_for_playout() chờ track TTS được phía client thực sự phát
                        # hết (_join_fut nội bộ của AudioSource) — nếu track không bao
                        # giờ được browser subscribe/consume (mất kết nối, tab đóng đột
                        # ngột, lỗi network), future đó không bao giờ resolve và cuộc gọi
                        # bị khoá vô thời hạn (bug thật đã gặp: 56s im lặng rồi room mới
                        # tự ngắt). Timeout ở đây không phải để "đúng" mọi trường hợp —
                        # chỉ đảm bảo CallBridge luôn tự giải phóng, không bao giờ treo
                        # cứng chờ 1 sự kiện WebRTC có thể không bao giờ tới.
                        logger.warning(
                            "call_bridge: wait_for_playout timeout sau %.0fs, tiếp tục turn tiếp theo",
                            _PLAYOUT_TIMEOUT_S,
                        )
        except asyncio.CancelledError:
            interrupted = self._interruption.state == InterruptionState.INTERRUPTED
            if not interrupted:
                raise
        finally:
            interrupted = interrupted or self._interruption.state == InterruptionState.INTERRUPTED
            self._turn_controller.on_bot_speaking_changed(False, preserve_candidate=interrupted)
            self._interruption.on_bot_stopped_speaking()
            self._active_speak_task = None

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
