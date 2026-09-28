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


async def test_vad_and_admission_disagree_does_not_crash_and_logs(caplog) -> None:
    """VAD chính (StreamingVAD) báo speech_start (candidate đang hình thành trong
    TurnController) trong khi Admission classifier RIÊNG vẫn REJECT audio khỏi ASR —
    2 classifier độc lập lệch nhau là kịch bản hợp lệ, không được crash, chỉ log để
    chẩn đoán (has_active_vad_candidate, xem controller.py). Admission vẫn REJECT bình
    thường cho MỌI frame sau preroll — vad_preroll (xem test riêng ở dưới) chỉ bù đúng
    audio TRƯỚC speech_start, không bypass Admission cho frame nào khác."""
    import logging

    # VAD chính (async, đọc bởi _drain_vad -> controller.on_vad_event) báo speech_start
    # ngay từ frame đầu -> controller.has_active_vad_candidate=True từ đó về sau. Admission
    # classifier (độc lập, dùng cho _fanout) luôn báo KHÔNG speech -> REJECT toàn bộ, trừ
    # đúng 1 frame preroll (frame 0, đã push vào vad_preroll trước khi candidate active).
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
            _collect(pipeline.stream(_frames_with_yield(5), turn_controller=controller)),
            timeout=2.0,
        )

    assert len(asr.consumed_frames) == 1
    assert any("VAD/Admission disagree" in record.message for record in caplog.records)


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


async def test_vad_preroll_bridges_audio_before_speech_start() -> None:
    """Tái hiện đúng bug thật (LIVEKIT_DEBUG_DUMP_AUDIO + decode trực tiếp ZipFormerASR):
    "Tôi tên là Nguyễn Văn A" -> "TÊN LÀ NGUYỄN VĂN A" dù Admission ADMIT ngay từ
    speech_start (không REJECT gì) — âm tiết đầu ("Tôi", phát âm nhẹ/lướt) nằm TRƯỚC thời
    điểm mà CHÍNH Silero VAD (main VAD) mới nhận ra là speech. vad_preroll (độc lập
    Admission, KHÔNG opt-in) phải bù đúng phần audio đó vào asr_queue trước frame đầu
    tiên có speech_start, không cần Admission cấu hình.

    `VadEvent("speech")` filler cho 2 frame đầu (không đổi candidate state, xem
    TurnController.on_vad_event — chỉ speech_start/speech_end có tác dụng) mô phỏng đúng
    "VAD chưa coi là active", để speech_start CHỈ gắn với frame thứ 3 — nếu dùng thẳng
    `VadEvent("speech_start")` (gắn với frame ĐẦU TIÊN, xem _FakeAsyncVAD.process()), mọi
    frame đều "sau" speech_start, không thực sự test được việc bù audio TRƯỚC nó."""
    frame_before_1, frame_before_2, frame_speech_start = (
        _make_frame(1),
        _make_frame(2),
        _make_frame(3),
    )
    vad = _FakeAsyncVAD([VadEvent("speech"), VadEvent("speech"), VadEvent("speech_start")])
    asr = _RecordingASR()
    pipeline = STTPipeline(
        asr=asr,
        vad=StreamingVAD(_NullEnergyClassifier()),
        async_vad=vad,
        vad_preroll_frames=8,
    )

    await asyncio.wait_for(
        _collect(
            pipeline.stream(_frame_sequence([frame_before_1, frame_before_2, frame_speech_start]))
        ),
        timeout=2.0,
    )

    assert asr.consumed_frames == [frame_before_1, frame_before_2, frame_speech_start]


async def test_vad_preroll_works_without_admission_configured() -> None:
    """vad_preroll KHÔNG opt-in (khác admission_preroll) — phải hoạt động ngay cả khi
    Speech Admission hoàn toàn tắt (admission=None, mặc định)."""
    frame_before, frame_speech_start = _make_frame(1), _make_frame(2)
    vad = _FakeAsyncVAD([VadEvent("speech"), VadEvent("speech_start")])
    asr = _RecordingASR()
    pipeline = STTPipeline(
        asr=asr,
        vad=StreamingVAD(_NullEnergyClassifier()),
        async_vad=vad,
        vad_preroll_frames=8,
    )

    await asyncio.wait_for(
        _collect(pipeline.stream(_frame_sequence([frame_before, frame_speech_start]))),
        timeout=2.0,
    )

    assert asr.consumed_frames == [frame_before, frame_speech_start]


async def test_vad_preroll_does_not_bypass_admission_for_later_frames() -> None:
    """vad_preroll chỉ bù audio TRƯỚC speech_start — KHÔNG bypass Admission cho các frame
    SAU đó (khác thiết kế ban đầu đã bỏ: bypass khiến Admission mất tác dụng bất cứ khi
    nào VAD chính tự tin là speech, kể cả khi VAD sai). `has_active_vad_candidate` có thể
    trễ 1 frame so với speech_start thật (xem comment trong _fanout()) — test này chỉ
    khẳng định phần cốt lõi: sau khi buffer preroll (dung lượng nhỏ) đã chắc chắn hết hạn
    (nhiều frame REJECT liên tục sau đó), Admission vẫn REJECT bình thường, không có
    "cửa sổ bypass" kéo dài vô thời hạn."""
    frame_speech_start = _make_frame(1)
    later_frames = [_make_frame(i) for i in range(2, 6)]  # 4 frame RÕ RÀNG sau candidate
    vad = _FakeAsyncVAD([VadEvent("speech_start")])
    asr = _RecordingASR()
    admission = SpeechAdmission(min_snr_db=6.0, min_speech_ms=1000)  # ngưỡng cao -> luôn REJECT
    pipeline = STTPipeline(
        asr=asr,
        vad=StreamingVAD(_NullEnergyClassifier()),
        async_vad=vad,
        admission=admission,
        admission_classifier=_AlwaysSpeechClassifier(),
        vad_preroll_frames=1,  # buffer nhỏ -> hết hạn "trễ 1 frame" nhanh, không che khuất assert
    )

    async def _yielding_frames() -> AsyncIterator[bytes]:
        for frame in [frame_speech_start, *later_frames]:
            yield frame
            await asyncio.sleep(0)

    await asyncio.wait_for(_collect(pipeline.stream(_yielding_frames())), timeout=2.0)

    # 4 frame cuối đủ xa candidate start để chắc chắn không còn nằm trong "cửa sổ trễ 1
    # frame" của has_active_vad_candidate — phải bị Admission REJECT (too_short), không
    # lọt qua nhờ vad_preroll (buffer dung lượng 1, đã flush/tràn từ lâu).
    assert set(later_frames).isdisjoint(asr.consumed_frames)


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
