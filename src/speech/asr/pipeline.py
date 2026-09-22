"""Realtime STT pipeline: Audio Input (PCM 8 kHz băng hẹp) -> VAD -> ASR -> Streaming Transcript."""

import asyncio
from collections import deque
from collections.abc import Mapping
from typing import AsyncIterator, Optional

from speech.asr.admission import SpeechAdmission
from speech.asr.evidence import TranscriptEvidenceTracker
from speech.asr.recognizer import Recognizer
from speech.asr.vad.async_stream import AsyncStreamingVAD
from speech.asr.vad.base import FrameClassifier
from speech.asr.vad.streaming import StreamingVAD, split_frames
from speech.audio.codec import to_sample_rate
from speech.audio.loader import load_from_url
from speech.audio.noise_tracker import NoiseTracker
from speech.turn.controller import TurnController
from speech.turn.events import UserTurnCompleted
from speech.turn.interruption import InterruptionController, InterruptionState
from speech.types import NARROWBAND_RATE, AudioSegment, Transcript

_QUEUE_DONE = object()


class STTPipeline:
    def __init__(
        self,
        asr: Recognizer,
        vad: StreamingVAD,
        sample_rate: int = NARROWBAND_RATE,
        async_vad: Optional[AsyncStreamingVAD] = None,
        queue_max_frames: int = 50,
        barge_in_preroll_frames: int = 17,
        asr_stream_options: Optional[Mapping[str, object]] = None,
        admission: Optional[SpeechAdmission] = None,
        admission_classifier: Optional[FrameClassifier] = None,
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
        self._barge_in_preroll_frames = barge_in_preroll_frames
        self._asr_stream_options = dict(asr_stream_options or {})
        # Speech Admission (docs/reference/livekit-architecture.md §5.4): lớp lọc TRƯỚC
        # asr_queue, dựa trên SNR liên tục (NoiseTracker) thay vì chỉ is_speech() tức thời
        # của 1 frame — chặn sớm noise phòng không đồng đều mà VAD đôi khi hiểu nhầm thành
        # speech_start. `None` (mặc định) tắt hẳn — giữ hành vi cũ 100% cho caller chưa cấu
        # hình. CHỈ áp dụng ở nhánh bot không nói (turn-taking bình thường) — nhánh
        # interruption-candidate (bot đang nói) đẩy audio thẳng vào ASR không qua Admission,
        # vì đó là audio PHẢI tới ASR để InterruptionController tự xác nhận barge-in qua
        # on_partial_transcript, chặn nhầm ở đây sẽ deadlock (xem comment trong _fanout()).
        if admission is not None and admission_classifier is None:
            raise ValueError("admission_classifier bắt buộc khi truyền admission")
        self._admission = admission
        self._admission_classifier = admission_classifier
        self._noise_tracker = NoiseTracker() if admission is not None else None

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
    ) -> AsyncIterator[UserTurnCompleted]:
        """VAD và ASR chạy THẬT SỰ song song trên cùng nguồn frame, hợp nhất event vào
        TurnController để emit UserTurnCompleted — đây là turn-taking thật (không phải
        raw transcript stream), dùng cho đường LiveKit (transports/livekit/call_bridge.py).

        `frames` là PCM ở `self._sample_rate` (narrowband mặc định), liên tục suốt cuộc gọi.
        `interruption` (tuỳ chọn) cũng nhận CÙNG VAD/ASR event — input pipeline không bị
        tạm dừng khi bot nói, TurnController và InterruptionController chỉ khác nhau ở
        quyết định cuối (chốt turn vs. xác nhận ngắt lời), không khác luồng dữ liệu đầu vào.

        `evidence_tracker`/`noise_tracker` (tuỳ chọn, ĐỘC LẬP với `self._admission`'s
        noise tracker — Speech Admission và TurnValidator là 2 tính năng tách biệt, xem
        docs/reference/livekit-architecture.md §5.4): nếu `turn_controller` có `validator`
        cấu hình, cả 2 tracker này PHẢI được truyền để nó có dữ liệu — `noise_classifier`
        bắt buộc đi kèm `noise_tracker` (giống ràng buộc `admission`/`admission_classifier`
        ở `__init__`). Evidence được tính trên MỌI frame (kể cả khi bot đang nói, khác
        Admission chỉ áp dụng nhánh turn-taking bình thường) và đẩy vào
        `controller.on_evidence_updated()` mỗi khi có TranscriptEvent mới, để
        `TurnValidator.evaluate()` đọc được giá trị mới nhất lúc `_try_emit()` chạy.
        """
        if noise_tracker is not None and noise_classifier is None:
            raise ValueError("noise_classifier bắt buộc khi truyền noise_tracker")
        controller = turn_controller or TurnController()
        vad_queue: "asyncio.Queue[object]" = asyncio.Queue(maxsize=self._queue_max_frames)
        asr_queue: "asyncio.Queue[object]" = asyncio.Queue(maxsize=self._queue_max_frames)
        pre_roll: deque[bytes] = deque(maxlen=self._barge_in_preroll_frames)
        was_candidate = False
        admitted_speech_ms = 0.0
        currently_admitted = False
        latest_noise_evidence = None

        async def _fanout() -> None:
            nonlocal was_candidate, admitted_speech_ms, currently_admitted, latest_noise_evidence
            try:
                async for frame in frames:
                    await vad_queue.put(frame)
                    if noise_tracker is not None:
                        is_speech_for_evidence = noise_classifier.is_speech(frame)
                        latest_noise_evidence = noise_tracker.observe(frame, is_speech_for_evidence)
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
                                for buffered in pre_roll:
                                    await asr_queue.put(buffered)
                                pre_roll.clear()
                                was_candidate = True
                            await asr_queue.put(frame)
                        else:
                            # Chưa có dấu hiệu gì (hoặc candidate đã bị bác bỏ) — giữ
                            # echo tiềm năng trong pre-roll có giới hạn, không đưa vào
                            # ASR để không tốn compute decode noise/echo thuần tuý.
                            was_candidate = False
                            pre_roll.append(frame)
                        continue

                    pre_roll.clear()
                    was_candidate = False
                    if self._admission is None or self._noise_tracker is None:
                        await asr_queue.put(frame)
                        continue
                    is_speech = self._admission_classifier.is_speech(frame)
                    evidence = self._noise_tracker.observe(frame, is_speech)
                    if is_speech:
                        admitted_speech_ms += len(frame) / 2 / self._sample_rate * 1000
                    else:
                        admitted_speech_ms = 0.0
                    decision = self._admission.evaluate(
                        is_speech=is_speech,
                        evidence=evidence,
                        speech_ms_so_far=admitted_speech_ms,
                        already_admitted=currently_admitted,
                    )
                    currently_admitted = decision.admit
                    if decision.admit:
                        await asr_queue.put(frame)
            finally:
                await vad_queue.put(_QUEUE_DONE)
                await asr_queue.put(_QUEUE_DONE)

        async def _drain_vad() -> None:
            async for event in self._async_vad.process(_dequeue(vad_queue)):
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
            async for event in self._asr.stream(_dequeue(asr_queue), **self._asr_stream_options):
                if evidence_tracker is not None or noise_tracker is not None:
                    stability = (
                        evidence_tracker.observe(event) if evidence_tracker is not None else None
                    )
                    controller.on_evidence_updated(
                        noise_evidence=latest_noise_evidence, stability=stability
                    )
                    if interruption is not None:
                        interruption.on_evidence_updated(
                            noise_evidence=latest_noise_evidence, stability=stability
                        )
                await controller.on_transcript_event(event)
                if interruption is not None:
                    await interruption.on_partial_transcript(event)

        fanout_task = asyncio.ensure_future(_fanout())
        vad_task = asyncio.ensure_future(_drain_vad())
        asr_task = asyncio.ensure_future(_drain_asr())
        try:
            while True:
                next_turn = asyncio.ensure_future(controller.get_turn())
                done, _ = await asyncio.wait(
                    {next_turn, vad_task, asr_task}, return_when=asyncio.FIRST_COMPLETED
                )
                if next_turn in done:
                    yield next_turn.result()
                    continue
                # VAD và ASR đã đọc hết `frames` (call kết thúc) và không còn turn nào
                # đang chờ trong queue — dừng generator thay vì treo vô hạn.
                next_turn.cancel()
                if vad_task.done() and asr_task.done() and not controller.has_pending_turn():
                    return
        finally:
            for task in (fanout_task, vad_task, asr_task):
                task.cancel()
            await asyncio.gather(fanout_task, vad_task, asr_task, return_exceptions=True)


async def _dequeue(queue: "asyncio.Queue[object]") -> AsyncIterator[bytes]:
    while True:
        item = await queue.get()
        if item is _QUEUE_DONE:
            return
        yield item  # type: ignore[misc]


def _default_async_vad() -> AsyncStreamingVAD:
    from speech.asr.vad.energy import EnergyFrameClassifier

    return AsyncStreamingVAD(EnergyFrameClassifier())
