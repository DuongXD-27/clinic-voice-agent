"""Người gọi đang nói (hoặc vừa nói) thì bot bắt đầu trả lời: lời người gọi không được mất."""

import asyncio

from speech.asr.vad.base import VadEvent
from speech.turn.controller import TurnController
from speech.turn.interruption import InterruptionController, InterruptionState
from speech.types import TranscriptEvent


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _FakeTTS:
    def __init__(self) -> None:
        self.cancel_calls = 0

    async def cancel(self) -> None:
        self.cancel_calls += 1


async def test_turn_started_before_the_bot_is_delivered_when_the_bot_stops() -> None:
    clock = _Clock()
    controller = TurnController(min_speech_ms=0, clock=clock)
    await controller.on_vad_event(VadEvent("speech_start"))
    clock.now = 1.0
    controller.on_bot_speaking_changed(True)
    await controller.on_transcript_event(
        TranscriptEvent(text="SINH NGÀY MƯỜI BỐN THÁNG BA", is_final=True)
    )
    await controller.on_vad_event(VadEvent("speech_end"))
    clock.now = 3.0
    controller.on_bot_speaking_changed(False)

    turn = await asyncio.wait_for(controller.get_turn(), timeout=1.0)
    assert turn.text == "SINH NGÀY MƯỜI BỐN THÁNG BA"


async def test_turn_started_while_the_bot_spoke_is_still_discarded_when_not_confirmed() -> None:
    clock = _Clock()
    controller = TurnController(min_speech_ms=0, clock=clock)
    controller.on_bot_speaking_changed(True)
    clock.now = 1.0
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="DẠ EM XIN NGHE", is_final=True))
    await controller.on_vad_event(VadEvent("speech_end"))
    clock.now = 2.0
    controller.on_bot_speaking_changed(False)

    assert not controller.has_pending_turn()


async def test_words_before_the_bot_survive_when_the_caller_resumes_during_the_bot() -> None:
    """Người gọi nói, dừng giữa lúc bot nói rồi nói tiếp: phần trước không bị lượt mới xoá."""
    clock = _Clock()
    controller = TurnController(min_speech_ms=0, clock=clock)
    await controller.on_vad_event(VadEvent("speech_start"))
    clock.now = 1.0
    controller.on_bot_speaking_changed(True)
    await controller.on_transcript_event(
        TranscriptEvent(text="TÔI TÊN LÀ NGUYỄN VĂN A", is_final=True)
    )
    clock.now = 1.5
    await controller.on_vad_event(VadEvent("speech_end"))
    clock.now = 3.0
    await controller.on_vad_event(VadEvent("speech_start"))
    clock.now = 4.0
    controller.on_bot_speaking_changed(False)

    turn = await asyncio.wait_for(controller.get_turn(), timeout=1.0)
    assert turn.text == "TÔI TÊN LÀ NGUYỄN VĂN A"


async def test_filler_before_the_bot_is_not_delivered() -> None:
    clock = _Clock()
    controller = TurnController(min_speech_ms=0, clock=clock)
    await controller.on_vad_event(VadEvent("speech_start"))
    clock.now = 1.0
    controller.on_bot_speaking_changed(True)
    await controller.on_transcript_event(TranscriptEvent(text="Ừ", is_final=True))
    await controller.on_vad_event(VadEvent("speech_end"))
    clock.now = 3.0
    await controller.on_vad_event(VadEvent("speech_start"))
    controller.on_bot_speaking_changed(False)

    assert not controller.has_pending_turn()


async def test_bot_starting_while_the_vad_is_in_speech_opens_a_candidate() -> None:
    interruption = InterruptionController(_FakeTTS(), min_speech_ms=0)
    await interruption.on_speech_started(VadEvent("speech_start"))
    interruption.on_bot_started_speaking("Dạ em xin nghe")

    assert interruption.state == InterruptionState.INTERRUPTION_CANDIDATE
    assert interruption.rearmed


async def test_bot_starting_after_the_caller_stopped_does_not_open_a_candidate() -> None:
    interruption = InterruptionController(_FakeTTS(), min_speech_ms=0)
    await interruption.on_speech_started(VadEvent("speech_start"))
    await interruption.on_speech_ended_without_confirmation()
    interruption.on_bot_started_speaking("Dạ em xin nghe")

    assert interruption.state == InterruptionState.BOT_SPEAKING
    assert not interruption.rearmed


async def test_rearmed_candidate_confirms_on_caller_words() -> None:
    tts = _FakeTTS()
    interruption = InterruptionController(tts, min_speech_ms=0)
    await interruption.on_speech_started(VadEvent("speech_start"))
    interruption.on_bot_started_speaking("Dạ em xin phép hỏi ngày sinh của anh chị")

    confirmed = await interruption.on_partial_transcript(
        TranscriptEvent(text="TÔI MUỐN ĐỔI LỊCH KHÁM", is_final=False)
    )

    assert confirmed
    assert tts.cancel_calls == 1


async def test_rearmed_candidate_on_echo_of_the_previous_sentence_does_not_cancel_the_bot() -> None:
    """Đuôi vọng câu bot trước giữ VAD "đang nói" sang câu sau: không được tự ngắt lời."""
    tts = _FakeTTS()
    interruption = InterruptionController(tts, min_speech_ms=0)
    interruption.on_bot_started_speaking("Anh chị cần em hỗ trợ gì ạ")
    await interruption.on_speech_started(VadEvent("speech_start"))
    interruption.on_bot_stopped_speaking()
    interruption.on_bot_started_speaking("Dạ em xin phép hỏi ngày sinh của anh chị")

    confirmed = await interruption.on_partial_transcript(
        TranscriptEvent(text="CẦN EM HỖ TRỢ GÌ Ạ", is_final=False)
    )

    assert interruption.rearmed
    assert not confirmed
    assert tts.cancel_calls == 0


def test_echoed_last_words_of_the_bot_question_are_not_a_caller_answer() -> None:
    from speech.turn.controller import strip_echo_prefix

    assert strip_echo_prefix("KHÔNG Ạ", "Anh chị muốn giữ theo lịch này không ạ?") == ""
    assert strip_echo_prefix("GÌ Ạ", "Anh chị cần em hỗ trợ gì ạ") == ""
    # Không trùng đuôi câu bot: là lời người gọi.
    assert strip_echo_prefix("KHÔNG", "Anh chị cần em hỗ trợ gì ạ") == "KHÔNG"
    assert strip_echo_prefix("CÓ Ạ", "Anh chị muốn giữ theo lịch này không ạ?") == "CÓ Ạ"


async def test_clear_confident_yes_filler_is_a_turn_even_when_fillers_are_dropped() -> None:
    """ "Ừ" to, rõ (0,997) phải tới engine; "Ừ" ASR nghe từ nhiễu (<= 0,93) vẫn bị bỏ."""
    from speech.audio.noise_tracker import NoiseEvidence

    for confidence, expected in ((0.997, True), (0.89, False)):
        controller = TurnController(min_speech_ms=0, drop_filler_words=True)
        await controller.on_vad_event(VadEvent("speech_start"))
        controller.on_evidence_updated(
            noise_evidence=NoiseEvidence(rms=3000.0, noise_floor=30.0, snr_db=40.0)
        )
        await controller.on_transcript_event(
            TranscriptEvent(text="Ừ", is_final=True, confidence=confidence)
        )
        assert controller.has_pending_turn() is expected


async def test_confident_hesitation_filler_is_still_dropped() -> None:
    controller = TurnController(min_speech_ms=0, drop_filler_words=True)
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="À", is_final=True, confidence=0.99))

    assert not controller.has_pending_turn()


async def test_confident_yes_filler_in_low_snr_is_dropped() -> None:
    from speech.audio.noise_tracker import NoiseEvidence

    controller = TurnController(min_speech_ms=0, drop_filler_words=True)
    await controller.on_vad_event(VadEvent("speech_start"))
    controller.on_evidence_updated(
        noise_evidence=NoiseEvidence(rms=60.0, noise_floor=50.0, snr_db=1.6)
    )
    await controller.on_transcript_event(TranscriptEvent(text="Ừ", is_final=True, confidence=0.99))

    assert not controller.has_pending_turn()


def test_held_confident_yes_counts_only_when_it_answers_the_bot_question() -> None:
    for answers_bot, expected in ((True, True), (False, False)):
        controller = TurnController(min_speech_ms=0, drop_filler_words=True)
        controller.on_held_barge_in("Ừ", confidence=0.997, speech_ms=600.0, answers_bot=answers_bot)
        assert controller.has_pending_turn() is expected


async def test_clear_short_reply_can_interrupt_the_bot() -> None:
    """ "OK" -> "OK EM" không bao giờ "hội tụ": câu trả lời ngắn rõ ràng vẫn phải ngắt được bot."""
    from speech.audio.noise_tracker import NoiseEvidence
    from speech.turn.validator import TurnValidator

    def controller_with(snr_db: float) -> tuple[InterruptionController, _FakeTTS, _Clock]:
        clock = _Clock()
        tts = _FakeTTS()
        controller = InterruptionController(tts, clock=clock, validator=TurnValidator())
        controller.on_bot_started_speaking("Dạ, em xin xác nhận lịch khám ngày 14 tháng 10 ạ.")
        controller.on_evidence_updated(
            noise_evidence=NoiseEvidence(rms=3000.0, noise_floor=30.0, snr_db=snr_db)
        )
        return controller, tts, clock

    for text, snr_db, expected in (
        ("OK EM", 36.5, True),
        ("XUỐNG", 46.0, False),
        ("OK EM", 8.0, False),
    ):
        controller, tts, clock = controller_with(snr_db)
        await controller.on_speech_started(VadEvent("speech_start"))
        clock.now = 0.72
        confirmed = await controller.on_partial_transcript(
            TranscriptEvent(text=text, is_final=False, confidence=0.9)
        )
        assert confirmed is expected, (text, snr_db)
        assert tts.cancel_calls == int(expected)


async def test_clear_yes_interrupts_only_while_the_bot_asks_its_final_question() -> None:
    """ "Ừ" lúc bot hỏi "…Anh chị đồng ý chứ ạ?" là câu trả lời; lúc bot đang giải thích thì không."""
    from speech.audio.noise_tracker import NoiseEvidence

    bot_text = "Em xin xác nhận lại lịch khám ngày 14 tháng 10. Anh chị đồng ý chứ ạ?"
    for started_at, expected in ((3.6, True), (0.5, False)):
        clock = _Clock()
        tts = _FakeTTS()
        controller = InterruptionController(tts, clock=clock)
        controller.on_bot_started_speaking(bot_text)
        controller.on_bot_audio(b"\x00\x00" * 16000 * 4, 16000, complete=True)  # 4 s audio
        controller.on_evidence_updated(
            noise_evidence=NoiseEvidence(rms=3000.0, noise_floor=60.0, snr_db=30.0)
        )
        clock.now = started_at
        await controller.on_speech_started(VadEvent("speech_start"))
        clock.now = started_at + 0.4
        confirmed = await controller.on_partial_transcript(
            TranscriptEvent(text="Ừ", is_final=False, confidence=0.97)
        )
        assert confirmed is expected, started_at


def test_yes_filler_without_asr_confidence_needs_a_clear_voice() -> None:
    """Gemini Live không trả độ tin cậy: "Ừ." chỉ qua khi giọng rõ hơn nền >= 15 dB."""
    from speech.audio.noise_tracker import NoiseEvidence
    from speech.turn.controller import is_confident_answer_filler

    def evidence(snr_db: float) -> NoiseEvidence:
        return NoiseEvidence(rms=1000.0, noise_floor=50.0, snr_db=snr_db)

    assert is_confident_answer_filler("Ừ.", None, evidence(25.0))
    assert not is_confident_answer_filler("Ừ.", None, evidence(9.0))
    assert not is_confident_answer_filler("Ừ.", None, None)
