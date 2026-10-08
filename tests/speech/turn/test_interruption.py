import numpy as np
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


@pytest.mark.parametrize(("snr", "confirmed"), [(20.0, True), (-20.0, False)])
async def test_final_reply_can_confirm_without_a_second_partial_but_still_checks_snr(
    snr: float, confirmed: bool
) -> None:
    from speech.audio.noise_tracker import NoiseEvidence
    from speech.turn.validator import TurnValidator

    tts = _FakeTTS()
    clock = _FakeClock()
    controller = InterruptionController(tts, clock=clock, validator=TurnValidator(), min_snr_db=0)
    controller.on_bot_started_speaking("Xin cho biết họ tên")
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.advance(0.5)
    controller.on_evidence_updated(noise_evidence=NoiseEvidence(1000, 100, snr))

    assert await controller.on_partial_transcript(TranscriptEvent("ĐÚNG RỒI", True)) is confirmed
    assert tts.cancel_calls == int(confirmed)


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


@pytest.mark.parametrize("text", ["A LÔ", "A LÔ ANH CHỊ CÒN NGHE MÁY KHÔNG Ạ"])
async def test_split_alo_echo_cannot_cancel_bot_playout(text: str) -> None:
    tts = _FakeTTS()
    clock = _FakeClock()
    controller = InterruptionController(tts, min_speech_ms=0, clock=clock)
    controller.on_bot_started_speaking("Alo, anh chị còn nghe máy không ạ?")
    await controller.on_speech_started(VadEvent("speech_start"))

    assert not await controller.on_partial_transcript(TranscriptEvent(text, is_final=False))
    assert tts.cancel_calls == 0


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


_BOT = "Dạ anh chị muốn đặt lịch khám ngày mai hay ngày kia ạ"
_RATE = 16_000
_FRAME_S = 0.03


def _voice(seconds: float, seed: int) -> np.ndarray:
    """Giọng giả: nhiễu có đường bao lên xuống theo âm tiết (60 ms, độ to ngẫu nhiên)."""
    rng = np.random.default_rng(seed)
    envelope = np.repeat(rng.uniform(0.05, 1.0, int(seconds / 0.06)), int(0.06 * _RATE))
    return rng.normal(0.0, 3000.0, envelope.size) * envelope


async def _echo_text_heard_at(seconds: float, *, echo: bool, interrupted: bool = False) -> str:
    """Câu bot `_BOT` phát 4 s từ t=0; mic nhận frame 30 ms; ứng viên ngắt lời ở `seconds`,
    pre-roll 0,5 s; bot dừng 0,6 s sau đó. `echo`: mic là tiếng bot trễ 0,1 s, nhỏ đi 20 dB
    (AEC không khử hết); không thì mic là giọng khác (người gọi, AEC đã khử tiếng bot)."""
    clock = _FakeClock()
    controller = InterruptionController(_FakeTTS(), min_speech_ms=0, clock=clock)
    controller.on_bot_started_speaking(_BOT)
    bot = _voice(4.0, seed=1)
    controller.on_bot_audio(bot.astype(np.int16).tobytes(), _RATE, complete=True)
    if echo:
        mic = np.concatenate([np.zeros(int(0.1 * _RATE)), bot * 0.1, np.zeros(_RATE)])
    else:
        mic = _voice(5.0, seed=2)
    frame = int(_FRAME_S * _RATE)

    def hear_until(t: float) -> None:
        while clock.now + _FRAME_S <= t + 1e-9:
            i = int(round(clock.now * _RATE))
            clock.advance(_FRAME_S)
            controller.on_caller_audio(mic[i : i + frame].astype(np.int16).tobytes())

    hear_until(seconds)
    await controller.on_speech_started(VadEvent("speech_start"))
    if interrupted:
        await controller.on_partial_transcript(TranscriptEvent(text="khoan đã", is_final=False))
    hear_until(seconds + 0.6)
    controller.on_bot_stopped_speaking()
    return controller.echo_text(lookback_s=0.5)


async def test_caller_repeating_bot_words_without_echo_in_the_mic_is_not_echo() -> None:
    """Người gọi nhắc lại chữ bot vừa nói ("đặt lịch khám ngày mai") khi mic không có tiếng bot
    vọng lại (AEC đã khử): chỉ so chữ thì bị bỏ sạch, mất yêu cầu của người gọi."""
    from speech.turn.controller import strip_echo_prefix

    echo = await _echo_text_heard_at(3.0, echo=False)

    assert echo == ""
    assert strip_echo_prefix("Đặt lịch khám ngày mai", echo) == "Đặt lịch khám ngày mai"


async def test_echo_text_covers_bot_words_played_while_asr_listened() -> None:
    from speech.turn.controller import strip_echo_prefix

    echo = await _echo_text_heard_at(0.2, echo=True)

    assert echo == _BOT
    assert strip_echo_prefix("DẠ ANH CHỊ MUỐN ĐẶT LỊCH KHÁM NGÀY MAI HAY", echo) == ""


async def test_echo_text_excludes_bot_words_finished_before_asr_listened() -> None:
    echo = await _echo_text_heard_at(3.0, echo=True)

    assert echo == "khám ngày mai hay ngày kia ạ"


async def test_echo_text_stops_where_confirmed_barge_in_cut_the_bot() -> None:
    echo = await _echo_text_heard_at(0.2, echo=True, interrupted=True)

    assert echo == "Dạ anh chị muốn đặt"


def _play(controller, clock: _FakeClock, text: str, bot: np.ndarray, mic: np.ndarray) -> None:
    """Một câu bot từ lúc này tới hết `mic` (frame 30 ms), không ai ngắt lời."""
    controller.on_bot_started_speaking(text)
    controller.on_bot_audio(bot.astype(np.int16).tobytes(), _RATE, complete=True)
    frame = int(_FRAME_S * _RATE)
    for i in range(0, len(mic) - frame + 1, frame):
        clock.advance(_FRAME_S)
        controller.on_caller_audio(mic[i : i + frame].astype(np.int16).tobytes())
    controller.on_bot_stopped_speaking()


def _echo_of(bot: np.ndarray) -> np.ndarray:
    return np.concatenate([np.zeros(int(0.1 * _RATE)), bot * 0.1, np.zeros(_RATE // 2)])


async def _barge_in_after(echo_in_previous_sentence: bool) -> str:
    """Câu bot trước (có hoặc không có tiếng vọng), rồi `_BOT` mà người gọi nói to át ngay từ
    đầu — tiếng vọng của câu này không đo ra được."""
    clock = _FakeClock()
    controller = InterruptionController(_FakeTTS(), min_speech_ms=0, clock=clock)
    greeting = _voice(4.0, seed=3)
    _play(
        controller,
        clock,
        "Dạ Vinmec xin nghe",
        greeting,
        _echo_of(greeting) if echo_in_previous_sentence else np.zeros(5 * _RATE),
    )
    controller.on_bot_started_speaking(_BOT)
    controller.on_bot_audio(_voice(4.0, seed=1).astype(np.int16).tobytes(), _RATE, complete=True)
    clock.advance(0.2)
    await controller.on_speech_started(VadEvent("speech_start"))
    caller = _voice(4.0, seed=2)
    frame = int(_FRAME_S * _RATE)
    for i in range(0, len(caller) - frame + 1, frame):
        clock.advance(_FRAME_S)
        controller.on_caller_audio(caller[i : i + frame].astype(np.int16).tobytes())
    controller.on_bot_stopped_speaking()
    return controller.echo_text(lookback_s=0.5)


async def test_echo_heard_earlier_in_the_call_still_counts_when_the_caller_drowns_it_out() -> None:
    assert await _barge_in_after(echo_in_previous_sentence=True) == _BOT


async def test_call_without_echo_never_strips_caller_words() -> None:
    assert await _barge_in_after(echo_in_previous_sentence=False) == ""


@pytest.mark.parametrize("echo", [True, False])
async def test_first_sentence_remembers_echo_before_the_caller_drowns_it_out(echo: bool) -> None:
    clock = _FakeClock()
    controller = InterruptionController(_FakeTTS(), min_speech_ms=0, clock=clock)
    controller.on_bot_started_speaking(_BOT)
    bot = _voice(4.0, seed=1)
    controller.on_bot_audio(bot.astype(np.int16).tobytes(), _RATE, complete=True)
    mic = _echo_of(bot) if echo else np.zeros(len(_echo_of(bot)))
    caller = _voice(3.0, seed=2) * 0.4
    start = int(1.2 * _RATE)
    mic[start : start + len(caller)] += caller
    frame = int(_FRAME_S * _RATE)
    for i in range(0, len(mic) - frame + 1, frame):
        clock.advance(_FRAME_S)
        controller.on_caller_audio(
            np.clip(mic[i : i + frame], -32768, 32767).astype(np.int16).tobytes()
        )
        if i == 9 * frame:
            await controller.on_speech_started(VadEvent("speech_start"))
    controller.on_bot_stopped_speaking()

    # The final mixed envelope alone no longer shows echo; the earlier evidence must survive.
    assert not controller._echo_heard(*controller._echo_evidence())
    assert controller.echo_text(lookback_s=0.5) == (_BOT if echo else "")


async def test_echo_text_without_tts_audio_strips_nothing() -> None:
    clock = _FakeClock()
    controller = InterruptionController(_FakeTTS(), min_speech_ms=0, clock=clock)
    controller.on_bot_started_speaking(_BOT)
    clock.advance(1.0)
    await controller.on_speech_started(VadEvent("speech_start"))

    assert controller.echo_text(lookback_s=0.5) == ""


async def test_bot_sentence_echoed_with_misheard_words_does_not_confirm_barge_in() -> None:
    """Đo 07/10 qua kênh điện thoại: đuôi câu bot bị chép sai ("VỀ VIỆC", "HẢ") vẫn là echo."""
    tts = _FakeTTS()
    clock = _FakeClock()
    controller = InterruptionController(tts, min_speech_ms=200, clock=clock)
    controller.on_bot_started_speaking("Dạ, anh chị muốn đổi lịch hay hủy lịch khám ạ?")
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.advance(0.25)

    confirmed = await controller.on_partial_transcript(
        TranscriptEvent(text="DẠ ANH CHỊ MUỐN ĐỔI LỊCH HAY HỦY LỊCH HẢ", is_final=False)
    )

    assert confirmed is False
    assert tts.cancel_calls == 0


if __name__ == "__main__":
    pytest.main([__file__])


def test_long_echo_delay_is_recognised_when_the_bot_stops() -> None:
    """Echo trễ 0,6 s (SIP): lúc bot vừa dứt lời, 0,6 s cuối câu chưa vọng về mic. Độ phủ tính cả
    phần đó thì tiếng vọng thuần (tương quan 1,0) chỉ phủ 0,67 < 0,7 — không bao giờ nhận ra."""
    rate, hop = 16000, 480
    clock = _FakeClock()
    controller = InterruptionController(_FakeTTS(), clock=clock)
    rng = np.random.default_rng(1)
    envelope = np.repeat(rng.uniform(0.05, 1.0, 30), int(0.06 * rate))
    bot = rng.normal(0, 3000, envelope.size) * envelope
    controller.on_bot_started_speaking("Alo, anh chị còn nghe máy không ạ?")
    controller.on_bot_audio(bot.astype(np.int16).tobytes(), rate, complete=True)
    delay = 0.6
    mic = np.concatenate([np.zeros(int(delay * rate)), 0.1 * bot, np.zeros(rate)])
    for k in range(len(bot) // hop):
        clock.advance(hop / rate)
        controller.on_caller_audio(mic[k * hop : (k + 1) * hop].astype(np.int16).tobytes())
    controller.on_bot_stopped_speaking()

    assert controller.echo_path == "echo"


def test_correlated_echo_residue_that_the_vad_never_hears_is_not_echo() -> None:
    """AEC của trình duyệt để lại phần vọng rất nhỏ, vẫn tương quan với tiếng bot nhưng VAD không
    bắt: không được coi là có vọng (cắt nhầm "HỌ VÀ TÊN" khi người gọi nhắc lại câu bot)."""
    rate, hop = 16000, 480
    clock = _FakeClock()
    controller = InterruptionController(_FakeTTS(), clock=clock)
    rng = np.random.default_rng(1)
    envelope = np.repeat(rng.uniform(0.05, 1.0, 50), int(0.06 * rate))
    bot = rng.normal(0, 3000, envelope.size) * envelope
    controller.on_bot_started_speaking("Dạ, anh chị vui lòng cho em xin họ và tên đầy đủ ạ.")
    controller.on_bot_audio(bot.astype(np.int16).tobytes(), rate, complete=True)
    mic = np.concatenate([np.zeros(int(0.2 * rate)), 0.1 * bot, np.zeros(rate)])
    for k in range(len(bot) // hop):
        clock.advance(hop / rate)
        frame = mic[k * hop : (k + 1) * hop].astype(np.int16).tobytes()
        controller.on_caller_audio(frame, is_speech=False)
    controller.on_bot_stopped_speaking()

    assert controller.echo_path != "echo"
