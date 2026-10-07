import asyncio

import pytest

from speech.asr.vad.base import VadEvent
from speech.turn.controller import TurnController, is_meaningful_text, strip_echo_prefix
from speech.types import TranscriptEvent


async def _next_turn(controller: TurnController, timeout: float = 1.0):
    return await asyncio.wait_for(controller.get_turn(), timeout=timeout)


async def test_final_transcript_emits_turn_immediately() -> None:
    controller = TurnController(min_speech_ms=0)
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="tôi muốn đổi lịch", is_final=True))

    turn = await _next_turn(controller)

    assert turn.text == "tôi muốn đổi lịch"


async def test_vad_speech_end_before_final_waits_then_emits_via_timeout() -> None:
    controller = TurnController(max_wait_after_vad_end_ms=30, min_speech_ms=0)
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="tôi muốn đổi", is_final=False))
    await controller.on_vad_event(VadEvent("speech_end"))  # final ASR chưa tới

    turn = await _next_turn(controller, timeout=1.0)

    assert turn.text == "tôi muốn đổi"  # dùng partial cuối cùng, không treo vô hạn


async def test_final_arriving_before_timeout_cancels_timeout_and_uses_final_text() -> None:
    controller = TurnController(max_wait_after_vad_end_ms=200, min_speech_ms=0)
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="tôi muốn", is_final=False))
    await controller.on_vad_event(VadEvent("speech_end"))
    # final tới sớm hơn timeout — phải dùng text final, không phải partial cũ.
    await controller.on_transcript_event(
        TranscriptEvent(text="tôi muốn đổi lịch sang thứ sáu", is_final=True)
    )

    turn = await _next_turn(controller, timeout=1.0)

    assert turn.text == "tôi muốn đổi lịch sang thứ sáu"


async def test_pause_inside_utterance_does_not_emit_turn_early() -> None:
    """VAD speech_start giữa chừng reset candidate — pause giữa câu không tự chốt turn
    nếu vẫn còn nói tiếp sau đó (đây là việc của VAD phía trên: chỉ phát
    speech_end khi im lặng đủ dài, TurnController tin tưởng speech_end là thật)."""
    controller = TurnController(max_wait_after_vad_end_ms=50, min_speech_ms=0)
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="tôi muốn", is_final=False))
    # Chưa có speech_end (VAD coi đây vẫn là pause ngắn trong câu) -> không được có turn nào.
    await asyncio.sleep(0.1)
    assert controller._queue.empty()

    await controller.on_vad_event(VadEvent("speech_end"))
    await controller.on_transcript_event(TranscriptEvent(text="tôi muốn đổi lịch", is_final=True))
    turn = await _next_turn(controller)
    assert turn.text == "tôi muốn đổi lịch"


async def test_empty_partial_does_not_emit_turn() -> None:
    """Short noise: VAD trigger speech_start/speech_end nhưng ASR không nhận ra chữ nào
    (partial rỗng) -> không được tạo UserTurnCompleted giả."""
    controller = TurnController(max_wait_after_vad_end_ms=20)
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_vad_event(VadEvent("speech_end"))

    await asyncio.sleep(0.1)

    assert controller._queue.empty()
    assert controller._candidate.started_at is None


@pytest.mark.parametrize(
    "text",
    ["à", "ừ", "ờm", "Dạ", " ờ ", "Ừ.", "Dạ,", "...", "?!", "---", "  ,  "],
)
async def test_filler_word_or_punctuation_only_is_not_meaningful(text: str) -> None:
    assert is_meaningful_text(text) is False


@pytest.mark.parametrize(
    "text",
    ["có", "không", "ok", "tôi muốn đổi lịch", "được ạ", "à tôi hiểu rồi"],
)
async def test_real_short_reply_is_meaningful(text: str) -> None:
    """Câu trả lời 1-2 từ hợp lệ ("có"/"không"/"ok") hoặc câu có filler NHƯNG còn nội
    dung khác đi kèm ("à tôi hiểu rồi") không được lọc — chỉ lọc filler ĐƠN LẺ."""
    assert is_meaningful_text(text) is True


async def test_filler_word_final_transcript_does_not_emit_turn() -> None:
    """ASR decode ĐÚNG "ờm" (không phải hallucination) từ audio ngắn hợp lệ về mặt VAD
    lẫn min_decode_ms — vẫn không được chốt thành turn gửi lên core, vì "ờm" không mang
    nội dung hội thoại (core sẽ chỉ hỏi lại, trải nghiệm tệ hơn là bỏ qua)."""
    controller = TurnController(min_speech_ms=0)
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="ờm", is_final=True))

    await asyncio.sleep(0.05)

    assert controller._queue.empty()


async def test_punctuation_only_final_transcript_does_not_emit_turn() -> None:
    controller = TurnController(min_speech_ms=0)
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="...", is_final=True))

    await asyncio.sleep(0.05)

    assert controller._queue.empty()


async def test_meaningful_text_after_discarded_filler_still_emits() -> None:
    """Sau khi 1 turn bị lọc vì filler, user nói câu thật ở lượt speech_start MỚI vẫn
    phải hoạt động bình thường — bộ lọc không được làm controller kẹt trạng thái."""
    controller = TurnController(min_speech_ms=0)
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="ờm", is_final=True))
    await asyncio.sleep(0.05)
    assert controller._queue.empty()

    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="tôi muốn đổi lịch", is_final=True))

    turn = await _next_turn(controller)
    assert turn.text == "tôi muốn đổi lịch"


async def test_continuous_speech_without_speech_end_never_times_out() -> None:
    """Nói liên tục dài: chỉ có speech_start, nhiều partial, không có speech_end/final
    trong suốt thời gian dài -> không được tự ý chốt turn giữa chừng."""
    controller = TurnController(max_wait_after_vad_end_ms=20)
    await controller.on_vad_event(VadEvent("speech_start"))
    for i in range(20):
        await controller.on_transcript_event(TranscriptEvent(text=f"phần {i}", is_final=False))
        await asyncio.sleep(0.01)

    assert controller._queue.empty()


async def test_bot_speaking_suppresses_turn_while_bot_is_speaking() -> None:
    controller = TurnController(max_wait_after_vad_end_ms=20)
    controller.on_bot_speaking_changed(True)
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="đợi chút", is_final=True))

    await asyncio.sleep(0.05)
    assert controller._queue.empty(), "không được chốt turn khi bot đang nói"


async def test_candidate_accumulated_while_bot_speaking_is_discarded_on_stop() -> None:
    """Audio nhận trong lúc bot nói (echo/dư âm qua mic, không phải barge-in thật đã
    được InterruptionController xác nhận) không được tự động trở thành turn ngay khi
    bot vừa dứt lời — nếu không sẽ tạo turn giả gây transfer/hành vi sai ngay sau câu
    chào (bug thật đã xảy ra: bot chào xong rồi transfer ngay dù user chưa kịp nói)."""
    controller = TurnController(max_wait_after_vad_end_ms=20)
    controller.on_bot_speaking_changed(True)
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="tiếng vọng của bot", is_final=True))

    controller.on_bot_speaking_changed(False)

    await asyncio.sleep(0.05)
    assert controller._queue.empty(), "candidate tích luỹ lúc bot nói phải bị bỏ, không emit"


async def test_confirmed_barge_in_candidate_is_preserved_on_stop() -> None:
    controller = TurnController(max_wait_after_vad_end_ms=20, min_speech_ms=0)
    controller.on_bot_speaking_changed(True)
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="dừng lại", is_final=True))

    controller.on_bot_speaking_changed(False, preserve_candidate=True)

    turn = await _next_turn(controller)
    assert turn.text == "dừng lại"


async def test_confirmed_barge_in_turn_drops_echoed_bot_words() -> None:
    """Đo 07/10 (barge_in_eval, echo qua kênh điện thoại): lượt ngắt lời gửi engine là
    "ANH CHỊ CHẮC CHẮN MUỐN HỦY TÔI LÀ NGUYỄN VĂN A" — engine đọc ra ý "hủy" từ chính câu bot."""
    controller = TurnController(max_wait_after_vad_end_ms=20, min_speech_ms=0)
    controller.on_bot_speaking_changed(True)
    await controller.on_vad_event(VadEvent("speech_start"))
    controller.expect_echo("Anh chị chắc chắn muốn hủy lịch khám này đúng không ạ?")
    await controller.on_transcript_event(
        TranscriptEvent(text="ANH CHỊ CHẮC CHẮN MUỐN HỦY TÔI LÀ NGUYỄN VĂN A", is_final=True)
    )

    controller.on_bot_speaking_changed(False, preserve_candidate=True)

    turn = await _next_turn(controller)
    assert turn.text == "TÔI LÀ NGUYỄN VĂN A"


@pytest.mark.parametrize(
    ("text", "bot_text", "expected"),
    [
        # Câu bot vọng lại nguyên câu (ASR chép sai vài chữ) -> không còn gì của người gọi.
        ("DẠ VIN BÁCH XIN NGHE EM LÀ TRỢ LÝ", "Dạ Vinmec xin nghe, em là trợ lý ảo AI", ""),
        (
            "DẠ VIN BÁCH XIN NGHE NGÀY MƯỜI BỐN THÁNG BA",
            "Dạ Vinmec xin nghe, em là trợ lý ảo AI",
            "NGÀY MƯỜI BỐN THÁNG BA",
        ),
        # Lời người gọi tình cờ có vài từ của câu bot nhưng không thành khối: giữ nguyên.
        ("Anh muốn", "Dạ, anh chị muốn đổi lịch hay hủy lịch khám ạ?", "Anh muốn"),
        ("ANH MUỐN EM ĐẶT PHÒNG", "Dạ anh chị cho em xin họ tên", "ANH MUỐN EM ĐẶT PHÒNG"),
        ("tôi muốn hủy", "", "tôi muốn hủy"),
    ],
)
def test_strip_echo_prefix(text: str, bot_text: str, expected: str) -> None:
    assert strip_echo_prefix(text, bot_text) == expected


async def test_user_can_speak_normally_right_after_bot_stops() -> None:
    """Sau khi candidate cũ bị discard, user nói bình thường (speech_start mới) MUỘN sau
    khi bot dừng (đã qua khỏi post-bot echo guard) vẫn phải tạo turn được — reset không
    được làm hỏng luồng turn tiếp theo."""
    controller = TurnController(max_wait_after_vad_end_ms=20, min_speech_ms=0)
    controller.on_bot_speaking_changed(True)
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="tiếng vọng", is_final=True))
    controller.on_bot_speaking_changed(False)
    await asyncio.sleep(0.6)  # vượt post_bot_guard_ms mặc định (500ms) — không còn là echo

    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="tôi muốn đổi lịch", is_final=True))

    turn = await _next_turn(controller)
    assert turn.text == "tôi muốn đổi lịch"


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


async def test_short_noise_below_min_speech_ms_is_discarded_via_timeout() -> None:
    """Backchannel/tiếng động ngắn (ho, gõ bàn): VAD+ASR đồng thuận có "speech" và text
    hợp lệ, nhưng duration chưa đủ min_speech_ms khi timeout hết hạn -> phải bị discard,
    không emit turn rác (đúng vấn đề user báo: "dạ dạ" liên tục do nhiễu ngoài)."""
    clock = _FakeClock()
    controller = TurnController(max_wait_after_vad_end_ms=20, min_speech_ms=250, clock=clock)
    await controller.on_vad_event(VadEvent("speech_start"))
    clock.advance(0.05)  # chỉ 50ms — dưới ngưỡng 250ms
    await controller.on_transcript_event(TranscriptEvent(text="ừm", is_final=True))

    await asyncio.sleep(0.1)  # đợi _timeout_flush thật chạy (asyncio.sleep nội bộ không mock)

    assert controller._queue.empty(), "turn ngắn hơn min_speech_ms phải bị discard"


async def test_speech_reaching_min_duration_is_emitted() -> None:
    """Turn đủ dài (>= min_speech_ms) vẫn phải được chốt bình thường — min_speech_ms chỉ
    lọc turn NGẮN, không được chặn hội thoại thật."""
    clock = _FakeClock()
    controller = TurnController(max_wait_after_vad_end_ms=20, min_speech_ms=250, clock=clock)
    await controller.on_vad_event(VadEvent("speech_start"))
    clock.advance(0.3)  # vượt ngưỡng 250ms
    await controller.on_transcript_event(TranscriptEvent(text="tôi muốn đổi lịch", is_final=True))

    turn = await _next_turn(controller)

    assert turn.text == "tôi muốn đổi lịch"


async def test_echo_right_after_bot_stops_is_discarded() -> None:
    """Bug thật: user hoàn toàn im lặng, nhưng dư âm/tiếng vọng (loa ngoài, echo
    cancellation không hoàn hảo) ngay sau khi bot dứt câu chào bị WebRTC VAD coi là
    speech_start thật, ASR hallucinate ra 1 cụm từ "có nghĩa" -> turn giả, transfer sai.
    Speech bắt đầu trong post_bot_guard_ms và kết thúc ngắn (không kéo dài thêm) phải bị
    discard, không được chốt thành turn."""
    clock = _FakeClock()
    controller = TurnController(
        max_wait_after_vad_end_ms=20, min_speech_ms=0, post_bot_guard_ms=500, clock=clock
    )
    controller.on_bot_speaking_changed(False)  # bot vừa dứt lời tại clock=0.0
    clock.advance(0.05)  # echo xuất hiện 50ms sau — vẫn trong guard window
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(
        TranscriptEvent(text="tư đứng một điểm thời phụ", is_final=True)
    )

    await asyncio.sleep(0.05)
    assert controller._queue.empty(), "echo ngắn ngay sau bot dứt lời phải bị discard"


async def test_real_speech_sustained_past_guard_after_bot_stops_is_emitted() -> None:
    """Nếu user THẬT SỰ bắt đầu nói ngay lúc echo guard còn hiệu lực và tiếp tục nói đủ
    lâu (vượt phần guard còn lại cộng dồn vào min_speech_ms), turn vẫn phải được chốt —
    guard không được nuốt mất câu nói thật của user, chỉ lọc echo thoảng qua."""
    clock = _FakeClock()
    controller = TurnController(
        max_wait_after_vad_end_ms=20, min_speech_ms=0, post_bot_guard_ms=500, clock=clock
    )
    controller.on_bot_speaking_changed(False)  # bot vừa dứt lời tại clock=0.0
    clock.advance(0.05)  # user bắt đầu nói 50ms sau — vẫn trong guard window
    await controller.on_vad_event(VadEvent("speech_start"))
    clock.advance(0.6)  # tiếp tục nói, vượt hẳn phần guard còn lại (~450ms)
    await controller.on_transcript_event(TranscriptEvent(text="tôi muốn đổi lịch", is_final=True))

    turn = await _next_turn(controller)
    assert turn.text == "tôi muốn đổi lịch"


async def test_speech_start_well_after_guard_window_is_unaffected() -> None:
    """speech_start xảy ra SAU khi post_bot_guard_ms đã hết hạn hoàn toàn không bị ảnh
    hưởng gì — hành vi min_speech_ms bình thường, không có guard_extra_s nào cộng thêm."""
    clock = _FakeClock()
    controller = TurnController(
        max_wait_after_vad_end_ms=20, min_speech_ms=0, post_bot_guard_ms=500, clock=clock
    )
    controller.on_bot_speaking_changed(False)  # bot vừa dứt lời tại clock=0.0
    clock.advance(0.6)  # đã vượt hẳn guard window (500ms)
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="tôi muốn đổi lịch", is_final=True))

    turn = await _next_turn(controller)
    assert turn.text == "tôi muốn đổi lịch"


async def test_final_before_min_duration_waits_and_can_still_be_discarded() -> None:
    """Final ASR đến RẤT sớm (trước cả khi đủ min_speech_ms) không được emit ngay —
    phải chờ; nếu speech thực sự ngắn (không có thêm audio), timeout sẽ discard nó."""
    clock = _FakeClock()
    controller = TurnController(max_wait_after_vad_end_ms=20, min_speech_ms=250, clock=clock)
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="à", is_final=True))

    # final đã tới nhưng chưa đủ min_speech_ms -> không được có turn ngay lập tức.
    assert controller._queue.empty()

    await asyncio.sleep(0.1)  # hết hạn max_wait_after_vad_end_ms mà vẫn ngắn -> discard
    assert controller._queue.empty()


class _FixedValidator:
    """Validator giả trả về đúng 1 quyết định cố định — cô lập test khỏi logic thật của
    TurnValidator, chỉ kiểm tra wiring TurnController đúng."""

    def __init__(self, decision) -> None:
        self.decision = decision
        self.calls = 0

    def evaluate(self, candidate_text, **kwargs):
        self.calls += 1
        return self.decision


async def test_validator_drop_discards_candidate() -> None:
    from speech.turn.validator import ValidationDecision

    validator = _FixedValidator(ValidationDecision.DROP)
    controller = TurnController(min_speech_ms=0, validator=validator)
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="đây", is_final=True))

    assert controller._queue.empty()
    assert validator.calls == 1


async def test_validator_accept_emits_turn() -> None:
    from speech.turn.validator import ValidationDecision

    validator = _FixedValidator(ValidationDecision.ACCEPT)
    controller = TurnController(min_speech_ms=0, validator=validator)
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="tôi muốn đổi lịch", is_final=True))

    turn = await _next_turn(controller)
    assert turn.text == "tôi muốn đổi lịch"


async def test_validator_wait_at_final_falls_back_to_accepting() -> None:
    """WAIT đúng lúc final đã tới (is_last_chance=True) -> không có event nào khác sẽ
    tới cho candidate này -> TurnController PHẢI tự chốt (fallback), không được treo turn
    vô thời hạn chỉ vì Validator còn phân vân."""
    from speech.turn.validator import ValidationDecision

    validator = _FixedValidator(ValidationDecision.WAIT)
    controller = TurnController(min_speech_ms=0, validator=validator)
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="tôi muốn đổi lịch", is_final=True))

    turn = await _next_turn(controller)
    assert turn.text == "tôi muốn đổi lịch"


async def test_validator_wait_after_barge_in_preserve_does_not_emit_yet() -> None:
    """WAIT khi KHÔNG phải last chance (candidate giữ lại sau barge-in, còn có thể có
    event mới tới) -> không emit ngay, nhưng cũng không raise/crash."""
    from speech.turn.validator import ValidationDecision

    validator = _FixedValidator(ValidationDecision.WAIT)
    controller = TurnController(min_speech_ms=0, validator=validator)
    await controller.on_vad_event(VadEvent("speech_start"))
    controller.on_bot_speaking_changed(True)
    await controller.on_vad_event(VadEvent("speech_start"))  # candidate mới trong lúc bot nói
    await controller.on_transcript_event(TranscriptEvent(text="dạ đúng rồi", is_final=False))
    controller.on_bot_speaking_changed(False, preserve_candidate=True)

    assert controller._queue.empty()

    # Final tới sau đó -> is_last_chance=True -> validator WAIT vẫn phải fallback ACCEPT.
    await controller.on_transcript_event(TranscriptEvent(text="dạ đúng rồi", is_final=True))
    turn = await _next_turn(controller)
    assert turn.text == "dạ đúng rồi"


async def test_no_validator_keeps_old_behavior() -> None:
    controller = TurnController(min_speech_ms=0)
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="tôi muốn đổi lịch", is_final=True))

    turn = await _next_turn(controller)
    assert turn.text == "tôi muốn đổi lịch"


async def test_silence_elapsed_counts_from_bot_stop_and_last_vad_activity() -> None:
    """CallBridge gửi lượt im lặng dựa trên số này — phải tính từ mốc muộn nhất giữa lúc bot
    dứt lời và lúc VAD còn thấy tiếng, và không tính khi đang có câu dở."""
    clock = _FakeClock()
    controller = TurnController(clock=clock, max_wait_after_vad_end_ms=20, min_speech_ms=250)
    assert controller.silence_elapsed_s() is None  # chưa có mốc nào

    controller.on_bot_speaking_changed(True)
    assert controller.silence_elapsed_s() is None  # bot đang nói
    controller.on_bot_speaking_changed(False)
    clock.advance(2.0)
    assert controller.silence_elapsed_s() == pytest.approx(2.0)

    await controller.on_vad_event(VadEvent("speech_start"))
    clock.advance(0.1)
    assert controller.silence_elapsed_s() is None  # đang nói dở
    await controller.on_vad_event(VadEvent("speech_end"))
    await asyncio.sleep(0.05)  # 100 ms < min_speech_ms: câu bị huỷ sau timeout
    clock.advance(1.0)
    assert controller.silence_elapsed_s() == pytest.approx(1.0)


async def test_remote_final_for_earlier_segment_waits_for_later_segment() -> None:
    """ASR remote: final của đoạn 1 tới khi đoạn 2 đã mở; lượt chờ cả final của đoạn 2 rồi
    ghép theo thứ tự đoạn."""
    controller = TurnController(min_speech_ms=0)
    controller.set_asr_final_required(True)
    await controller.on_vad_event(VadEvent("speech_start"))
    controller.expect_final(1)
    await controller.on_vad_event(VadEvent("speech_end"))
    assert controller.continues_turn() is True  # đoạn 1 chưa có final
    await controller.on_vad_event(VadEvent("speech_start"))
    controller.expect_final(2)
    await controller.on_transcript_event(
        TranscriptEvent(text="sinh ngày", is_final=False, segment_id=2)
    )
    await controller.on_transcript_event(
        TranscriptEvent(text="Anh tên là A.", is_final=True, segment_id=1)
    )
    await controller.on_vad_event(VadEvent("speech_end"))
    await asyncio.sleep(0.02)
    assert controller._queue.empty()

    await controller.on_transcript_event(
        TranscriptEvent(text="sinh ngày 14.", is_final=True, segment_id=2)
    )
    assert (await _next_turn(controller)).text == "Anh tên là A. sinh ngày 14."


@pytest.mark.parametrize("text", ["Ừ.", "ờ", "dạ", "à"])
async def test_single_syllable_reply_is_a_turn_when_filler_words_are_kept(text: str) -> None:
    """Engine hiểu được "ừ/ờ" (đồng ý), "dạ" (hỏi lại), "à" (đang nghĩ) — tầng speech không bỏ."""
    controller = TurnController(min_speech_ms=0, drop_filler_words=False)
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text=text, is_final=True))

    turn = await _next_turn(controller)

    assert turn.text == text


async def test_punctuation_only_is_dropped_even_when_filler_words_are_kept() -> None:
    controller = TurnController(min_speech_ms=0, drop_filler_words=False)
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="...", is_final=True))

    await asyncio.sleep(0.05)

    assert controller._queue.empty()


async def test_filler_heard_while_bot_was_speaking_is_still_dropped() -> None:
    """ "ừ" chen lúc bot đang nói là tiếng đệm ("tôi đang nghe"), không phải câu trả lời."""
    controller = TurnController(min_speech_ms=0, drop_filler_words=False)
    controller.on_bot_speaking_changed(True)
    await controller.on_vad_event(VadEvent("speech_start"))
    controller.on_bot_speaking_changed(False)
    controller.expect_echo("Anh chị có đến khám được theo lịch này không ạ?")
    await controller.on_transcript_event(TranscriptEvent(text="Ừ", is_final=True))

    await asyncio.sleep(0.05)

    assert controller._queue.empty()


if __name__ == "__main__":
    pytest.main([__file__])


async def _segment(controller: TurnController, segment_id: int, text: str) -> None:
    """Một câu của ASR remote (Gemini server VAD): final tới trước speech_end."""
    await controller.on_vad_event(VadEvent("speech_start"))
    controller.expect_final(segment_id)
    await controller.on_transcript_event(
        TranscriptEvent(text=text, is_final=True, segment_id=segment_id)
    )
    await controller.on_vad_event(VadEvent("speech_end"))


async def test_merge_window_joins_continuation_into_one_turn() -> None:
    controller = TurnController(min_speech_ms=0, merge_window_ms=150)
    controller.set_asr_final_required(True)
    await _segment(controller, 1, "14 tháng 3")
    await asyncio.sleep(0.05)  # ầm ừ, rồi nói tiếp trong cửa sổ gộp
    await _segment(controller, 2, "năm 1978")

    turn = await _next_turn(controller)

    assert turn.text == "14 tháng 3 năm 1978"
    assert controller._queue.empty()


async def test_merge_window_commits_after_window_without_continuation() -> None:
    controller = TurnController(min_speech_ms=0, merge_window_ms=50)
    controller.set_asr_final_required(True)
    await _segment(controller, 1, "tôi muốn đặt lịch")

    assert controller._queue.empty()  # chưa chốt ngay
    turn = await _next_turn(controller, timeout=0.5)
    assert turn.text == "tôi muốn đặt lịch"


async def test_without_merge_window_continuation_is_a_new_turn() -> None:
    controller = TurnController(min_speech_ms=0)
    controller.set_asr_final_required(True)
    await _segment(controller, 1, "14 tháng 3")
    await _segment(controller, 2, "năm 1978")

    assert (await _next_turn(controller)).text == "14 tháng 3"
    assert (await _next_turn(controller)).text == "năm 1978"
