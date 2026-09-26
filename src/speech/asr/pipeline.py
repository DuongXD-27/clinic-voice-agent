"""Realtime STT pipeline: Audio Input (PCM 8 kHz băng hẹp) -> VAD -> ASR -> Streaming Transcript."""

import asyncio
import logging
from collections import deque
from collections.abc import Mapping
from typing import AsyncIterator, Optional

from speech.asr.admission import PreRollBuffer, SpeechAdmission
from speech.asr.evidence import TranscriptEvidenceTracker
from speech.asr.recognizer import Recognizer
from speech.asr.vad.async_stream import AsyncStreamingVAD
from speech.asr.vad.base import FrameClassifier
from speech.asr.vad.streaming import StreamingVAD, split_frames
from speech.audio.codec import to_sample_rate
from speech.audio.loader import load_from_url
from speech.audio.noise_tracker import NoiseTracker, UtteranceEvidenceTracker
from speech.turn.controller import TurnController
from speech.turn.events import UserTurnCompleted
from speech.turn.interruption import InterruptionController, InterruptionState
from speech.types import NARROWBAND_RATE, AsrSegmentEnd, AudioSegment, Transcript

_QUEUE_DONE = object()
_DISAGREEMENT_LOG_INTERVAL_S = 10.0

logger = logging.getLogger(__name__)


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
        admission_preroll_frames: int = 20,
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
        # PreRollBuffer (xem docstring speech/asr/admission.py): bù lại đúng phần audio
        # "trễ" trong lúc Admission còn REJECT (chưa đủ SNR/duration) — không có buffer thì
        # ASR luôn mất khoảng min_speech_ms đầu câu, kể cả khi Admission quyết định đúng.
        #
        # Đây là bộ đệm DUY NHẤT ở tầng pipeline: mỗi frame tới asr_queue đúng một lần,
        # đúng thứ tự thời gian. Từng có thêm một `_vad_preroll` flush khi VAD chính báo
        # speech_start — nó giữ CÙNG các frame đã được gửi (Admission tắt) hoặc đang nằm
        # trong bộ đệm này (Admission bật), nên ASR nhận đầu câu hai lần và có lúc đảo thứ
        # tự ([90..99] rồi [83..]). Đo trên eval/noise-bench, audio sạch: "A LÔ" ->
        # "A LÔ A LÔ", "TÔI LÀ ĐỖ ĐỨC DŨNG" -> "DŨNG". Âm tiết đầu câu mà VAD
        # nhận muộn đã được ZipFormerASR.stream() giữ lại bằng pre-speech riêng của nó.
        self._admission_preroll = (
            PreRollBuffer(admission_preroll_frames) if admission is not None else None
        )

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
        admitted_nonspeech_ms = 0.0
        currently_admitted = False
        latest_noise_evidence = None
        # TurnValidator đọc SNR của CẢ câu vừa nói, không phải frame mới nhất (luôn là im
        # lặng lúc ASR final tới) — xem UtteranceEvidenceTracker. InterruptionController vẫn
        # nhận evidence theo frame như trước.
        utterance_tracker = UtteranceEvidenceTracker() if noise_tracker is not None else None
        latest_utterance_evidence = None
        last_disagreement_log_at: float | None = None
        # ASR tự chốt câu bằng khoảng lặng trong các frame NÓ nhận; mỗi khi _fanout ngừng
        # đưa frame, phải báo tường minh để câu dở không nằm lại trong buffer ASR (xem
        # docstring AsrSegmentEnd). True = đã gửi frame từ lần báo gần nhất.
        asr_segment_open = False

        async def _send_to_asr(frame: bytes) -> None:
            nonlocal asr_segment_open
            await asr_queue.put(frame)
            asr_segment_open = True

        async def _end_asr_segment(kind: AsrSegmentEnd) -> None:
            nonlocal asr_segment_open
            if asr_segment_open:
                await asr_queue.put(kind)
                asr_segment_open = False

        async def _fanout() -> None:
            nonlocal was_candidate, admitted_speech_ms, admitted_nonspeech_ms, currently_admitted
            nonlocal latest_noise_evidence, latest_utterance_evidence, last_disagreement_log_at
            try:
                async for frame in frames:
                    await vad_queue.put(frame)
                    if noise_tracker is not None:
                        is_speech_for_evidence = noise_classifier.is_speech(frame)
                        latest_noise_evidence = noise_tracker.observe(frame, is_speech_for_evidence)
                        latest_utterance_evidence = utterance_tracker.observe(
                            latest_noise_evidence, is_speech_for_evidence
                        )
                    if controller.is_bot_speaking:
                        # Turn trước đã kết thúc; không mang trạng thái Admission
                        # sang đoạn audio/echo trong lúc bot đang phát TTS.
                        admitted_speech_ms = admitted_nonspeech_ms = 0.0
                        currently_admitted = False
                        if self._admission_preroll is not None:
                            self._admission_preroll.clear()
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
                    if self._admission is None or self._noise_tracker is None:
                        await _send_to_asr(frame)
                        continue
                    is_speech = self._admission_classifier.is_speech(frame)
                    # Đo trước khi cập nhật floor. Một âm tiết đầu câu có thể rất lớn
                    # nhưng Silero cần vài frame mới nhận ra speech; nếu coi các frame
                    # đó là noise, floor sẽ tự tăng tới mức chặn cả câu nói thật.
                    evidence = self._noise_tracker.peek(frame)
                    frame_duration_ms = len(frame) / 2 / self._sample_rate * 1000
                    if is_speech:
                        admitted_speech_ms += frame_duration_ms
                        admitted_nonspeech_ms = 0.0
                    else:
                        admitted_speech_ms = 0.0
                        admitted_nonspeech_ms = (
                            admitted_nonspeech_ms + frame_duration_ms if currently_admitted else 0.0
                        )
                    decision = self._admission.evaluate(
                        is_speech=is_speech,
                        evidence=evidence,
                        speech_ms_so_far=admitted_speech_ms,
                        nonspeech_ms_so_far=admitted_nonspeech_ms,
                        already_admitted=currently_admitted,
                    )
                    # no_speech nhưng SNR cao là tín hiệu MƠ HỒ, không phải nền nhiễu
                    # chắc chắn. Giữ floor cũ để không tự khóa đầu câu nói thật.
                    if (
                        decision.reason == "no_speech"
                        and evidence.snr_db < self._admission.min_snr_db
                    ):
                        self._noise_tracker.commit_floor(evidence)
                    if not decision.admit and controller.has_active_vad_candidate:
                        # VAD chính còn trong đoạn speech, Admission vẫn chặn ASR.
                        # Log tối đa một lần/10s: 30ms/frame sẽ làm đầy log rất nhanh.
                        now = asyncio.get_running_loop().time()
                        if (
                            last_disagreement_log_at is None
                            or now - last_disagreement_log_at >= _DISAGREEMENT_LOG_INTERVAL_S
                        ):
                            logger.debug(
                                "speech_admission: VAD/Admission disagree — vad_candidate=True "
                                "admission_reason=%s snr_db=%.1f",
                                decision.reason,
                                evidence.snr_db,
                            )
                            last_disagreement_log_at = now
                    if decision.admit != currently_admitted:
                        # Log THEO CHUYỂN TRẠNG THÁI (không phải mỗi frame — 30ms/frame
                        # sẽ spam log) — đủ để chẩn đoán Admission có đang âm thầm chặn
                        # hết audio thật hay không (trước đây quyết định này KHÔNG được
                        # log gì cả, khiến "không bắt được âm" không có cách nào phân biệt
                        # được với VAD không thấy speech_start/track không publish).
                        logger.debug(
                            "speech_admission: %s reason=%s is_speech=%s snr_db=%.1f "
                            "speech_ms_so_far=%.0f",
                            "ADMIT" if decision.admit else "REJECT",
                            decision.reason,
                            is_speech,
                            evidence.snr_db,
                            admitted_speech_ms,
                        )
                    if currently_admitted and not decision.admit:
                        # Admission kết thúc đoạn sau end_silence_ms im lặng — cùng ngưỡng
                        # ASR cần để tự chốt, nên ASR luôn thiếu (đo được 570/600 ms): câu
                        # nằm lại trong buffer rồi thành final giả khi preroll của câu sau
                        # được flush. Bug thật: lượt 2 lặp nguyên văn lượt 1.
                        await _end_asr_segment(AsrSegmentEnd.FINALIZE)
                    if (
                        decision.admit
                        and not currently_admitted
                        and self._admission_preroll is not None
                    ):
                        # Transition REJECT->ADMIT: bù lại đúng phần audio đã giữ trong
                        # buffer (im lặng ngắn + phần đầu giọng nói chưa đủ bằng chứng) —
                        # PHẢI flush trước khi gửi frame hiện tại để giữ đúng thứ tự thời
                        # gian (xem docstring speech/asr/admission.py::PreRollBuffer).
                        for buffered in self._admission_preroll.flush():
                            await _send_to_asr(buffered)
                    currently_admitted = decision.admit
                    if decision.admit:
                        await _send_to_asr(frame)
                    elif self._admission_preroll is not None:
                        self._admission_preroll.push(frame)
            finally:
                await vad_queue.put(_QUEUE_DONE)
                await asr_queue.put(_QUEUE_DONE)

        async def _drain_vad() -> None:
            async for event in self._async_vad.process(_dequeue(vad_queue)):
                if event.kind in ("speech_start", "speech_end"):
                    # DEBUG only: chẩn đoán VAD chính có "kẹt" ở in_speech=True kéo dài
                    # bất thường hay không (bug thật đã gặp qua LiveKit: log Admission
                    # disagree lặp hàng trăm dòng liên tục dù user chỉ nói câu ngắn rồi
                    # dừng — cần biết VAD chính có bao giờ tự phát speech_end không, tách
                    # biệt khỏi log Admission ở _fanout() vốn dùng classifier KHÁC).
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
            async for event in self._asr.stream(_dequeue(asr_queue), **self._asr_stream_options):
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
