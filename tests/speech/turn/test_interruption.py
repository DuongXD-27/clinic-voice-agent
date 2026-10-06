import pytest

from speech.asr.vad.base import VadEvent
from speech.turn.interruption import InterruptionController, InterruptionState
from speech.types import TranscriptEvent


class _FakeTTS:
    def __init__(self) -> None:
        self.cancel_calls = 0

    async def cancel(self) -> None:
        self.cancel_calls += 1


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


async def test_idle_ignores_speech_events() -> None:
    tts = _FakeTTS()
    controller = InterruptionController(tts)

    await controller.on_speech_started(VadEvent("speech_start"))

    assert controller.state == InterruptionState.IDLE
    assert tts.cancel_calls == 0


async def test_speech_start_while_bot_speaking_becomes_candidate_not_interrupted_yet() -> None:
    tts = _FakeTTS()
    controller = InterruptionController(tts)
    controller.on_bot_started_speaking()

    await controller.on_speech_started(VadEvent("speech_start"))

    assert controller.state == InterruptionState.INTERRUPTION_CANDIDATE
    assert tts.cancel_calls == 0  # chưa đủ điều kiện — chỉ mới là ứng viên


async def test_partial_transcript_confirms_interruption_after_min_duration() -> None:
    tts = _FakeTTS()
    clock = _FakeClock()
    controller = InterruptionController(tts, min_speech_ms=200, clock=clock)
    controller.on_bot_started_speaking()
    await controller.on_speech_started(VadEvent("speech_start"))

    clock.advance(0.25)  # vượt ngưỡng 200ms
    confirmed = await controller.on_partial_transcript(
        TranscriptEvent(text="dừng lại", is_final=False)
    )

    assert confirmed is True
    assert controller.state == InterruptionState.INTERRUPTED
    assert tts.cancel_calls == 1


async def test_empty_partial_does_not_confirm() -> None:
    tts = _FakeTTS()
    clock = _FakeClock()
    controller = InterruptionController(tts, min_speech_ms=200, clock=clock)
    controller.on_bot_started_speaking()
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.advance(0.25)

    confirmed = await controller.on_partial_transcript(TranscriptEvent(text="   ", is_final=False))

    assert confirmed is False
    assert controller.state == InterruptionState.INTERRUPTION_CANDIDATE
    assert tts.cancel_calls == 0


async def test_short_noise_reverts_to_bot_speaking_without_cancelling() -> None:
    """Backchannel/noise ngắn: speech_start rồi speech_end ngay, không có partial nào,
    chưa đủ min_speech_ms -> không được cancel TTS, quay lại BOT_SPEAKING."""
    tts = _FakeTTS()
    clock = _FakeClock()
    controller = InterruptionController(tts, min_speech_ms=200, clock=clock)
    controller.on_bot_started_speaking()
    await controller.on_speech_started(VadEvent("speech_start"))

    clock.advance(0.05)  # chỉ 50ms — chưa đủ 200ms
    await controller.on_speech_ended_without_confirmation()

    assert controller.state == InterruptionState.BOT_SPEAKING
    assert tts.cancel_calls == 0


async def test_partial_before_min_duration_does_not_confirm() -> None:
    """Bug thật đã gặp: ASR trả về text (kể cả hợp lệ) NGAY khi vừa mới thành candidate,
    trước khi đủ min_speech_ms, không được confirm ngay — text có thể là hallucination
    từ vài frame noise đầu tiên (quạt máy, tiếng ồn phòng)."""
    tts = _FakeTTS()
    clock = _FakeClock()
    controller = InterruptionController(tts, min_speech_ms=200, clock=clock)
    controller.on_bot_started_speaking()
    await controller.on_speech_started(VadEvent("speech_start"))

    clock.advance(0.05)  # chỉ 50ms — chưa đủ 200ms
    confirmed = await controller.on_partial_transcript(
        TranscriptEvent(text="dừng lại", is_final=False)
    )

    assert confirmed is False
    assert controller.state == InterruptionState.INTERRUPTION_CANDIDATE
    assert tts.cancel_calls == 0


async def test_sustained_duration_alone_without_transcript_does_not_confirm() -> None:
    """Bug thật đã gặp: tiếng quạt/noise nền kéo dài liên tục (VAD báo "speech" nhiều
    lần) không được tự cắt lời bot chỉ vì đủ duration — phải có ASR partial có nghĩa
    thật sự đi kèm. Không còn đường xác nhận thuần-duration (confirm_if_sustained đã bị
    xoá), nên duration một mình sẽ không bao giờ tự confirm."""
    tts = _FakeTTS()
    clock = _FakeClock()
    controller = InterruptionController(tts, min_speech_ms=200, clock=clock)
    controller.on_bot_started_speaking()
    await controller.on_speech_started(VadEvent("speech_start"))

    clock.advance(5.0)  # noise kéo dài rất lâu, vượt xa ngưỡng duration

    assert controller.state == InterruptionState.INTERRUPTION_CANDIDATE
    assert tts.cancel_calls == 0


async def test_meaningless_partial_does_not_confirm_even_after_min_duration() -> None:
    """Filler word ("ờm") mà ASR decode đúng (không phải hallucination) từ audio đủ dài
    vẫn không được coi là barge-in thật — không mang nội dung ngắt lời."""
    tts = _FakeTTS()
    clock = _FakeClock()
    controller = InterruptionController(tts, min_speech_ms=200, clock=clock)
    controller.on_bot_started_speaking()
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.advance(0.25)

    confirmed = await controller.on_partial_transcript(TranscriptEvent(text="ờm", is_final=False))

    assert confirmed is False
    assert controller.state == InterruptionState.INTERRUPTION_CANDIDATE
    assert tts.cancel_calls == 0


async def test_bot_stopped_speaking_resets_to_idle() -> None:
    tts = _FakeTTS()
    controller = InterruptionController(tts)
    controller.on_bot_started_speaking()
    await controller.on_speech_started(VadEvent("speech_start"))

    controller.on_bot_stopped_speaking()

    assert controller.state == InterruptionState.IDLE


async def test_validator_drops_hallucination_pattern_during_barge_in() -> None:
    """Tái hiện đúng bug thật đã gặp qua LiveKit demo: WebRTC VAD nhận nhầm noise phòng
    thành speech_start GIỮA LÚC bot đang nói -> ASR hallucinate ra "ĐÂY" (SNR thấp, text
    ngắn) -> KHÔNG được confirm barge-in nếu có TurnValidator cấu hình (trước khi sửa,
    _passes_gate() không có SNR check nên vẫn confirm bất kể noise)."""
    from speech.asr.evidence import StabilityVerdict
    from speech.audio.noise_tracker import NoiseEvidence
    from speech.turn.validator import TurnValidator

    tts = _FakeTTS()
    clock = _FakeClock()
    validator = TurnValidator(min_snr_db=6.0)
    controller = InterruptionController(tts, min_speech_ms=200, clock=clock, validator=validator)
    controller.on_bot_started_speaking()
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.advance(0.25)
    controller.on_evidence_updated(
        noise_evidence=NoiseEvidence(rms=60.0, noise_floor=50.0, snr_db=1.6),
        stability=StabilityVerdict.UNKNOWN,
    )

    confirmed = await controller.on_partial_transcript(TranscriptEvent(text="đây", is_final=False))

    assert confirmed is False
    assert controller.state == InterruptionState.INTERRUPTION_CANDIDATE
    assert tts.cancel_calls == 0


async def test_validator_allows_real_speech_with_high_snr_during_barge_in() -> None:
    """Barge-in thật (SNR cao, câu dài rõ ràng) vẫn phải hoạt động bình thường dù có
    TurnValidator cấu hình — validator chỉ CHẶN THÊM, không được chặn nhầm barge-in thật."""
    from speech.asr.evidence import StabilityVerdict
    from speech.audio.noise_tracker import NoiseEvidence
    from speech.turn.validator import TurnValidator

    tts = _FakeTTS()
    clock = _FakeClock()
    validator = TurnValidator(min_snr_db=6.0)
    controller = InterruptionController(tts, min_speech_ms=200, clock=clock, validator=validator)
    controller.on_bot_started_speaking()
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.advance(0.25)
    controller.on_evidence_updated(
        noise_evidence=NoiseEvidence(rms=5000.0, noise_floor=50.0, snr_db=40.0),
        stability=StabilityVerdict.CONVERGING,
    )

    confirmed = await controller.on_partial_transcript(
        TranscriptEvent(text="dừng lại đi", is_final=False)
    )

    assert confirmed is True
    assert controller.state == InterruptionState.INTERRUPTED
    assert tts.cancel_calls == 1


async def test_validator_wait_does_not_confirm_barge_in() -> None:
    """Tái hiện đúng log thật qua LiveKit (LIVEKIT_DEBUG_DUMP_AUDIO): SNR vừa phải
    (~14dB, không đủ thấp để TurnValidator DROP ở min_snr_db mặc định) + text ngắn
    hallucinate ("ĐÚNG") + stability=UNKNOWN -> validator.evaluate() trả WAIT, không
    DROP. Trước khi sửa, `_passes_gate()` coi WAIT như ACCEPT nên vẫn xác nhận barge-in
    giả dù user hoàn toàn im lặng — WAIT giờ phải reject như DROP."""
    from speech.asr.evidence import StabilityVerdict
    from speech.audio.noise_tracker import NoiseEvidence
    from speech.turn.validator import TurnValidator

    tts = _FakeTTS()
    clock = _FakeClock()
    validator = TurnValidator(min_snr_db=3.0)
    controller = InterruptionController(tts, min_speech_ms=200, clock=clock, validator=validator)
    controller.on_bot_started_speaking()
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.advance(0.25)
    controller.on_evidence_updated(
        noise_evidence=NoiseEvidence(rms=250.0, noise_floor=50.0, snr_db=14.1),
        stability=StabilityVerdict.UNKNOWN,
    )

    confirmed = await controller.on_partial_transcript(TranscriptEvent(text="ĐÚNG", is_final=False))

    assert confirmed is False
    assert controller.state == InterruptionState.INTERRUPTION_CANDIDATE
    assert tts.cancel_calls == 0


async def test_no_validator_keeps_old_behavior() -> None:
    tts = _FakeTTS()
    clock = _FakeClock()
    controller = InterruptionController(tts, min_speech_ms=200, clock=clock)
    controller.on_bot_started_speaking()
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.advance(0.25)

    confirmed = await controller.on_partial_transcript(TranscriptEvent(text="đây", is_final=False))

    assert confirmed is True


async def test_echo_of_bot_greeting_does_not_confirm_barge_in() -> None:
    """Tái hiện đúng bug thật qua LiveKit (LIVEKIT_DEBUG_DUMP_AUDIO): bot đọc câu chào,
    browser echo cancellation không loại hết audio qua loa/mic, ASR nghe lại chính giọng
    bot và tưởng là barge-in. Candidate text giống cao với bot_text (fuzzy match) ->
    reject dù qua được mọi gate khác (duration/meaningful text/validator)."""
    tts = _FakeTTS()
    clock = _FakeClock()
    controller = InterruptionController(tts, min_speech_ms=200, clock=clock)
    controller.on_bot_started_speaking(
        "Dạ Vinmec xin nghe, em là trợ lý ảo AI của tổng đài. "
        "Anh chị vui lòng cho em biết họ tên đầy đủ ạ?"
    )
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.advance(0.25)

    confirmed = await controller.on_partial_transcript(
        TranscriptEvent(text="em là trợ lý ảo AI", is_final=False)
    )

    assert confirmed is False
    assert controller.state == InterruptionState.INTERRUPTION_CANDIDATE
    assert tts.cancel_calls == 0


@pytest.mark.parametrize("partials", [["Anh", "Anh muốn"], ["ANH MUỐN", "ANH MUỐN EM"]])
async def test_short_caller_partials_are_not_mistaken_for_bot_echo(partials) -> None:
    """Đo 06/10: partial thật "Anh", "Anh muốn", "ANH MUỐN EM" khớp mờ một khúc câu bot nên bị
    coi là echo, 0/12 lần ngắt lời được xác nhận."""
    tts = _FakeTTS()
    clock = _FakeClock()
    controller = InterruptionController(tts, min_speech_ms=200, clock=clock)
    controller.on_bot_started_speaking("Alo, anh chị còn nghe máy không ạ?")
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.advance(0.25)

    results = [
        await controller.on_partial_transcript(TranscriptEvent(text=text, is_final=False))
        for text in partials
    ]

    assert any(results)
    assert tts.cancel_calls == 1


async def test_exact_short_fragment_of_bot_text_is_still_echo() -> None:
    tts = _FakeTTS()
    clock = _FakeClock()
    controller = InterruptionController(tts, min_speech_ms=200, clock=clock)
    controller.on_bot_started_speaking("Alo, anh chị còn nghe máy không ạ?")
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.advance(0.25)

    confirmed = await controller.on_partial_transcript(
        TranscriptEvent(text="anh chị", is_final=False)
    )

    assert confirmed is False


async def test_no_bot_text_keeps_old_behavior_for_echo_check() -> None:
    """`on_bot_started_speaking()` không truyền bot_text (caller cũ chưa cập nhật) -> tắt
    hẳn echo check, không đổi hành vi barge-in thật."""
    tts = _FakeTTS()
    clock = _FakeClock()
    controller = InterruptionController(tts, min_speech_ms=200, clock=clock)
    controller.on_bot_started_speaking()  # bot_text mặc định ""
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.advance(0.25)

    confirmed = await controller.on_partial_transcript(
        TranscriptEvent(text="dừng lại đi", is_final=False)
    )

    assert confirmed is True


async def test_low_snr_rejects_long_text_during_barge_in() -> None:
    """Tái hiện đúng log thật: candidate 5 từ 'EM ĐÃ CHUẨN BỊ Ở ĐÂY' snr_db=-25.56 (rất
    thấp, đặc trưng echo qua loa-mic) vẫn được TurnValidator ACCEPT vì luật SNR của nó
    chỉ áp dụng cho text <=2 từ (không kích hoạt cho text dài này). interruption_min_snr_db
    RIÊNG phải chặn được case này mà validator bỏ lọt."""
    from speech.asr.evidence import StabilityVerdict
    from speech.audio.noise_tracker import NoiseEvidence
    from speech.turn.validator import TurnValidator

    tts = _FakeTTS()
    clock = _FakeClock()
    validator = TurnValidator(min_snr_db=3.0)
    controller = InterruptionController(
        tts, min_speech_ms=200, clock=clock, validator=validator, min_snr_db=0.0
    )
    controller.on_bot_started_speaking()
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.advance(0.25)
    controller.on_evidence_updated(
        noise_evidence=NoiseEvidence(rms=3.0, noise_floor=50.0, snr_db=-25.56),
        stability=StabilityVerdict.CONVERGING,
    )

    confirmed = await controller.on_partial_transcript(
        TranscriptEvent(text="em đã chuẩn bị ở đây", is_final=False)
    )

    assert confirmed is False
    assert controller.state == InterruptionState.INTERRUPTION_CANDIDATE
    assert tts.cancel_calls == 0


async def test_low_snr_threshold_none_keeps_old_behavior() -> None:
    """min_snr_db=None (mặc định) -> không chặn gì thêm, giữ hành vi cũ 100%."""
    from speech.asr.evidence import StabilityVerdict
    from speech.audio.noise_tracker import NoiseEvidence

    tts = _FakeTTS()
    clock = _FakeClock()
    controller = InterruptionController(tts, min_speech_ms=200, clock=clock)
    controller.on_bot_started_speaking()
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.advance(0.25)
    controller.on_evidence_updated(
        noise_evidence=NoiseEvidence(rms=3.0, noise_floor=50.0, snr_db=-25.56),
        stability=StabilityVerdict.CONVERGING,
    )

    confirmed = await controller.on_partial_transcript(
        TranscriptEvent(text="em đã chuẩn bị ở đây", is_final=False)
    )

    assert confirmed is True


async def test_high_snr_real_barge_in_still_confirms_with_snr_threshold() -> None:
    """Barge-in thật (SNR cao) vẫn hoạt động bình thường dù đã cấu hình
    interruption_min_snr_db — ngưỡng chỉ chặn SNR THẤP, không chặn nhầm barge-in thật."""
    from speech.asr.evidence import StabilityVerdict
    from speech.audio.noise_tracker import NoiseEvidence

    tts = _FakeTTS()
    clock = _FakeClock()
    controller = InterruptionController(tts, min_speech_ms=200, clock=clock, min_snr_db=0.0)
    controller.on_bot_started_speaking()
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.advance(0.25)
    controller.on_evidence_updated(
        noise_evidence=NoiseEvidence(rms=5000.0, noise_floor=50.0, snr_db=40.0),
        stability=StabilityVerdict.CONVERGING,
    )

    confirmed = await controller.on_partial_transcript(
        TranscriptEvent(text="dừng lại đi", is_final=False)
    )

    assert confirmed is True
    assert controller.state == InterruptionState.INTERRUPTED
    assert tts.cancel_calls == 1


if __name__ == "__main__":
    pytest.main([__file__])
