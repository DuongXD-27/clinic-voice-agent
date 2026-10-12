"""Người gọi nói chen lúc bot nói: bot dừng theo bằng chứng — chữ có nghĩa, nói đủ lâu, giọng rõ
hơn nền, không phải tiếng bot vọng lại — không phụ thuộc may rủi hai partial ASR liên tiếp giống
nhau (validator CONVERGING).

Log cuộc gọi 08-09/10 (temp/livekit-logs): 76/155 lần người gọi nói chen có partial mà bot vẫn nói
tiếp; lý do từ chối nhiều nhất là validator WAIT — partial GipFormer decode lại cả câu nên hiếm khi
giống lần trước, và không được phát lại khi chữ không đổi.
"""

import numpy as np
import pytest

from speech.asr.evidence import StabilityVerdict
from speech.asr.vad.base import VadEvent
from speech.audio.noise_tracker import NoiseEvidence
from speech.turn.interruption import InterruptionController, InterruptionState
from speech.turn.validator import TurnValidator
from speech.types import TranscriptEvent

# Câu bot không chứa chữ nào của các câu người gọi dưới đây (trừ khi test cố ý dùng chữ bot).
_BOT = "Dạ, em xin phép đọc các khung giờ còn trống trong ngày mai ạ."
_QUESTION = "Anh chị có đồng ý với khung giờ này không ạ?"
_RATE = 16_000
_FRAME_S = 0.03


class _FakeTTS:
    def __init__(self) -> None:
        self.cancel_calls = 0

    async def cancel(self) -> None:
        self.cancel_calls += 1


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _EchoInMic(InterruptionController):
    """Mic có tiếng bot vọng lại (AEC không khử hết) — phần đo âm thanh có test riêng."""

    def _echo_evidence(self) -> tuple[float, float]:
        return 1.0, 1.0


def _controller(
    bot: str = _BOT, snr_db: float = 25.0, cls=InterruptionController, **kwargs
) -> tuple[InterruptionController, _FakeTTS, _Clock]:
    clock = _Clock()
    tts = _FakeTTS()
    controller = cls(tts, clock=clock, validator=TurnValidator(), min_snr_db=0.0, **kwargs)
    controller.on_bot_started_speaking(bot)
    controller.on_evidence_updated(
        noise_evidence=NoiseEvidence(rms=3000.0, noise_floor=30.0, snr_db=snr_db)
    )
    return controller, tts, clock


async def _partial(controller: InterruptionController, text: str, confidence=0.9) -> bool:
    return await controller.on_partial_transcript(
        TranscriptEvent(text=text, is_final=False, confidence=confidence)
    )


@pytest.mark.parametrize(
    "text", ["TỪ XƯA ĐẾN GIỜ", "EM CÓ THỂ", "Không phải lúc nào cũng", "MÌNH ƠI KHÔNG CÓ"]
)
async def test_caller_words_interrupt_on_the_first_partial(text: str) -> None:
    """Log 09/10: mỗi câu chỉ có một partial (hoặc các partial không giống nhau) nên validator
    WAIT tới khi VAD hết câu — bot nói tiếp hết câu."""
    controller, tts, clock = _controller()
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.now = 0.42

    assert await _partial(controller, text)
    assert controller.state == InterruptionState.INTERRUPTED
    assert tts.cancel_calls == 1


async def test_words_heard_early_confirm_on_a_later_speech_frame_without_a_new_partial() -> None:
    """GipFormer không phát lại partial khi chữ không đổi: partial tới trước `_WORDS_MIN_S` thì
    phải xét lại khi VAD còn nghe tiếng nói, nếu không bot nói tiếp dù người gọi vẫn đang nói."""
    controller, tts, clock = _controller()
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.now = 0.3
    assert not await _partial(controller, "hết luôn")
    clock.now = 0.35
    assert not await controller.on_speech_frame()

    clock.now = 0.45
    assert await controller.on_speech_frame()
    assert tts.cancel_calls == 1


async def test_speech_frames_never_confirm_text_that_failed_for_another_reason() -> None:
    controller, tts, clock = _controller(snr_db=7.7)
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.now = 0.5
    assert not await _partial(controller, "CÓ AI THẤY")

    clock.now = 3.0
    assert not await controller.on_speech_frame()
    assert tts.cancel_calls == 0


async def test_speech_frames_without_any_partial_do_not_confirm() -> None:
    """Không có đường xác nhận thuần thời lượng: tiếng quạt/nhiễu kéo dài không cắt lời bot."""
    controller, tts, clock = _controller()
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.now = 5.0

    assert not await controller.on_speech_frame()
    assert controller.state == InterruptionState.INTERRUPTION_CANDIDATE


async def test_a_single_word_that_is_not_an_answer_waits_for_more_words() -> None:
    controller, tts, clock = _controller()
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.now = 0.42
    assert not await _partial(controller, "MÌNH")
    clock.now = 2.0
    assert not await controller.on_speech_frame()

    assert await _partial(controller, "MÌNH ƠI")
    assert tts.cancel_calls == 1


async def test_a_single_word_never_interrupts_even_when_two_partials_converge() -> None:
    """barge_in_eval 10/10: người gọi nói "OK", GipFormer nghe "ĐẤY" -> "ĐÂY" — hai partial hội
    tụ, trước đây bot bị ngắt bởi một chữ nghe nhầm."""
    controller, tts, clock = _controller()
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.now = 0.7
    controller.on_evidence_updated(stability=StabilityVerdict.CONVERGING)

    assert not await _partial(controller, "ĐÂY", confidence=0.62)
    assert tts.cancel_calls == 0


@pytest.mark.parametrize(
    ("text", "confidence", "confirmed"),
    [
        ("ĐÚNG KHÔNG", 0.52, False),  # GipFormer nghe "Ừ" thật (barge_in_eval 10/10)
        ("VIỆT NAM", 0.9, True),
        ("hết luôn", None, True),  # Gemini Live không trả độ tin cậy
        ("ANH MUỐN ĐỔI LỊCH", 0.52, True),  # câu dài: chữ đủ là bằng chứng
    ],
)
async def test_two_words_need_a_confident_asr_but_longer_speech_does_not(
    text: str, confidence, confirmed: bool
) -> None:
    controller, tts, clock = _controller()
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.now = 0.6

    assert await _partial(controller, text, confidence=confidence) is confirmed


@pytest.mark.parametrize("text", ["Ừ", "DẠ", "À", "ỜM"])
async def test_backchannel_fillers_never_interrupt(text: str) -> None:
    controller, tts, clock = _controller()
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.now = 0.6
    assert not await _partial(controller, text)
    clock.now = 2.0
    assert not await controller.on_speech_frame()
    assert tts.cancel_calls == 0


@pytest.mark.parametrize(("text", "snr_db"), [("CÓ AI THẤY", 7.7), ("phòng ngủ", 6.3)])
async def test_words_from_a_voice_barely_above_the_background_do_not_interrupt(
    text: str, snr_db: float
) -> None:
    """Log 09/10: người khác nói phía sau, SNR 6-8 dB; lần người gọi chen lời SNR 15-35 dB."""
    controller, tts, clock = _controller(snr_db=snr_db)
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.now = 1.0

    assert not await _partial(controller, text)
    assert tts.cancel_calls == 0


async def test_words_without_noise_evidence_need_converging_partials() -> None:
    """Có validator mà chưa có SNR thì không biết giọng rõ hơn nền hay không: như trước."""
    clock = _Clock()
    controller = InterruptionController(_FakeTTS(), clock=clock, validator=TurnValidator())
    controller.on_bot_started_speaking(_BOT)
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.now = 0.6

    assert not await _partial(controller, "TÔI MUỐN ĐỔI LỊCH")


async def test_long_partial_is_not_dropped_for_short_partials_that_flipped_before_it() -> None:
    """Log 09/10: "HAI TỶ" -> "HAI THẾ" -> "HAI TỶ" (GipFormer decode lại phần đầu câu) rồi
    "CÓ AI THẤY KHÔNG" vẫn bị DROP vì cửa sổ độ ổn định còn giữ các chữ ngắn kia."""
    controller, tts, clock = _controller()
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.now = 1.0
    controller.on_evidence_updated(stability=StabilityVerdict.OSCILLATING)

    assert not await _partial(controller, "HAI TỶ")  # chữ ngắn lật qua lại: mẫu ảo giác
    assert await _partial(controller, "CÓ AI THẤY KHÔNG")


async def test_a_new_candidate_does_not_inherit_the_previous_candidate_stability() -> None:
    controller, tts, clock = _controller()
    await controller.on_speech_started(VadEvent("speech_start"))
    controller.on_evidence_updated(stability=StabilityVerdict.OSCILLATING)
    await controller.on_speech_ended_without_confirmation()
    clock.now = 2.0
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.now = 2.5

    assert await _partial(controller, "ĐÚNG RỒI EM")


async def test_on_a_line_with_echo_words_alone_still_need_converging_partials() -> None:
    """Đường truyền có tiếng bot vọng lại: chữ có thể là tiếng bot ASR chép sai mà lọt so khớp
    vọng (đuôi câu "…HỦY LỊCH HẢ", 07/10) — giữ đòi partial hội tụ như trước."""
    controller, tts, clock = _controller(cls=_EchoInMic)
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.now = 0.6
    assert not await _partial(controller, "TÔI MUỐN ĐỔI LỊCH")

    controller.on_evidence_updated(stability=StabilityVerdict.CONVERGING)
    assert await _partial(controller, "TÔI MUỐN ĐỔI LỊCH SANG")


def _voice(seconds: float, seed: int = 1) -> np.ndarray:
    """Giọng giả: nhiễu có đường bao lên xuống theo âm tiết (60 ms, độ to ngẫu nhiên)."""
    rng = np.random.default_rng(seed)
    envelope = np.repeat(rng.uniform(0.05, 1.0, int(seconds / 0.06)), int(0.06 * _RATE))
    return (rng.normal(0.0, 3000.0, envelope.size) * envelope).astype(np.int16)


def _hear_quiet_mic(controller: InterruptionController, clock: _Clock, seconds: float) -> None:
    """Bot đang phát, mic chỉ có nhiễu nền nhỏ (AEC trình duyệt đã khử tiếng bot)."""
    rng = np.random.default_rng(2)
    for _ in range(round(seconds / _FRAME_S)):
        clock.now += _FRAME_S
        frame = rng.normal(0.0, 30.0, int(_FRAME_S * _RATE)).astype(np.int16)
        controller.on_caller_audio(frame.tobytes(), is_speech=False)


async def _answer_after(
    seconds: float, *, policy: str = "acoustic", text: str = "ĐỒNG Ý"
) -> tuple[bool, InterruptionController]:
    """Bot đọc `_QUESTION` (4 s audio), mic im `seconds` giây rồi người gọi trả lời bằng chữ của
    chính câu bot."""
    controller, _tts, clock = _controller(bot=_QUESTION, echo_policy=policy)
    controller.on_bot_audio(_voice(4.0).tobytes(), _RATE, complete=True)
    _hear_quiet_mic(controller, clock, seconds)
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.now += 0.45
    return await _partial(controller, text), controller


async def test_caller_answering_with_the_bot_words_interrupts_once_the_line_shows_no_echo() -> None:
    """Log 08-09/10: "CHỊ", "OK ANH ĐỒNG Ý", "CHO ANH CHỌN KHUNG" bị coi là tiếng bot vọng lại chỉ
    vì trùng chữ câu bot, trên cuộc gọi web không hề có vọng (AEC trình duyệt). Bot phát 2 s mà
    VAD không mở ứng viên nào: tiếng bot không vọng tới mức thành chữ."""
    confirmed, _ = await _answer_after(2.5)

    assert confirmed


async def test_bot_words_heard_before_the_line_is_known_are_still_treated_as_echo() -> None:
    confirmed, _ = await _answer_after(0.5)

    assert not confirmed


async def test_a_candidate_early_in_the_sentence_gives_no_evidence_against_echo() -> None:
    """Tiếng bot vọng lại mở ứng viên ngay đầu câu (barge_in_eval: 12/12 câu, trễ 0,09 s) — câu đó
    không chứng minh được gì."""
    controller, _tts, clock = _controller(bot=_QUESTION)
    controller.on_bot_audio(_voice(4.0).tobytes(), _RATE, complete=True)
    _hear_quiet_mic(controller, clock, 0.3)
    await controller.on_speech_started(VadEvent("speech_start"))
    await controller.on_speech_ended_without_confirmation()
    _hear_quiet_mic(controller, clock, 2.5)
    await controller.on_speech_started(VadEvent("speech_start"))
    clock.now += 0.45

    assert not await _partial(controller, "ĐỒNG Ý")


async def test_echo_heard_later_in_the_call_overrides_the_evidence_of_no_echo() -> None:
    confirmed, controller = await _answer_after(2.5, text="KHUNG GIỜ NÀY")
    assert confirmed

    controller._call_has_echo = True  # probe nghe thấy vọng ở câu sau
    controller.on_bot_started_speaking(_QUESTION)
    await controller.on_speech_started(VadEvent("speech_start"))
    controller._clock.now += 0.6
    controller.on_evidence_updated(stability=StabilityVerdict.CONVERGING)

    assert not await _partial(controller, "KHUNG GIỜ NÀY")


@pytest.mark.parametrize("policy", ["text", "three_state"])
async def test_conservative_echo_policies_keep_comparing_with_the_bot_words(policy: str) -> None:
    confirmed, _ = await _answer_after(2.5, policy=policy)

    assert not confirmed


async def test_caller_still_talking_as_the_next_sentence_starts_interrupts_without_echo() -> None:
    """Người gọi nói tiếp lúc bot bắt đầu câu sau (ứng viên mở lại), nhắc lại chữ câu bot trước:
    đường truyền đã cho thấy không vọng thì đó là lời người gọi, không phải đuôi vọng câu trước."""
    _, controller = await _answer_after(2.5)  # câu đầu: không vọng, người gọi trả lời
    controller.on_bot_stopped_speaking()
    await controller.on_speech_started(VadEvent("speech_start"))
    controller.on_bot_started_speaking("Dạ, em xin phép đặt lịch theo khung giờ đó.")
    assert controller.rearmed
    controller._clock.now += 0.5

    assert await _partial(controller, "KHUNG GIỜ NÀY KHÔNG")
