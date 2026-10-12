"""STTPipeline báo cho ASR mỗi khi ngừng đưa audio (AsrSegmentEnd).

Bug thật (cuộc gọi LiveKit 2026-09-26): ASR chỉ tự chốt câu khi thấy đủ khoảng lặng trong
các frame nó nhận. Bot bắt đầu nói giữa câu người dùng — câu dở nằm lại buffer, thành lượt
"ANH SINH ANH SINH NGÀY ...". (Nhánh Speech Admission — ngừng gửi im lặng lúc ASR mới thấy
570/600 ms — đã gỡ cùng Admission 28/09.)
"""

import asyncio
from typing import AsyncIterator

import pytest
from tests.speech.pipeline_factory import make_stt_pipeline

from speech.asr.vad.base import VadEvent
from speech.turn.controller import TurnController
from speech.turn.interruption import InterruptionController, InterruptionState
from speech.types import AsrSegmentEnd, Transcript, TranscriptEvent


class _FakeAsyncVAD:
    """Phát một VadEvent sau mỗi frame nhận được, theo thứ tự cho sẵn."""

    def __init__(self, events: list[VadEvent]) -> None:
        self._events = events

    async def process(self, frames: AsyncIterator[bytes]) -> AsyncIterator[VadEvent]:
        frame_iter = frames.__aiter__()
        for event in self._events:
            try:
                await frame_iter.__anext__()
            except StopAsyncIteration:
                return
            yield event
        async for _ in frame_iter:
            pass


class _RecordingASR:
    """Ghi lại mọi phần tử ASR nhận (frame và AsrSegmentEnd) theo đúng thứ tự; tuỳ chọn
    phát một partial sau `partial_after` frame để xác nhận barge-in."""

    name = "fake"
    input_sample_rate = 8000

    def __init__(self, partial_after: int | None = None) -> None:
        self.items: list = []
        self._partial_after = partial_after

    def transcribe(self, segment) -> Transcript:
        raise NotImplementedError

    async def stream(self, frames: AsyncIterator) -> AsyncIterator[TranscriptEvent]:
        async for item in frames:
            self.items.append(item)
            if len(self.items) == self._partial_after:
                yield TranscriptEvent(text="dừng lại", is_final=False)


class _FakeCancellableTTS:
    def __init__(self) -> None:
        self.cancel_calls = 0

    async def cancel(self) -> None:
        self.cancel_calls += 1


def _make_frame(tag: int) -> bytes:
    return bytes([tag, 0x7F]) * 240


async def _realtime(frames: list[bytes], before_frame=None) -> AsyncIterator[bytes]:
    for index, frame in enumerate(frames):
        if before_frame is not None:
            before_frame(index)
        yield frame
        await asyncio.sleep(0.01)


async def _collect(gen) -> list:
    return [item async for item in gen]


async def test_bot_starting_to_speak_discards_pending_asr_segment() -> None:
    """Bot bắt đầu nói giữa câu người dùng: phần đã gửi ASR bị bỏ, không nằm lại để ghép
    vào câu sau."""
    frames = [_make_frame(i) for i in range(1, 7)]
    controller = TurnController(min_speech_ms=0)
    asr = _RecordingASR()
    pipeline = make_stt_pipeline(asr=asr, vad=_FakeAsyncVAD([]))

    def _bot_starts_at_frame_3(index: int) -> None:
        if index == 3:
            controller.on_bot_speaking_changed(True)

    await asyncio.wait_for(
        _collect(
            pipeline.stream(_realtime(frames, _bot_starts_at_frame_3), turn_controller=controller)
        ),
        timeout=2.0,
    )

    assert asr.items == frames[:3] + [AsrSegmentEnd.DISCARD]


async def test_rejected_barge_in_candidate_discards_asr_segment() -> None:
    """Ứng viên ngắt lời không được xác nhận (VAD speech_end trước khi ASR có chữ): audio đã
    gửi ASR phải bị bỏ, không thành tiền tố của câu người dùng nói sau khi bot dứt lời."""
    controller = TurnController(min_speech_ms=0)
    controller.on_bot_speaking_changed(True)
    tts = _FakeCancellableTTS()
    interruption = InterruptionController(tts, min_speech_ms=0)
    interruption.on_bot_started_speaking()
    vad = _FakeAsyncVAD(
        [VadEvent("speech_start"), VadEvent("speech", b"x"), VadEvent("speech_end")]
    )
    asr = _RecordingASR()
    pipeline = make_stt_pipeline(asr=asr, vad=vad)

    frames = [_make_frame(i) for i in range(1, 8)]
    await asyncio.wait_for(
        _collect(
            pipeline.stream(
                _realtime(frames), turn_controller=controller, interruption=interruption
            )
        ),
        timeout=2.0,
    )

    assert tts.cancel_calls == 0  # không xác nhận ngắt lời
    assert asr.items.count(AsrSegmentEnd.DISCARD) == 1
    assert len(asr.items) > 1 and asr.items[-1] is AsrSegmentEnd.DISCARD


async def test_confirmed_barge_in_keeps_asr_segment() -> None:
    """Sau khi xác nhận ngắt lời (INTERRUPTED), bot chưa dừng hẳn nên frame tạm không vào
    ASR — nhưng phần người dùng đã nói phải được GIỮ để chốt thành turn, không bị bỏ."""
    controller = TurnController(min_speech_ms=0)
    controller.on_bot_speaking_changed(True)
    interruption = InterruptionController(_FakeCancellableTTS(), min_speech_ms=0)
    interruption.on_bot_started_speaking()
    vad = _FakeAsyncVAD([VadEvent("speech_start")] + [VadEvent("speech", b"x")] * 7)
    asr = _RecordingASR(partial_after=2)
    pipeline = make_stt_pipeline(asr=asr, vad=vad)

    frames = [_make_frame(i) for i in range(1, 9)]
    await asyncio.wait_for(
        _collect(
            pipeline.stream(
                _realtime(frames), turn_controller=controller, interruption=interruption
            )
        ),
        timeout=2.0,
    )

    assert interruption.state == InterruptionState.INTERRUPTED
    assert AsrSegmentEnd.DISCARD not in asr.items


class _EchoInMic(InterruptionController):
    """Mic có tiếng bot vọng lại (AEC không khử hết) — phần đo âm thanh có test riêng."""

    def _echo_evidence(self) -> tuple[float, float]:
        return 1.0, 1.0


class _FinalASR(_RecordingASR):
    """Phát một final `text` khi đã nhận `final_after` frame."""

    def __init__(self, text: str, final_after: int) -> None:
        super().__init__()
        self._text = text
        self._final_after = final_after

    async def stream(self, frames: AsyncIterator) -> AsyncIterator[TranscriptEvent]:
        async for item in frames:
            self.items.append(item)
            if len(self.items) == self._final_after:
                yield TranscriptEvent(text=self._text, is_final=True)


@pytest.mark.parametrize(
    ("final_text", "turns"),
    [
        ("ANH CHỊ CHẮC CHẮN MUỐN HỦY LỊCH KHÁM NÀY", []),
        ("ANH CHỊ CHẮC CHẮN MUỐN HỦY TÔI LÀ NGUYỄN VĂN A", ["TÔI LÀ NGUYỄN VĂN A"]),
    ],
)
async def test_bot_stopping_with_unconfirmed_candidate_keeps_only_caller_words(
    final_text: str, turns: list[str]
) -> None:
    """Tiếng bot vọng lại giữ ứng viên ngắt lời tới hết câu bot (VAD không có speech_end), chưa
    được xác nhận. Đo 07/10 (eval/noise-bench/barge_in_eval.py, echo nhỏ hơn giọng người gọi
    30 dB): final của đoạn đó thành lượt chép lại câu bot ở 11-12/12 câu; bỏ cả đoạn thì người
    gọi chen vào mất luôn câu của mình. Giữ đoạn, chỉ bỏ phần đầu là câu bot."""
    controller = TurnController(min_speech_ms=0, max_wait_after_vad_end_ms=20)
    controller.on_bot_speaking_changed(True)
    interruption = _EchoInMic(_FakeCancellableTTS(), min_speech_ms=0)
    interruption.on_bot_started_speaking("Anh chị chắc chắn muốn hủy lịch khám này đúng không ạ?")
    interruption.on_bot_audio(b"\x00\x00" * 8000, 8000, complete=True)
    vad = _FakeAsyncVAD([VadEvent("speech_start")] + [VadEvent("speech", b"x")] * 9)
    asr = _FinalASR(final_text, final_after=8)
    pipeline = make_stt_pipeline(asr=asr, vad=vad)

    def _bot_stops_at_frame_5(index: int) -> None:
        if index == 5:
            controller.on_bot_speaking_changed(False)
            interruption.on_bot_stopped_speaking()

    frames = [_make_frame(i) for i in range(1, 11)]
    result = await asyncio.wait_for(
        _collect(
            pipeline.stream(
                _realtime(frames, _bot_stops_at_frame_5),
                turn_controller=controller,
                interruption=interruption,
            )
        ),
        timeout=2.0,
    )

    assert AsrSegmentEnd.DISCARD not in asr.items
    assert [turn.text for turn in result] == turns


async def test_no_marker_when_asr_received_nothing() -> None:
    """Chưa gửi frame nào vào ASR thì không có gì để chốt/bỏ — không gửi tín hiệu thừa."""
    controller = TurnController(min_speech_ms=0)
    controller.on_bot_speaking_changed(True)
    asr = _RecordingASR()
    pipeline = make_stt_pipeline(asr=asr, vad=_FakeAsyncVAD([]))

    frames = [_make_frame(i) for i in range(1, 5)]
    await asyncio.wait_for(
        _collect(pipeline.stream(_realtime(frames), turn_controller=controller)), timeout=2.0
    )

    assert asr.items == []


async def test_caller_repeating_bot_words_is_not_stripped_when_the_mic_has_no_echo() -> None:
    """Người gọi chen vào, nhắc lại chữ bot ("chắc chắn muốn hủy lịch khám này") và mic không có
    tiếng bot vọng lại (AEC trình duyệt đã khử). So chữ với câu bot thì bỏ sạch, lượt rỗng —
    mất yêu cầu hủy (review 08/10)."""
    controller = TurnController(min_speech_ms=0, max_wait_after_vad_end_ms=20)
    controller.on_bot_speaking_changed(True)
    interruption = InterruptionController(_FakeCancellableTTS(), min_speech_ms=0)
    interruption.on_bot_started_speaking("Anh chị chắc chắn muốn hủy lịch khám này đúng không ạ?")
    interruption.on_bot_audio(b"\x00\x10" * 8000, 8000, complete=True)
    vad = _FakeAsyncVAD([VadEvent("speech_start")] + [VadEvent("speech", b"x")] * 9)
    asr = _FinalASR("CHẮC CHẮN MUỐN HỦY LỊCH KHÁM NÀY", final_after=8)
    pipeline = make_stt_pipeline(asr=asr, vad=vad)

    def _bot_stops_at_frame_5(index: int) -> None:
        if index == 5:
            controller.on_bot_speaking_changed(False)
            interruption.on_bot_stopped_speaking()

    frames = [_make_frame(i) for i in range(1, 11)]
    result = await asyncio.wait_for(
        _collect(
            pipeline.stream(
                _realtime(frames, _bot_stops_at_frame_5),
                turn_controller=controller,
                interruption=interruption,
            )
        ),
        timeout=2.0,
    )

    assert [turn.text for turn in result] == ["CHẮC CHẮN MUỐN HỦY LỊCH KHÁM NÀY"]


class _ScriptedFinalsASR(_RecordingASR):
    """Phát final ngay khi nhận frame có tag cho sẵn (`_make_frame(tag)`)."""

    def __init__(self, finals: dict[int, str]) -> None:
        super().__init__()
        self._finals = finals

    async def stream(self, frames: AsyncIterator) -> AsyncIterator[TranscriptEvent]:
        async for item in frames:
            self.items.append(item)
            if isinstance(item, bytes) and item[0] in self._finals:
                yield TranscriptEvent(text=self._finals[item[0]], is_final=True)


class _RecordingGate:
    enforce = True

    def __init__(self) -> None:
        self.pcm: list[bytes] = []

    def assess(self, pcm: bytes, sample_rate: int, speech_ms):
        from speech.audio.speaker_gate import SpeakerVerdict

        self.pcm.append(pcm)
        return SpeakerVerdict("pass")


async def test_speaker_gate_never_gets_audio_from_while_the_bot_was_speaking() -> None:
    """Giọng mẫu lấy từ lượt dài đầu tiên: audio lúc bot nói (tiếng bot vọng lại) lọt vào thì
    giọng mẫu có thể là giọng bot, rồi lời thật của người gọi bị chặn."""
    controller = TurnController(min_speech_ms=0, max_wait_after_vad_end_ms=20)
    controller.on_bot_speaking_changed(True)
    interruption = InterruptionController(_FakeCancellableTTS(), min_speech_ms=0)
    interruption.on_bot_started_speaking()
    vad = _FakeAsyncVAD([VadEvent("speech_start")] + [VadEvent("speech", b"x")] * 9)
    asr = _ScriptedFinalsASR({8: "tôi tên là Nguyễn Văn A"})
    gate = _RecordingGate()
    pipeline = make_stt_pipeline(asr=asr, vad=vad, speaker_gate=gate)

    def _bot_stops_at_frame_5(index: int) -> None:
        if index == 4:  # frame tag 5
            controller.on_bot_speaking_changed(False)
            interruption.on_bot_stopped_speaking()

    frames = [_make_frame(i) for i in range(1, 11)]
    result = await asyncio.wait_for(
        _collect(
            pipeline.stream(
                _realtime(frames, _bot_stops_at_frame_5),
                turn_controller=controller,
                interruption=interruption,
            )
        ),
        timeout=2.0,
    )

    assert [turn.text for turn in result] == ["tôi tên là Nguyễn Văn A"]
    (pcm,) = gate.pcm
    assert all(_make_frame(tag) not in pcm for tag in range(1, 5))
    assert _make_frame(5) in pcm


async def test_speaker_gate_gets_only_the_accepted_turn_not_dropped_ones_before_it() -> None:
    """Lượt bị bỏ (final rỗng, từ đệm, quá ngắn) không được dồn vào audio của lượt sau."""
    events = (
        [VadEvent("speech_start")]
        + [VadEvent("speech", b"x")] * 12
        + [VadEvent("speech_end")]  # frame 14: lượt đầu, final rỗng -> bỏ
        + [VadEvent("speech", b"x")] * 14
        + [VadEvent("speech_start")]  # frame 29: lượt được nhận
        + [VadEvent("speech", b"x")] * 2
        + [VadEvent("speech_end")]
    )
    asr = _ScriptedFinalsASR({13: "", 31: "tôi muốn đặt lịch"})
    gate = _RecordingGate()
    pipeline = make_stt_pipeline(asr=asr, vad=_FakeAsyncVAD(events), speaker_gate=gate)

    frames = [_make_frame(i) for i in range(1, 34)]
    result = await asyncio.wait_for(
        _collect(
            pipeline.stream(
                _realtime(frames),
                turn_controller=TurnController(min_speech_ms=0, max_wait_after_vad_end_ms=20),
            )
        ),
        timeout=3.0,
    )

    assert [turn.text for turn in result] == ["tôi muốn đặt lịch"]
    (pcm,) = gate.pcm
    assert all(_make_frame(tag) not in pcm for tag in range(1, 15))
    assert _make_frame(29) in pcm


class _BatchASR(_RecordingASR):
    """Streaming không phát gì; decode cả đoạn (lời chen giữ riêng) trả `text`."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self._text = text
        self.batch: list[bytes] = []

    def transcribe(self, segment) -> Transcript:
        self.batch.append(segment.pcm)
        return Transcript(text=self._text, confidence=0.9, is_silence=False)


@pytest.mark.parametrize(("keep", "turns"), [(True, ["NĂM MỘT CHÍN BẢY TÁM"]), (False, [])])
async def test_unconfirmed_barge_in_is_held_and_released_when_the_bot_finishes(
    keep: bool, turns: list[str]
) -> None:
    """Cuộc gọi 08/10: người gọi nói "năm một chín bảy tám" chen lúc bot nói, không được xác
    nhận ngắt lời (SNR thấp), VAD hết câu khi bot còn nói -> đoạn ASR bị bỏ, mất cả câu. Giữ
    riêng audio đó, bot dứt lời thì decode thành lượt."""
    controller = TurnController(min_speech_ms=0, max_wait_after_vad_end_ms=20)
    controller.on_bot_speaking_changed(True)
    interruption = InterruptionController(_FakeCancellableTTS(), min_speech_ms=0)
    interruption.on_bot_started_speaking("Dạ, anh chị cho em xin năm sinh ạ.")
    events = (
        [VadEvent("speech_start")]
        + [VadEvent("speech", b"x")] * 3
        + [VadEvent("speech_end")]
        + [VadEvent("speech", b"x")] * 9
    )
    asr = _BatchASR("NĂM MỘT CHÍN BẢY TÁM")
    pipeline = make_stt_pipeline(asr=asr, vad=_FakeAsyncVAD(events), keep_unconfirmed_barge_in=keep)

    def _bot_stops_at_frame_10(index: int) -> None:
        if index == 9:
            controller.on_bot_speaking_changed(False)
            interruption.on_bot_stopped_speaking()

    frames = [_make_frame(i) for i in range(1, 15)]
    result = await asyncio.wait_for(
        _collect(
            pipeline.stream(
                _realtime(frames, _bot_stops_at_frame_10),
                turn_controller=controller,
                interruption=interruption,
            )
        ),
        timeout=2.0,
    )

    assert [turn.text for turn in result] == turns
    assert len(asr.batch) == (1 if keep else 0)
    if keep:
        assert all(_make_frame(tag) in asr.batch[0] for tag in range(1, 5))
        assert _make_frame(12) not in asr.batch[0]  # chỉ audio của ứng viên, không phải sau đó


async def test_held_barge_in_that_is_only_bot_echo_does_not_become_a_turn() -> None:
    controller = TurnController(min_speech_ms=0, max_wait_after_vad_end_ms=20)
    controller.on_bot_speaking_changed(True)
    interruption = _EchoInMic(_FakeCancellableTTS(), min_speech_ms=0)
    interruption.on_bot_started_speaking("Dạ Vinmec xin nghe, em là trợ lý ảo AI")
    interruption.on_bot_audio(b"\x00\x00" * 8000, 8000, complete=True)
    events = [VadEvent("speech_start")] + [VadEvent("speech", b"x")] * 3 + [VadEvent("speech_end")]
    events += [VadEvent("speech", b"x")] * 9
    pipeline = make_stt_pipeline(
        asr=_BatchASR("DẠ VIN MÁCH XIN NGHE EM LÀ"),
        vad=_FakeAsyncVAD(events),
        keep_unconfirmed_barge_in=True,
    )

    def _bot_stops_at_frame_10(index: int) -> None:
        if index == 9:
            controller.on_bot_speaking_changed(False)
            interruption.on_bot_stopped_speaking()

    frames = [_make_frame(i) for i in range(1, 15)]
    result = await asyncio.wait_for(
        _collect(
            pipeline.stream(
                _realtime(frames, _bot_stops_at_frame_10),
                turn_controller=controller,
                interruption=interruption,
            )
        ),
        timeout=2.0,
    )

    assert result == []


async def test_speech_before_bot_end_is_replayed_even_without_a_vad_candidate() -> None:
    from speech.asr.stream_context import StreamingFrame

    class PrerollASR(_RecordingASR):
        supports_preroll_frames = True

    controller = TurnController()
    controller.on_bot_speaking_changed(True)
    interruption = InterruptionController(_FakeCancellableTTS())
    interruption.on_bot_started_speaking("Xin chào")
    asr = PrerollASR()
    pipeline = make_stt_pipeline(asr=asr, vad=_FakeAsyncVAD([]))
    frames = [_make_frame(i) for i in range(1, 6)]

    def stop(index):
        if index == 3:
            controller.on_bot_speaking_changed(False)
            interruption.on_bot_stopped_speaking()

    await _collect(pipeline.stream(_realtime(frames, stop), controller, interruption))

    replay = asr.items[:3]
    assert all(isinstance(item, StreamingFrame) and item.is_preroll for item in replay)
    assert [item.pcm for item in replay] == frames[:3]
    assert asr.items[3:] == frames[3:]


async def test_barge_in_reads_utterance_snr_when_latest_mic_frame_is_silent() -> None:
    from speech.asr.evidence import StabilityVerdict
    from speech.asr.pipeline import _CallStream
    from speech.audio.noise_tracker import NoiseEvidence
    from speech.turn.validator import TurnValidator

    class Evidence:
        frame_noise = NoiseEvidence(rms=0, noise_floor=100, snr_db=-60)
        utterance_noise = NoiseEvidence(rms=1000, noise_floor=100, snr_db=20)

        def observe_transcript(self, event):
            return StabilityVerdict.CONVERGING

    tts = _FakeCancellableTTS()
    interruption = InterruptionController(
        tts, min_speech_ms=0, min_snr_db=0, validator=TurnValidator()
    )
    interruption.on_bot_started_speaking("Xin cho biết họ tên")
    await interruption.on_speech_started(VadEvent("speech_start"))
    controller = TurnController(min_speech_ms=0)
    controller.on_bot_speaking_changed(True)
    pipeline = make_stt_pipeline(
        asr=_FinalASR("ĐÚNG RỒI", 1), vad=_FakeAsyncVAD([]), evidence=Evidence()
    )
    stream = _CallStream(pipeline, controller, interruption)
    await stream._send_to_asr(_make_frame(1))
    from speech.asr.pipeline import _QUEUE_DONE

    await stream._asr_queue.put(_QUEUE_DONE)
    await stream._drain_asr()

    assert tts.cancel_calls == 1
    assert interruption.state == InterruptionState.INTERRUPTED


@pytest.mark.parametrize("text", ["Ừ", "À", "ĐÂY"])
async def test_held_noise_is_still_filtered_before_core(text: str) -> None:
    from speech.audio.noise_tracker import NoiseEvidence
    from speech.turn.validator import TurnValidator

    controller = TurnController(min_speech_ms=250, validator=TurnValidator())
    controller.on_held_barge_in(
        text, speech_ms=2000, noise_evidence=NoiseEvidence(rms=1, noise_floor=100, snr_db=-40)
    )

    assert not controller.has_pending_turn()


@pytest.mark.parametrize("vad_start", [True, False])
async def test_recovery_preserves_prefix_when_new_final_arrives_first(vad_start: bool) -> None:
    controller = TurnController(min_speech_ms=0)
    if vad_start:
        await controller.on_vad_event(VadEvent("speech_start"))
    controller.begin_barge_in_recovery()
    await controller.on_transcript_event(TranscriptEvent("NĂM MỘT CHÍN BẢY TÁM", is_final=True))
    assert not controller.has_pending_turn()

    controller.on_held_barge_in("MƯỜI BỐN THÁNG BA", speech_ms=1000)
    controller.end_barge_in_recovery()

    assert (await controller.get_turn()).text == "MƯỜI BỐN THÁNG BA NĂM MỘT CHÍN BẢY TÁM"


async def test_recovered_segments_form_one_turn_and_each_segment_still_passes_noise_gates() -> None:
    from speech.audio.noise_tracker import NoiseEvidence
    from speech.turn.validator import TurnValidator

    controller = TurnController(min_speech_ms=250, validator=TurnValidator())
    controller.begin_barge_in_recovery()
    controller.on_held_barge_in("MƯỜI BỐN THÁNG BA", speech_ms=500)
    assert not controller.has_pending_turn()
    controller.on_held_barge_in("ĐÂY", speech_ms=500, noise_evidence=NoiseEvidence(1, 100, -40))
    controller.on_held_barge_in("NĂM MỘT CHÍN BẢY TÁM", speech_ms=600)
    controller.end_barge_in_recovery()

    turn = await controller.get_turn()
    assert turn.text == "MƯỜI BỐN THÁNG BA NĂM MỘT CHÍN BẢY TÁM"
    assert turn.audio_duration_ms == 1100
    assert not controller.has_pending_turn()


async def test_held_decoder_error_is_reported_while_audio_is_still_open() -> None:
    class BrokenASR(_BatchASR):
        def transcribe(self, segment):
            raise RuntimeError("held decoder failed")

    controller = TurnController(min_speech_ms=0)
    controller.on_bot_speaking_changed(True)
    interruption = InterruptionController(_FakeCancellableTTS(), min_speech_ms=0)
    interruption.on_bot_started_speaking("Xin cho biết ngày sinh")
    vad = _FakeAsyncVAD([VadEvent("speech_start"), VadEvent("speech_end")])
    pipeline = make_stt_pipeline(asr=BrokenASR(""), vad=vad, keep_unconfirmed_barge_in=True)

    def stop(index):
        if index == 4:
            controller.on_bot_speaking_changed(False)
            interruption.on_bot_stopped_speaking()

    async def still_open():
        async for frame in _realtime([_make_frame(i) for i in range(1, 7)], stop):
            yield frame
        await asyncio.Event().wait()

    with pytest.raises(RuntimeError, match="held decoder failed"):
        await asyncio.wait_for(_collect(pipeline.stream(still_open(), controller, interruption)), 2)


class _FinalizingASR(_RecordingASR):
    supports_segment_finalize = True


async def test_caller_mid_sentence_when_bot_starts_keeps_asr_segment_and_finalizes_it() -> None:
    """Người gọi đang nói dở (VAD đã "đang nói") thì bot bắt đầu nói: không có cạnh
    speech_start nào nữa. Trước đây cả câu bot không có ứng viên và đoạn ASR bị bỏ mỗi frame —
    mất lời người gọi. Giờ ứng viên mở lại ngay, đoạn ASR giữ nguyên và được chốt thành final
    khi người gọi ngừng mà chưa xác nhận ngắt lời."""
    frames = [_make_frame(i) for i in range(1, 10)]
    controller = TurnController(min_speech_ms=0)
    tts = _FakeCancellableTTS()
    interruption = InterruptionController(tts, min_speech_ms=0)
    vad = _FakeAsyncVAD(
        [VadEvent("speech_start")] + [VadEvent("speech", b"x")] * 4 + [VadEvent("speech_end")]
    )
    asr = _FinalizingASR()
    pipeline = make_stt_pipeline(asr=asr, vad=vad)

    def _bot_starts_at_frame_3(index: int) -> None:
        if index == 3:
            controller.on_bot_speaking_changed(True)
            interruption.on_bot_started_speaking("Dạ em xin nghe")

    await asyncio.wait_for(
        _collect(
            pipeline.stream(
                _realtime(frames, _bot_starts_at_frame_3),
                turn_controller=controller,
                interruption=interruption,
            )
        ),
        timeout=2.0,
    )

    assert asr.items[:5] == frames[:5]
    assert AsrSegmentEnd.DISCARD not in asr.items
    assert asr.items.count(AsrSegmentEnd.FINALIZE) == 1
    assert tts.cancel_calls == 0


class _HotwordASR(_RecordingASR):
    def __init__(self, supports: bool) -> None:
        super().__init__()
        self.supports_hotwords = supports
        self.options: dict = {}

    async def stream(self, frames: AsyncIterator, **options) -> AsyncIterator[TranscriptEvent]:
        self.options = options
        async for item in super().stream(frames):
            yield item


@pytest.mark.parametrize("supports", [True, False])
async def test_pipeline_hands_its_hotword_box_only_to_providers_that_support_it(
    supports: bool,
) -> None:
    asr = _HotwordASR(supports)
    pipeline = make_stt_pipeline(asr=asr, vad=_FakeAsyncVAD([]))
    frames = [_make_frame(i) for i in range(1, 4)]

    await asyncio.wait_for(
        _collect(pipeline.stream(_realtime(frames), turn_controller=TurnController())),
        timeout=2.0,
    )

    assert (asr.options.get("hotwords") is pipeline.hotwords) is supports
    assert ("hotwords" in asr.options) is supports
