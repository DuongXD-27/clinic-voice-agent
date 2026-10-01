"""Realtime STT pipeline: Audio Input (PCM 8 kHz băng hẹp) -> VAD -> ASR -> Streaming Transcript."""

import asyncio
import logging
from collections import deque
from collections.abc import Mapping
from typing import AsyncIterator, Callable, Optional

from speech.asr.evidence import TranscriptEvidenceTracker
from speech.asr.recognizer import Recognizer
from speech.asr.vad.async_stream import AsyncStreamingVAD
from speech.asr.vad.base import FrameClassifier
from speech.asr.vad.shared import SharedSpeechDetector
from speech.asr.vad.streaming import StreamingVAD, split_frames
from speech.audio.codec import to_sample_rate
from speech.audio.loader import load_from_url
from speech.audio.noise_tracker import NoiseTracker, UtteranceEvidenceTracker
from speech.turn.controller import TurnController
from speech.turn.events import UserTurnCompleted
from speech.turn.interruption import InterruptionController, InterruptionState
from speech.types import NARROWBAND_RATE, AsrSegmentEnd, AudioSegment, Transcript

_QUEUE_DONE = object()
# ASR tồn quá mức này (ms audio chưa decode) thì log cảnh báo; hết cảnh báo khi còn một nửa.
_ASR_LAG_WARN_MS = 1_000.0

logger = logging.getLogger(__name__)


class STTPipeline:
    def __init__(
        self,
        asr: Recognizer,
        vad: StreamingVAD,
        sample_rate: int = NARROWBAND_RATE,
        async_vad: Optional[AsyncStreamingVAD] = None,
        queue_max_frames: int = 50,
        asr_queue_max_frames: Optional[int] = None,
        barge_in_preroll_frames: int = 17,
        asr_stream_options: Optional[Mapping[str, object]] = None,
        speech_detector: Optional[SharedSpeechDetector] = None,
    ) -> None:
        self._asr = asr
        self._vad = vad
        self._sample_rate = sample_rate
        # Cùng thuật toán với `vad` (chỉ khác sync/async) — inject riêng để không đọc
        # attribute nội bộ của StreamingVAD; mặc định dùng classifier năng lượng nếu
        # caller không truyền, giữ hành vi hợp lý ngay cả khi chỉ cấu hình `vad`.
        self._async_vad = async_vad or _default_async_vad()
        if queue_max_frames <= 0:
            raise ValueError("queue_max_frames phải lớn hơn 0")
        if barge_in_preroll_frames <= 0:
            raise ValueError("barge_in_preroll_frames phải lớn hơn 0")
        self._queue_max_frames = queue_max_frames
        # Hàng đợi ASR tách khỏi hàng đợi VAD và rộng hơn nhiều (mặc định 20x ≈ 30 s ở 30 ms):
        # decode chậm không được chặn _fanout, nếu không VAD/barge-in/evidence đứng theo ASR
        # (log 24/09: decode 1,89 s nhưng cả pipeline trễ 4,38 s). Không bỏ frame lời nói —
        # chỉ khi ASR tồn quá trần này thì _fanout mới chờ (backpressure như cũ).
        self._asr_queue_max_frames = asr_queue_max_frames or queue_max_frames * 20
        self._barge_in_preroll_frames = barge_in_preroll_frames
        self._asr_stream_options = dict(asr_stream_options or {})
        # Bộ phân loại dùng chung (speech/asr/vad/shared.py): _fanout phân loại MỖI frame một lần
        # theo thứ tự tới; VAD, ASR, evidence đọc lại qua view() của nó.
        self._speech_detector = speech_detector
        # Speech Admission (lọc frame trước ASR theo SNR) đã gỡ 28/09: đo 25/09 và 28/09
        # (eval/noise-bench) tắt nó tốt hơn hoặc bằng ở gần mọi điều kiện, production vốn tắt,
        # và nó là một phía của bug câu kẹt trong ASR 26/09. Mọi frame (bot không nói) đi thẳng
        # vào ASR đúng một lần, đúng thứ tự; âm tiết đầu câu VAD nhận muộn đã được
        # ZipFormerASR.stream() giữ bằng pre-speech riêng.

    def transcribe_turn(
        self, text: Optional[str], audio_url: Optional[str], silence_ms: int
    ) -> Transcript:
        """Một lượt của harness (§4.1): text mode, audio mode, hoặc im lặng."""
        if silence_ms > 0:
            return Transcript(is_silence=True)
        if text is not None:
            return Transcript(text=text.strip(), is_silence=not text.strip())
        if audio_url:
            return self.transcribe_segment(load_from_url(audio_url, self._sample_rate))
        return Transcript(is_silence=True)

    def transcribe_segment(self, segment: AudioSegment) -> Transcript:
        segment = to_sample_rate(segment, self._sample_rate)
        has_speech = any(
            event.kind == "speech"
            for event in self._vad.process(split_frames(segment.pcm, segment.sample_rate))
        )
        # Không có tiếng nói thì bỏ qua ASR — giảm cost per session (§5)
        if not has_speech:
            return Transcript(is_silence=True)
        return self._asr.transcribe(segment)

    async def stream(
        self,
        frames: AsyncIterator[bytes],
        turn_controller: Optional[TurnController] = None,
        interruption: Optional[InterruptionController] = None,
        evidence_tracker: Optional[TranscriptEvidenceTracker] = None,
        noise_tracker: Optional[NoiseTracker] = None,
        noise_classifier: Optional[FrameClassifier] = None,
        asr_hotwords: Optional[Callable[[], Optional[str]]] = None,
    ) -> AsyncIterator[UserTurnCompleted]:
        """VAD và ASR chạy THẬT SỰ song song trên cùng nguồn frame, hợp nhất event vào
        TurnController để emit UserTurnCompleted — đây là turn-taking thật (không phải
        raw transcript stream), dùng cho đường LiveKit (transports/livekit/call_bridge.py).

        `frames` là PCM ở `self._sample_rate` (narrowband mặc định), liên tục suốt cuộc gọi.
        `interruption` (tuỳ chọn) cũng nhận CÙNG VAD/ASR event — input pipeline không bị
        tạm dừng khi bot nói, TurnController và InterruptionController chỉ khác nhau ở
        quyết định cuối (chốt turn vs. xác nhận ngắt lời), không khác luồng dữ liệu đầu vào.

        `asr_hotwords` (tuỳ chọn): hàm trả cụm từ ưu tiên cho lần decode final của ASR, theo
        câu bot vừa hỏi (xem ZipFormerASR.stream). Chỉ truyền xuống ASR khi có.

        `evidence_tracker`/`noise_tracker` (tuỳ chọn): nếu `turn_controller` có `validator`
        cấu hình, cả 2 tracker này PHẢI được truyền để nó có dữ liệu — `noise_classifier`
        bắt buộc đi kèm `noise_tracker`. Evidence được tính trên MỌI frame (kể cả khi bot
        đang nói) và đẩy vào `controller.on_evidence_updated()` mỗi khi có TranscriptEvent
        mới, để `TurnValidator.evaluate()` đọc được giá trị mới nhất lúc `_try_emit()` chạy.
        """
        if noise_tracker is not None and noise_classifier is None:
            raise ValueError("noise_classifier bắt buộc khi truyền noise_tracker")
        controller = turn_controller or TurnController()
        vad_queue: "asyncio.Queue[object]" = asyncio.Queue(maxsize=self._queue_max_frames)
        asr_queue: "asyncio.Queue[object]" = asyncio.Queue(maxsize=self._asr_queue_max_frames)
        # True khi ASR đang chờ frame mới (không decode, không còn gì tồn) — TurnController hỏi
        # trước khi chốt câu bằng partial: ASR còn tồn audio của câu thì final sắp tới.
        asr_idle = True
        asr_lag_warned = False
        controller.set_asr_pending_probe(lambda: not asr_idle or not asr_queue.empty())
        pre_roll: deque[bytes] = deque(maxlen=self._barge_in_preroll_frames)
        was_candidate = False
        latest_noise_evidence = None
        # TurnValidator đọc SNR của CẢ câu vừa nói, không phải frame mới nhất (luôn là im
        # lặng lúc ASR final tới) — xem UtteranceEvidenceTracker. InterruptionController vẫn
        # nhận evidence theo frame như trước.
        utterance_tracker = UtteranceEvidenceTracker() if noise_tracker is not None else None
        latest_utterance_evidence = None
        # ASR tự chốt câu bằng khoảng lặng trong các frame NÓ nhận; mỗi khi _fanout ngừng
        # đưa frame, phải báo tường minh để câu dở không nằm lại trong buffer ASR (xem
        # docstring AsrSegmentEnd). True = đã gửi frame từ lần báo gần nhất.
        asr_segment_open = False

        async def _send_to_asr(frame: bytes) -> None:
            nonlocal asr_segment_open, asr_lag_warned
            await asr_queue.put(frame)
            asr_segment_open = True
            lag_ms = asr_queue.qsize() * len(frame) / 2 / self._sample_rate * 1000
            if lag_ms >= _ASR_LAG_WARN_MS and not asr_lag_warned:
                logger.warning("stt_pipeline: ASR tồn %.0f ms audio chưa decode", lag_ms)
                asr_lag_warned = True
            elif lag_ms < _ASR_LAG_WARN_MS / 2 and asr_lag_warned:
                logger.info("stt_pipeline: ASR đã bắt kịp (tồn %.0f ms)", lag_ms)
                asr_lag_warned = False

        async def _asr_frames() -> AsyncIterator[object]:
            nonlocal asr_idle
            while True:
                asr_idle = True
                item = await asr_queue.get()
                asr_idle = False
                if item is _QUEUE_DONE:
                    return
                yield item

        async def _end_asr_segment(kind: AsrSegmentEnd) -> None:
            nonlocal asr_segment_open
            if asr_segment_open:
                await asr_queue.put(kind)
                asr_segment_open = False

        async def _fanout() -> None:
            nonlocal was_candidate, latest_noise_evidence, latest_utterance_evidence
            try:
                async for frame in frames:
                    if self._speech_detector is not None:
                        self._speech_detector.classify(frame)
                    await vad_queue.put(frame)
                    if noise_tracker is not None:
                        is_speech_for_evidence = noise_classifier.is_speech(frame)
                        latest_noise_evidence = noise_tracker.observe(frame, is_speech_for_evidence)
                        latest_utterance_evidence = utterance_tracker.observe(
                            latest_noise_evidence, is_speech_for_evidence
                        )
                    if controller.is_bot_speaking:
                        # Nhường lịch cho VAD drain để nó có thể xác nhận
                        # INTERRUPTION_CANDIDATE từ chính frame vừa enqueue trước khi
                        # fanout quyết định frame này đi đâu.
                        await asyncio.sleep(0)
                        is_candidate = (
                            interruption is not None
                            and interruption.state == InterruptionState.INTERRUPTION_CANDIDATE
                        )
                        if is_candidate:
                            # Đã nghi ngờ user đang nói (VAD speech_start giữa lúc bot
                            # nói) — cho ASR nghe THẬT ngay từ đây, không chờ tới khi
                            # "chắc chắn" mới confirm: ASR cần audio thật để tự nó xác
                            # nhận qua on_partial_transcript, nếu không sẽ deadlock (ASR
                            # không có gì để decode -> không bao giờ confirm được, kể cả
                            # khi user nói rõ ràng đủ lâu). Replay 1 lần phần pre-roll đã
                            # tích luỹ TRƯỚC lúc thành candidate, rồi đẩy thẳng frame hiện
                            # tại — an toàn vì is_bot_speaking vẫn chặn TurnController
                            # chốt turn thật, audio này chỉ phục vụ việc CONFIRM barge-in.
                            if not was_candidate:
                                # Phần còn trong ASR là audio TRƯỚC khi bot nói, không
                                # thuộc lần ngắt lời này.
                                await _end_asr_segment(AsrSegmentEnd.DISCARD)
                                for buffered in pre_roll:
                                    await _send_to_asr(buffered)
                                pre_roll.clear()
                                was_candidate = True
                            await _send_to_asr(frame)
                        else:
                            # Chưa có dấu hiệu gì (hoặc candidate đã bị bác bỏ) — giữ
                            # echo tiềm năng trong pre-roll có giới hạn, không đưa vào
                            # ASR để không tốn compute decode noise/echo thuần tuý.
                            was_candidate = False
                            pre_roll.append(frame)
                            # Bot vừa bắt đầu nói, hoặc candidate bị bác: TurnController
                            # cũng bỏ đoạn này khi bot dứt lời. Không bỏ lúc INTERRUPTED —
                            # đó là câu ngắt lời đã xác nhận, được giữ để chốt thành turn.
                            # Bug thật: bot nói đè giữa câu, "ANH SINH" còn lại trong ASR
                            # bị ghép vào câu sau thành "ANH SINH ANH SINH NGÀY ...".
                            if (
                                interruption is None
                                or interruption.state != InterruptionState.INTERRUPTED
                            ):
                                await _end_asr_segment(AsrSegmentEnd.DISCARD)
                        continue

                    pre_roll.clear()
                    was_candidate = False
                    await _send_to_asr(frame)
            finally:
                # During cancellation the consumers are stopping too. Waiting to put
                # sentinels into a full queue would deadlock error cleanup.
                task = asyncio.current_task()
                if task is None or not task.cancelling():
                    await vad_queue.put(_QUEUE_DONE)
                    await asr_queue.put(_QUEUE_DONE)

        async def _drain_vad() -> None:
            async for event in self._async_vad.process(_dequeue(vad_queue)):
                if event.kind in ("speech_start", "speech_end"):
                    # DEBUG only: chẩn đoán VAD chính có "kẹt" ở in_speech=True kéo dài
                    # bất thường hay không (VAD có bao giờ tự phát speech_end không).
                    logger.debug("main_vad: %s", event.kind)
                await controller.on_vad_event(event)
                if interruption is not None:
                    if event.kind == "speech_start":
                        await interruption.on_speech_started(event)
                    elif event.kind == "speech_end":
                        await interruption.on_speech_ended_without_confirmation()
                    # event.kind == "speech" (giữa chừng): không còn hành động riêng —
                    # xác nhận barge-in chỉ qua on_partial_transcript khi ASR có chữ
                    # (xem docstring module speech/turn/interruption.py).

        async def _drain_asr() -> None:
            options = dict(self._asr_stream_options)
            if asr_hotwords is not None:
                options["hotwords"] = asr_hotwords
            async for event in self._asr.stream(_asr_frames(), **options):
                if evidence_tracker is not None or noise_tracker is not None:
                    stability = (
                        evidence_tracker.observe(event) if evidence_tracker is not None else None
                    )
                    controller.on_evidence_updated(
                        noise_evidence=latest_utterance_evidence, stability=stability
                    )
                    if interruption is not None:
                        interruption.on_evidence_updated(
                            noise_evidence=latest_noise_evidence, stability=stability
                        )
                await controller.on_transcript_event(event)
                if interruption is not None:
                    await interruption.on_partial_transcript(event)
                if event.is_final and evidence_tracker is not None:
                    # Độ ổn định là chuyện BÊN TRONG một câu. Không reset thì chuỗi câu trả
                    # lời thật "vâng" -> "có" -> "vâng" khớp mẫu dao động và câu thứ ba bị
                    # DROP; đo được "A LÔ" bị bỏ vì ảo giác "ĐÂY" của câu trước.
                    evidence_tracker.reset()

        fanout_task = asyncio.ensure_future(_fanout())
        vad_task = asyncio.ensure_future(_drain_vad())
        asr_task = asyncio.ensure_future(_drain_asr())
        next_turn = None
        workers = (fanout_task, vad_task, asr_task)
        try:
            while True:
                # Surface transport/ASR/VAD errors before emitting any pending turn.
                for task in workers:
                    if task.done():
                        task.result()
                if vad_task.done() and asr_task.done() and not controller.has_pending_turn():
                    return
                next_turn = asyncio.ensure_future(controller.get_turn())
                done, _ = await asyncio.wait(
                    {next_turn, *(task for task in workers if not task.done())},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in workers:
                    if task.done():
                        task.result()
                if next_turn in done:
                    yield next_turn.result()
                    continue
                # VAD và ASR đã đọc hết `frames` (call kết thúc) và không còn turn nào
                # đang chờ trong queue — dừng generator thay vì treo vô hạn.
                next_turn.cancel()
                await asyncio.gather(next_turn, return_exceptions=True)
                if vad_task.done() and asr_task.done() and not controller.has_pending_turn():
                    return
        finally:
            controller.set_asr_pending_probe(None)
            if next_turn is not None:
                next_turn.cancel()
            for task in workers:
                task.cancel()
            await asyncio.gather(
                *workers, *([next_turn] if next_turn else []), return_exceptions=True
            )


async def _dequeue(queue: "asyncio.Queue[object]") -> AsyncIterator[bytes]:
    while True:
        item = await queue.get()
        if item is _QUEUE_DONE:
            return
        yield item  # type: ignore[misc]


def _default_async_vad() -> AsyncStreamingVAD:
    from speech.asr.vad.energy import EnergyFrameClassifier

    return AsyncStreamingVAD(EnergyFrameClassifier())
