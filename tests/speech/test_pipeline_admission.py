import asyncio
from typing import AsyncIterator

from speech.asr.admission import SpeechAdmission
from speech.asr.pipeline import STTPipeline
from speech.asr.vad.base import VadEvent
from speech.asr.vad.streaming import StreamingVAD
from speech.turn.controller import TurnController
from speech.types import Transcript, TranscriptEvent


class _NullEnergyClassifier:
    def is_speech(self, frame: bytes) -> bool:
        return False


class _AlwaysSpeechClassifier:
    """Admission classifier độc lập — luôn báo speech để cô lập test khỏi thuật toán
    phân loại thật, chỉ kiểm tra wiring Admission trong _fanout()."""

    def is_speech(self, frame: bytes) -> bool:
        return True


class _FakeAsyncVAD:
    def __init__(self, events: list[VadEvent]) -> None:
        self._events = events

    async def process(self, frames: AsyncIterator[bytes]) -> AsyncIterator[VadEvent]:
        frame_iter = frames.__aiter__()
        for event in self._events:
            try:
                await frame_iter.__anext__()
            except StopAsyncIteration:
                pass
            yield event
        async for _ in frame_iter:
            pass


class _FakeASR:
    name = "fake"
    input_sample_rate = 8000

    def __init__(self) -> None:
        self.consumed_frame_count = 0

    def transcribe(self, segment) -> Transcript:
        raise NotImplementedError

    async def stream(self, frames: AsyncIterator[bytes]) -> AsyncIterator[TranscriptEvent]:
        async for _ in frames:
            self.consumed_frame_count += 1
        return
        yield  # pragma: no cover - hàm generator, không có event nào emit trong test này


class _RecordingASR:
    """Như `_FakeASR` nhưng ghi lại ĐÚNG THỨ TỰ frame đã nhận — dùng để verify pre-roll
    flush không làm lệch/mất thứ tự audio (test PreRollBuffer qua pipeline thật)."""

    name = "fake"
    input_sample_rate = 8000

    def __init__(self) -> None:
        self.consumed_frames: list[bytes] = []

    def transcribe(self, segment) -> Transcript:
        raise NotImplementedError

    async def stream(self, frames: AsyncIterator[bytes]) -> AsyncIterator[TranscriptEvent]:
        async for frame in frames:
            self.consumed_frames.append(frame)
        return
        yield  # pragma: no cover


class _ByFrameClassifier:
    """Admission classifier điều khiển được is_speech theo TỪNG frame cụ thể (khớp index
    trong danh sách frame gửi vào) — mô phỏng câu nói thật: vài frame đầu SNR/duration
    chưa đủ, sau đó ổn định. Frame không có trong `speech_frames` -> is_speech=False."""

    def __init__(self, speech_frames: set[bytes]) -> None:
        self._speech_frames = speech_frames

    def is_speech(self, frame: bytes) -> bool:
        return frame in self._speech_frames


async def _frames(count: int, frame: bytes = b"\x00\x00" * 240) -> AsyncIterator[bytes]:
    for _ in range(count):
        yield frame


async def _frame_sequence(frames: list[bytes]) -> AsyncIterator[bytes]:
    for frame in frames:
        yield frame


async def _collect(gen):
    return [item async for item in gen]


def _make_frame(tag: int, amplitude: int = 0x7F) -> bytes:
    """Frame PCM 240 sample, phân biệt được bằng `tag` (byte đầu) để assert thứ tự chính
    xác — `amplitude` cao mô phỏng audio thật (SNR cao so với noise_floor mặc định)."""
    return bytes([tag & 0xFF, amplitude]) * 240


async def test_admission_blocks_low_snr_frames_from_reaching_asr() -> None:
    """Frame is_speech=True nhưng SNR quá thấp (silence thuần -> rms=noise_floor -> snr=0)
    bị Admission chặn — không tới ASR dù classifier báo speech."""
    vad = _FakeAsyncVAD([])
    asr = _FakeASR()
    admission = SpeechAdmission(min_snr_db=6.0, min_speech_ms=0)
    pipeline = STTPipeline(
        asr=asr,
        vad=StreamingVAD(_NullEnergyClassifier()),
        async_vad=vad,
        admission=admission,
        admission_classifier=_AlwaysSpeechClassifier(),
    )

    await asyncio.wait_for(
        _collect(pipeline.stream(_frames(5, frame=b"\x00\x00" * 240))), timeout=2.0
    )

    assert asr.consumed_frame_count == 0


async def test_admission_admits_high_snr_frames_after_min_duration() -> None:
    """Frame biên độ lớn (SNR cao so với noise_floor mặc định) đủ min_speech_ms -> admit,
    tới được ASR."""
    vad = _FakeAsyncVAD([])
    asr = _FakeASR()
    admission = SpeechAdmission(min_snr_db=6.0, min_speech_ms=30)
    loud_frame = b"\x00\x7f" * 240  # amplitude lớn -> SNR cao so với noise_floor mặc định
    pipeline = STTPipeline(
        asr=asr,
        vad=StreamingVAD(_NullEnergyClassifier()),
        async_vad=vad,
        admission=admission,
        admission_classifier=_AlwaysSpeechClassifier(),
    )

    await asyncio.wait_for(_collect(pipeline.stream(_frames(5, frame=loud_frame))), timeout=2.0)

    assert asr.consumed_frame_count > 0


async def test_admission_disabled_by_default_keeps_old_behavior() -> None:
    vad = _FakeAsyncVAD([])
    asr = _FakeASR()
    pipeline = STTPipeline(asr=asr, vad=StreamingVAD(_NullEnergyClassifier()), async_vad=vad)

    await asyncio.wait_for(_collect(pipeline.stream(_frames(5))), timeout=2.0)

    assert asr.consumed_frame_count == 5


async def test_preroll_flushes_rejected_frames_when_admitted() -> None:
    """ "Không, tôi muốn đổi lịch" — 2 frame đầu (phần "Không") bị REJECT vì too_short
    (chưa đủ min_speech_ms), frame thứ 3 mới đủ điều kiện ADMIT. PreRollBuffer phải bù lại
    đúng 2 frame đầu đó vào asr_queue, theo đúng thứ tự, trước khi gửi frame thứ 3."""
    vad = _FakeAsyncVAD([])
    asr = _RecordingASR()
    frame_khong_1, frame_khong_2, frame_toi = (
        _make_frame(1),
        _make_frame(2),
        _make_frame(3),
    )
    # min_speech_ms=90 (3 frame @30ms) -> 2 frame đầu luôn too_short dù SNR đã đủ ngay từ
    # frame 1 (amplitude cao, is_speech=True cho cả 3 frame qua _ByFrameClassifier).
    admission = SpeechAdmission(min_snr_db=6.0, min_speech_ms=90)
    pipeline = STTPipeline(
        asr=asr,
        vad=StreamingVAD(_NullEnergyClassifier()),
        async_vad=vad,
        admission=admission,
        admission_classifier=_ByFrameClassifier({frame_khong_1, frame_khong_2, frame_toi}),
        admission_preroll_frames=8,
    )

    await asyncio.wait_for(
        _collect(pipeline.stream(_frame_sequence([frame_khong_1, frame_khong_2, frame_toi]))),
        timeout=2.0,
    )

    assert asr.consumed_frames == [frame_khong_1, frame_khong_2, frame_toi]


async def test_quiet_start_of_sentence_still_reaches_asr_via_preroll() -> None:
    """Người nói nhỏ ở đầu câu: 2 frame đầu SNR thấp (low_snr, is_speech=True nhưng dưới
    ngưỡng), giọng lớn dần đủ ADMIT ở frame 3 -> vẫn phải có đủ cả 3 frame tới ASR."""
    vad = _FakeAsyncVAD([])
    asr = _RecordingASR()
    quiet_1, quiet_2, loud = _make_frame(1, 0x01), _make_frame(2, 0x01), _make_frame(3, 0x7F)
    admission = SpeechAdmission(min_snr_db=6.0, min_speech_ms=0)

    class _SnrRisingClassifier:
        def is_speech(self, frame: bytes) -> bool:
            return frame in {quiet_1, quiet_2, loud}

    pipeline = STTPipeline(
        asr=asr,
        vad=StreamingVAD(_NullEnergyClassifier()),
        async_vad=vad,
        admission=admission,
        admission_classifier=_SnrRisingClassifier(),
        admission_preroll_frames=8,
    )

    await asyncio.wait_for(
        _collect(pipeline.stream(_frame_sequence([quiet_1, quiet_2, loud]))), timeout=2.0
    )

    assert asr.consumed_frames == [quiet_1, quiet_2, loud]


async def test_noise_before_speech_does_not_inflate_noise_floor() -> None:
    """Noise trước khi user nói: frame no_speech liên tục phải được phép cập nhật
    noise_floor bình thường (không có gì để giữ lại vì is_speech=False rõ ràng) — verify
    qua wiring: audio noise thuần (is_speech=False) không tới ASR, không bị kẹt trong
    preroll mãi mãi (buffer chỉ giữ tối đa `admission_preroll_frames`)."""
    vad = _FakeAsyncVAD([])
    asr = _RecordingASR()
    noise_frames = [_make_frame(i, 0x01) for i in range(20)]
    admission = SpeechAdmission(min_snr_db=6.0, min_speech_ms=0)

    class _NeverSpeechClassifier:
        def is_speech(self, frame: bytes) -> bool:
            return False

    pipeline = STTPipeline(
        asr=asr,
        vad=StreamingVAD(_NullEnergyClassifier()),
        async_vad=vad,
        admission=admission,
        admission_classifier=_NeverSpeechClassifier(),
        admission_preroll_frames=4,
    )

    await asyncio.wait_for(_collect(pipeline.stream(_frame_sequence(noise_frames))), timeout=2.0)

    assert asr.consumed_frames == []


async def test_loud_pre_onset_does_not_poison_floor_or_stream_silence_forever() -> None:
    """Silero nhận speech trễ: frame đầu rất lớn không được nâng floor rồi khóa cả câu.

    Khi đã ADMIT, chỉ gửi tối đa end_silence_ms im lặng cho ASR để nó chốt final.
    """
    asr = _RecordingASR()
    pre_onset = _make_frame(1, 0x7F)
    speech = _make_frame(2, 0x03)
    silence = bytes(480)
    admission = SpeechAdmission(min_snr_db=6.0, min_speech_ms=30, end_silence_ms=90)
    pipeline = STTPipeline(
        asr=asr,
        vad=StreamingVAD(_NullEnergyClassifier()),
        async_vad=_FakeAsyncVAD([]),
        admission=admission,
        admission_classifier=_ByFrameClassifier({speech}),
    )

    frames = [pre_onset] * 10 + [speech] * 5 + [silence] * 30
    await asyncio.wait_for(_collect(pipeline.stream(_frame_sequence(frames))), timeout=2.0)

    assert speech in asr.consumed_frames
    assert asr.consumed_frames.count(silence) == 2


async def test_vad_and_admission_disagree_does_not_crash_and_logs(caplog) -> None:
    """VAD chính (StreamingVAD) báo speech_start (candidate đang hình thành trong
    TurnController) trong khi Admission classifier RIÊNG vẫn REJECT audio khỏi ASR —
    2 classifier độc lập lệch nhau là kịch bản hợp lệ, không được crash, chỉ log để
    chẩn đoán (has_active_vad_candidate, xem controller.py). VAD chính không phải cổng
    vào ASR: Admission REJECT thì không frame nào tới ASR."""
    import logging

    # VAD chính (async, đọc bởi _drain_vad -> controller.on_vad_event) báo speech_start
    # ngay từ frame đầu -> controller.has_active_vad_candidate=True từ đó về sau. Admission
    # classifier (độc lập, dùng cho _fanout) luôn báo KHÔNG speech -> REJECT toàn bộ.
    vad = _FakeAsyncVAD([VadEvent("speech_start")])
    asr = _RecordingASR()
    controller = TurnController(min_speech_ms=0)
    admission = SpeechAdmission(min_snr_db=6.0, min_speech_ms=0)
    pipeline = STTPipeline(
        asr=asr,
        vad=StreamingVAD(_NullEnergyClassifier()),
        async_vad=vad,
        admission=admission,
        admission_classifier=_NullEnergyClassifier(),
    )

    async def _frames_with_yield(count: int) -> AsyncIterator[bytes]:
        # asyncio.sleep(0) giữa mỗi frame -> nhường lịch cho _drain_vad() xử lý
        # speech_start trước khi _fanout() xử lý frame kế tiếp, tránh test đua với
        # scheduler (_drain_vad chạy ở task riêng, không đồng bộ với _fanout theo frame).
        for _ in range(count):
            yield b"\x00\x00" * 240
            await asyncio.sleep(0)

    with caplog.at_level(logging.DEBUG, logger="speech.asr.pipeline"):
        await asyncio.wait_for(
            _collect(pipeline.stream(_frames_with_yield(100), turn_controller=controller)),
            timeout=2.0,
        )

    assert asr.consumed_frames == []
    disagree_logs = [
        record for record in caplog.records if "VAD/Admission disagree" in record.message
    ]
    assert len(disagree_logs) == 1  # không log 100 lần cho 100 frame 30ms


async def test_already_admitted_mid_sentence_frame_not_dropped_by_preroll() -> None:
    """Sau khi ADMIT, audio giữa câu (already_admitted=True, kể cả khi SNR/is_speech tụt
    tạm thời) phải tới ASR trực tiếp — KHÔNG bị route qua PreRollBuffer (buffer chỉ giữ
    frame bị REJECT), không mất frame nào giữa câu."""
    vad = _FakeAsyncVAD([])
    asr = _RecordingASR()
    frames = [_make_frame(i) for i in range(6)]
    admission = SpeechAdmission(min_snr_db=6.0, min_speech_ms=30)
    pipeline = STTPipeline(
        asr=asr,
        vad=StreamingVAD(_NullEnergyClassifier()),
        async_vad=vad,
        admission=admission,
        admission_classifier=_AlwaysSpeechClassifier(),
        admission_preroll_frames=8,
    )

    await asyncio.wait_for(_collect(pipeline.stream(_frame_sequence(frames))), timeout=2.0)

    assert asr.consumed_frames == frames


async def _yielding(frames: list[bytes]) -> AsyncIterator[bytes]:
    """Như audio live: nhường lịch sau mỗi frame để task VAD kịp xử lý frame vừa gửi."""
    for frame in frames:
        yield frame
        await asyncio.sleep(0)


async def test_each_frame_reaches_asr_once_in_order_without_admission() -> None:
    """Hồi quy: VAD chính báo speech_start giữa luồng KHÔNG được làm ASR nhận lại audio.

    Bug thật (eval/noise-bench): một bộ preroll riêng của VAD chính flush lại các frame
    đã gửi, ASR nhận [1, 2, 3, 1, 2, 3, 4, ...] — "A LÔ" thành "A LÔ A LÔ"."""
    frames = [_make_frame(i) for i in range(1, 9)]
    vad = _FakeAsyncVAD([VadEvent("speech"), VadEvent("speech"), VadEvent("speech_start")])
    asr = _RecordingASR()
    pipeline = STTPipeline(asr=asr, vad=StreamingVAD(_NullEnergyClassifier()), async_vad=vad)

    await asyncio.wait_for(_collect(pipeline.stream(_yielding(frames))), timeout=2.0)

    assert asr.consumed_frames == frames


async def test_each_frame_reaches_asr_once_in_order_with_admission() -> None:
    """Hồi quy: preroll của Admission và speech_start của VAD chính không được chồng lấn.

    Bug thật: hai bộ preroll cùng flush các frame chồng nhau, ASR nhận [90..99] rồi
    [83..] — đầu câu bị đảo thứ tự, "TÔI LÀ ĐỖ ĐỨC DŨNG" chỉ còn "DŨNG"."""
    frames = [_make_frame(i) for i in range(1, 9)]
    vad = _FakeAsyncVAD([VadEvent("speech"), VadEvent("speech"), VadEvent("speech_start")])
    asr = _RecordingASR()
    pipeline = STTPipeline(
        asr=asr,
        vad=StreamingVAD(_NullEnergyClassifier()),
        async_vad=vad,
        admission=SpeechAdmission(min_snr_db=6.0, min_speech_ms=60),
        admission_classifier=_AlwaysSpeechClassifier(),
        admission_preroll_frames=20,
    )

    await asyncio.wait_for(_collect(pipeline.stream(_yielding(frames))), timeout=2.0)

    assert asr.consumed_frames == frames


async def test_stream_with_min_speech_ms_zero_still_works_with_turn_controller() -> None:
    """Sanity: pipeline vẫn hoạt động bình thường khi admission=None (mặc định) dù dùng
    TurnController tuỳ chỉnh — không có hồi quy khi wiring mới không được kích hoạt."""
    vad = _FakeAsyncVAD([VadEvent("speech_start"), VadEvent("speech_end")])

    class _AsrWithFinal:
        name = "fake"
        input_sample_rate = 8000

        def transcribe(self, segment) -> Transcript:
            raise NotImplementedError

        async def stream(self, frames: AsyncIterator[bytes]) -> AsyncIterator[TranscriptEvent]:
            frame_iter = frames.__aiter__()
            await frame_iter.__anext__()
            yield TranscriptEvent(text="ok", is_final=True)
            async for _ in frame_iter:
                pass

    asr = _AsrWithFinal()
    pipeline = STTPipeline(asr=asr, vad=StreamingVAD(_NullEnergyClassifier()), async_vad=vad)

    turns = await asyncio.wait_for(
        _collect(pipeline.stream(_frames(5), turn_controller=TurnController(min_speech_ms=0))),
        timeout=2.0,
    )

    assert len(turns) == 1
    assert turns[0].text == "ok"
