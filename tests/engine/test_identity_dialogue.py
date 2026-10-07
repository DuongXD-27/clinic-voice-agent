"""T-02: luồng hỏi và xác minh danh tính qua orchestrator thật + FakeClinicAPI.

Hỏi mở tên / ngày sinh, nhận phần còn thiếu, ngày sinh không hợp lệ, xin nhắc lại, giới hạn hỏi lại,
từ chối cung cấp, tra cứu lượt 0 thất bại. Mọi lượt trước khi xác minh xong không được lộ lịch (SF-03).
"""

from typing import Optional

import pytest

from callbot.engine import BotAction, CallerInput, CallStart, create_orchestrator
from callbot.engine.dialogue import templates as t
from callbot.engine.errors import OutboundStartFailed
from callbot.engine.policy.policy_engine import LOOKUP_TRANSFER_REASON
from callbot.engine.verification import LookupStatus, PrepareResult
from callbot.engine.verification.names import normalize_text, strip_diacritics
from clinic_mock_sim import FakeClinicAPI

SILENCE = None
NAME, DOB = "Nguyễn Văn A", "14/03/1978"
# Chi tiết lịch (Listing 3) và hồ sơ chuẩn: không được xuất hiện trước khi xác minh xong
PROTECTED = ("14 tháng 10", "nội tổng quát", "9 giờ", "nguyễn văn a", "1978", "14 tháng 3")


def _outbound(call_id: str) -> CallStart:
    return CallStart(call_id=call_id, direction="outbound", appointment_id="apt_00417")


def _inbound(call_id: str, phone: Optional[str] = "0912345600") -> CallStart:
    return CallStart(call_id=call_id, direction="inbound", caller_number=phone)


def _call(start: CallStart, lines: list[Optional[str]], clinic: Optional[FakeClinicAPI] = None):
    clinic = clinic or FakeClinicAPI()
    bot = create_orchestrator(clinic)
    actions = [bot.start_call(start)]
    for turn, line in enumerate(lines, start=1):
        caller = (
            CallerInput(turn=turn, text=None, silence_ms=2000)
            if line is SILENCE
            else CallerInput(turn=turn, text=line)
        )
        actions.append(bot.handle_turn(start.call_id, caller))
    return actions, clinic


def _searchable(text: str) -> str:
    return strip_diacritics(normalize_text(text))


def _assert_no_disclosure(actions: list[BotAction]) -> None:
    for action in actions:
        if action.state != "AWAITING_IDENTITY":
            break
        said = _searchable(action.utterance)
        leaked = [value for value in PROTECTED if _searchable(value) in said]
        assert not leaked, f"lộ {leaked} trước xác minh: {action.utterance!r}"


def _ended(action: BotAction, outcome: str, reason: Optional[str] = None) -> None:
    assert (action.state, action.ended, action.outcome) == ("ENDED", True, outcome)
    if reason:
        assert action.transfer_reason == reason or action.unreachable_reason == reason


# --- Lượt 0: không có hồ sơ để đối chiếu ---------------------------------------------------


@pytest.mark.parametrize("first_turn", ["Nguyễn Văn A", SILENCE, "tôi đau ngực quá"])
def test_unregistered_inbound_is_transferred_at_turn_one_without_asking_name(first_turn) -> None:
    actions, clinic = _call(_inbound("c_unreg", "0999999999"), [first_turn])
    opening, action = actions
    assert opening.utterance == t.GREETING_HANDOFF_INBOUND and "?" not in opening.utterance
    _ended(action, "TRANSFERRED", "PATIENT_NOT_FOUND")
    assert clinic.writes == [] and clinic.requests == []  # §2.1: không có lệnh ghi


def test_inbound_without_usable_phone_never_calls_mock() -> None:
    actions, clinic = _call(_inbound("c_nophone", None), ["Nguyễn Văn A"])
    _ended(actions[-1], "TRANSFERRED", "PATIENT_NOT_FOUND")
    assert clinic.patient_lookups == [] and clinic.writes == []


def test_inbound_lookup_failure_is_system_error_without_write() -> None:
    clinic = FakeClinicAPI()
    clinic.fail_next("find_patient_by_phone")
    actions, _ = _call(_inbound("c_in_down"), ["Nguyễn Văn A"], clinic)
    assert actions[0].utterance == t.GREETING_HANDOFF_INBOUND
    _ended(actions[-1], "TRANSFERRED", "SYSTEM_ERROR")
    assert clinic.writes == []


def test_outbound_unreadable_appointment_does_not_open_a_call() -> None:
    clinic = FakeClinicAPI()
    clinic.fail_next("get_appointment")
    bot = create_orchestrator(clinic)
    with pytest.raises(OutboundStartFailed):
        bot.start_call(_outbound("c_out_down"))
    assert bot.sessions.store.get_session("c_out_down") is None
    assert clinic.writes == []


def test_policy_lookup_table_matches_verifier() -> None:
    for status in LookupStatus:
        assert LOOKUP_TRANSFER_REASON.get(status.value) == PrepareResult(status).transfer_reason


# --- Hỏi mở, nhận phần còn thiếu --------------------------------------------------------------


def test_name_and_dob_in_one_answer_verifies_in_one_turn() -> None:
    actions, clinic = _call(
        _outbound("c_both"), ["Dạ, Nguyễn Văn A, sinh ngày 14 tháng 3 năm 1978"]
    )
    assert actions[-1].state == "AWAITING_INTENT" and "14 tháng 10" in actions[-1].utterance
    _assert_no_disclosure(actions)
    assert clinic.writes == []


def test_inbound_name_and_dob_in_one_answer() -> None:
    actions, clinic = _call(_inbound("c_in_both"), ["Nguyễn Văn A 14/03/1978"])
    assert actions[-1].state == "AWAITING_INTENT"
    assert actions[-1].utterance == t.ASK_INTENT_INBOUND
    assert clinic.writes == []


def test_dob_before_name_is_kept_and_only_name_is_asked() -> None:
    actions, _ = _call(_outbound("c_dob_first"), [DOB, NAME])
    assert actions[1].utterance == t.ASK_NAME_AFTER_DOB
    assert actions[2].state == "AWAITING_INTENT"
    _assert_no_disclosure(actions)


def test_wrong_identity_transfers_at_once_without_saying_which_field() -> None:
    actions, clinic = _call(_outbound("c_wrong"), ["Nguyễn Văn A, sinh ngày 15/03/1978"])
    _ended(actions[-1], "TRANSFERRED", "IDENTITY_FAILED")
    assert actions[-1].utterance == t.TRANSFER
    assert clinic.writes == [("apt_00417", "TRANSFERRED", {"transfer_reason": "IDENTITY_FAILED"})]


# --- Ngày sinh không hợp lệ -------------------------------------------------------------------


@pytest.mark.parametrize(
    "invalid",
    [
        "31/02/1978",  # ngày không tồn tại
        "14 tháng 3",  # thiếu năm
        "ngày 1 tháng 1 năm 20",  # năm 2 chữ số khớp cả 1920 và 2020
        "14 tháng 3 âm lịch năm 1978",
        "tôi 48 tuổi",
    ],
)
def test_invalid_dob_gets_its_own_reprompt(invalid: str) -> None:
    actions, clinic = _call(_outbound("c_invalid"), [NAME, invalid, DOB])
    assert actions[2].utterance == t.ASK_DOB_AGAIN
    assert actions[2].state == "AWAITING_IDENTITY"
    assert actions[3].state == "AWAITING_INTENT"  # hỏi lại một lần rồi xác minh được
    _assert_no_disclosure(actions)


def test_invalid_dob_twice_transfers_not_understood() -> None:
    actions, clinic = _call(_outbound("c_invalid2"), [NAME, "31/02/1978", "14 tháng 3"])
    _ended(actions[-1], "TRANSFERRED", "NOT_UNDERSTOOD")
    assert clinic.writes == [("apt_00417", "TRANSFERRED", {"transfer_reason": "NOT_UNDERSTOOD"})]


def test_inbound_invalid_dob_twice_transfers_without_write() -> None:
    actions, clinic = _call(_inbound("c_in_invalid2"), [NAME, "31/02/1978", "14 tháng 3"])
    _ended(actions[-1], "TRANSFERRED")
    assert clinic.writes == []


def test_name_with_invalid_dob_keeps_the_name_and_asks_the_dob_again() -> None:
    # Hai mệnh đề tách rõ: phần tên vẫn chắc chắn, chỉ ngày sinh là không dùng được.
    # Hỏi lại đúng phần thiếu, không bắt người gọi đọc lại cả hai.
    actions, _ = _call(_outbound("c_name_bad_dob"), ["Nguyễn Văn A, 31/02/1978", DOB])
    assert actions[1].utterance == t.ASK_DOB_AGAIN
    assert actions[2].state == "AWAITING_INTENT"


def test_out_of_scope_at_name_step_transfers_even_with_digits() -> None:
    actions, clinic = _call(_outbound("c_oos_digits"), ["bảo hiểm có chi trả 80% không"])
    _ended(actions[-1], "TRANSFERRED", "OUT_OF_SCOPE")
    assert clinic.writes == [("apt_00417", "TRANSFERRED", {"transfer_reason": "OUT_OF_SCOPE"})]


# --- Giới hạn hỏi lại: chỉ điền được trường còn thiếu mới tính là hiểu ---------------------------


def test_repeating_known_dob_does_not_reset_the_counter() -> None:
    actions, _ = _call(_outbound("c_loop"), [DOB, DOB, DOB])
    assert actions[1].state == actions[2].state == "AWAITING_IDENTITY"
    _ended(actions[3], "TRANSFERRED", "NOT_UNDERSTOOD")


def test_missing_name_twice_transfers_not_understood() -> None:
    actions, _ = _call(_outbound("c_noname"), ["tôi không rõ", "tôi cũng không biết"])
    assert actions[1].utterance == t.ASK_NAME_AGAIN
    _ended(actions[2], "TRANSFERRED", "NOT_UNDERSTOOD")


def test_a_greeting_between_failures_counts_as_absent_identity() -> None:
    actions, _ = _call(_outbound("c_noname_alo"), ["tôi không rõ", "alo"])
    _ended(actions[2], "TRANSFERRED", "NOT_UNDERSTOOD")


# --- "Alo" đáp câu chào mở đầu --------------------------------------------------------------------


@pytest.mark.parametrize("direction", ["outbound", "inbound"])
@pytest.mark.parametrize(
    "greeting",
    [
        "alo",
        "hello em",
        "hi em",
        "Hello, chị ạ!",
        "hú hú",
        "em ơi",
        "tôi nghe đây",
    ],
)
def test_greeting_after_opening_is_greeted_back_without_spending_the_retry(direction, greeting):
    # QC qc-id-05: "alo" khi vừa bắt máy chưa phải câu trả lời; lượt hỏi lại R-40 vẫn còn nguyên
    start = _outbound("c_alo") if direction == "outbound" else _inbound("c_alo")
    actions, clinic = _call(start, [greeting, "tôi không rõ", NAME, DOB])
    assert actions[1].utterance == t.greeting_back(direction)
    assert actions[2].utterance == t.ASK_NAME_AGAIN
    assert actions[3].utterance == t.ASK_DOB
    assert actions[4].state == "AWAITING_INTENT" and clinic.writes == []
    _assert_no_disclosure(actions)


def test_greeting_after_silence_reprompt_is_still_the_opening_greeting() -> None:
    actions, _ = _call(_outbound("c_silent_alo"), [SILENCE, "alo", "tôi không rõ", "tôi không rõ"])
    assert actions[2].utterance == t.GREETING_BACK_OUTBOUND
    assert actions[3].utterance == t.ASK_NAME_AGAIN
    _ended(actions[4], "TRANSFERRED", "NOT_UNDERSTOOD")


def test_greeting_after_another_identity_turn_spends_the_retry() -> None:
    # Chỉ lời chào trước mọi câu trả lời khác mới được chào lại; sau đó "alo" là ABSENT (stage1 R-40)
    actions, _ = _call(_outbound("c_late_alo"), ["tôi không rõ", "alo"])
    assert actions[1].utterance == t.ASK_NAME_AGAIN
    _ended(actions[2], "TRANSFERRED", "NOT_UNDERSTOOD")


# --- "Ai đấy?": câu hỏi phải trả lời, giới thiệu lại một lần mỗi cuộc gọi -------------------------


@pytest.mark.parametrize("direction", ["outbound", "inbound"])
@pytest.mark.parametrize("question", ["AI đấy?", "ai goi vay", "Alo, ai đấy?"])
def test_identity_question_reintroduces_without_spending_the_retry(direction, question) -> None:
    start = _outbound("c_who") if direction == "outbound" else _inbound("c_who")
    actions, clinic = _call(start, [question, NAME, DOB])
    assert actions[1].utterance == t.greeting_back(direction)
    assert actions[2].utterance == t.ASK_DOB
    assert actions[3].state == "AWAITING_INTENT" and clinic.writes == []
    _assert_no_disclosure(actions)


def test_identity_question_then_two_non_answers_transfers_on_the_third() -> None:
    # Bản QC qc-w6-03: "ai đấy?" được trả lời, câu không có tên tiếp theo mới dùng lượt hỏi lại
    actions, _ = _call(
        _outbound("c_who_then_vague"), ["Alo, ai đấy?", "À phòng khám à, ừ tôi đây", "ừ"]
    )
    assert actions[1].utterance == t.GREETING_BACK_OUTBOUND
    assert actions[2].utterance == t.ASK_NAME_AGAIN
    _ended(actions[3], "TRANSFERRED", "NOT_UNDERSTOOD")
    _assert_no_disclosure(actions)


def test_identity_question_then_name_completes_identity() -> None:
    actions, clinic = _call(
        _outbound("c_who_then_name"), ["Alo, ai đấy?", "À phòng khám à, ừ tôi đây", NAME, DOB]
    )
    assert actions[2].utterance == t.ASK_NAME_AGAIN
    assert actions[4].state == "AWAITING_INTENT" and clinic.writes == []


def test_repeated_greeting_exhausts_identity_retry() -> None:
    actions, _ = _call(_outbound("c_alo_twice"), ["alo", "alo", "alo"])
    assert actions[1].utterance == t.GREETING_BACK_OUTBOUND
    assert actions[2].utterance == t.ASK_NAME_AGAIN
    _ended(actions[3], "TRANSFERRED", "NOT_UNDERSTOOD")


@pytest.mark.parametrize("direction", ["outbound", "inbound"])
def test_absent_name_after_reprompt_transfers(direction) -> None:
    start = _outbound("c_who_again") if direction == "outbound" else _inbound("c_who_again")
    # "Ai đấy?" vẫn được trả lời sau lượt hỏi lại; câu không có tên kế tiếp thì chuyển máy
    actions, _ = _call(start, ["tôi không rõ", "Ai đấy?", "tôi không rõ"])
    assert actions[2].utterance == t.greeting_back(direction)
    _ended(actions[3], "TRANSFERRED", "NOT_UNDERSTOOD")
    _assert_no_disclosure(actions)


@pytest.mark.parametrize("direction", ["outbound", "inbound"])
def test_worst_case_identity_turns_before_transfer(direction) -> None:
    # Chào lại + hai câu hỏi được trả lời + một lượt hỏi lại: lượt không định danh thứ năm chuyển máy
    start = _outbound("c_worst") if direction == "outbound" else _inbound("c_worst")
    actions, _ = _call(start, ["alo", "Ai đấy?", "Ai đấy?", "tôi không rõ", "tôi không rõ"])
    assert [a.utterance for a in actions[1:4]] == [t.greeting_back(direction)] * 3
    assert actions[4].utterance == t.ASK_NAME_AGAIN
    _ended(actions[5], "TRANSFERRED", "NOT_UNDERSTOOD")
    _assert_no_disclosure(actions)


@pytest.mark.parametrize("direction", ["outbound", "inbound"])
def test_identity_question_at_dob_step_reasks_only_dob(direction) -> None:
    start = _outbound("c_who_dob") if direction == "outbound" else _inbound("c_who_dob")
    actions, clinic = _call(start, [NAME, "Ai gọi vậy?", DOB])
    assert actions[2].utterance == t.INTRODUCE_AGAIN_ASK_DOB
    assert actions[3].state == "AWAITING_INTENT" and clinic.writes == []
    _assert_no_disclosure(actions)


@pytest.mark.parametrize(
    "name",
    [
        "NGuyễn văn A nhé em",
        "nguyễn văn a nhé em",
        "Nguyễn Văn A nhé em, sinh ngày " + DOB,
        "Nguyễn Văn A ạ em",
        "Nguyễn Văn A cảm ơn em",
        "Họ tên của tôi là Nguyễn Văn A",
        "Tên đầy đủ của tôi trên giấy tờ là Nguyễn Văn A",
    ],
)
def test_name_with_polite_address_verifies_without_spurious_mismatch(name) -> None:
    lines = [name] if DOB in name else [name, DOB]
    actions, clinic = _call(_outbound("c_name_suffix"), lines)
    assert actions[-1].state == "AWAITING_INTENT" and clinic.writes == []
    _assert_no_disclosure(actions)


def test_greetings_after_the_opening_one_transfer_without_disclosure() -> None:
    actions, _ = _call(_outbound("c_hi_hi"), ["alo", "hi em", "alo"])
    assert actions[1].utterance == t.GREETING_BACK_OUTBOUND
    assert actions[2].utterance == t.ASK_NAME_AGAIN
    _ended(actions[3], "TRANSFERRED", "NOT_UNDERSTOOD")
    _assert_no_disclosure(actions)


def test_greetings_exhaust_one_identity_retry() -> None:
    actions, _ = _call(_outbound("c_alo_many"), ["alo"] * 3)
    assert not actions[2].ended
    _ended(actions[3], "TRANSFERRED", "NOT_UNDERSTOOD")


def test_repeated_identity_question_is_answered_twice_then_counts() -> None:
    actions, _ = _call(_outbound("c_who_many"), ["Ai đấy?"] * 4)
    assert actions[1].utterance == actions[2].utterance == t.GREETING_BACK_OUTBOUND
    assert actions[3].utterance == t.ASK_NAME_AGAIN
    _ended(actions[4], "TRANSFERRED", "NOT_UNDERSTOOD")


def test_identity_question_free_pass_is_per_call_not_per_field() -> None:
    actions, _ = _call(
        _outbound("c_who_both"),
        ["Ai đấy?", "Ai đấy?", NAME, "Ai gọi vậy?", "tôi không rõ"],
    )
    assert actions[1].utterance == actions[2].utterance == t.GREETING_BACK_OUTBOUND
    assert actions[4].utterance == t.ASK_DOB_AGAIN
    _ended(actions[5], "TRANSFERRED", "NOT_UNDERSTOOD")


def test_a_greeting_while_asking_dob_uses_the_single_retry() -> None:
    actions, _ = _call(_outbound("c_alo_dob"), [NAME, "alo", "tôi không rõ"])
    assert actions[2].utterance == t.ASK_DOB_AGAIN
    _ended(actions[3], "TRANSFERRED", "NOT_UNDERSTOOD")


@pytest.mark.parametrize("greeting", ["hú hú", "hú hú em ơi", "ừ tôi nghe"])
def test_contact_signal_during_dob_does_not_restart_identity(greeting) -> None:
    actions, clinic = _call(_outbound("c_contact_dob"), [NAME, greeting, DOB])
    assert actions[2].utterance == t.ASK_DOB_AGAIN
    assert actions[3].state == "AWAITING_INTENT" and clinic.writes == []


def test_english_greeting_after_reprompt_transfers_without_guessing() -> None:
    actions, _ = _call(_outbound("c_hello_again"), ["hello em", "hi em", "hello"])
    assert actions[1].utterance == t.GREETING_BACK_OUTBOUND
    assert actions[2].utterance == t.ASK_NAME_AGAIN
    _ended(actions[3], "TRANSFERRED", "NOT_UNDERSTOOD")


# --- Xin nhắc lại ---------------------------------------------------------------------------------


def test_repeat_request_rereads_question_without_counting() -> None:
    actions, _ = _call(_outbound("c_repeat"), [NAME, "gì cơ", "nói lại giúp tôi", DOB])
    assert actions[2].utterance == actions[3].utterance == t.ASK_DOB
    assert actions[4].state == "AWAITING_INTENT"


def test_repeat_request_between_failures_keeps_the_count() -> None:
    actions, _ = _call(_outbound("c_repeat_fail"), [NAME, "ờ để xem", "gì cơ", "ờ để xem"])
    assert actions[3].utterance == t.ASK_DOB_AGAIN  # đọc lại đúng câu đang chờ
    _ended(actions[4], "TRANSFERRED", "NOT_UNDERSTOOD")


# --- Im lặng: bộ đếm riêng ------------------------------------------------------------------------


def test_outbound_silence_during_identity_ends_unreachable() -> None:
    actions, clinic = _call(_outbound("c_silent"), [NAME, SILENCE, SILENCE, SILENCE])
    _ended(actions[-1], "UNREACHABLE", "SILENCE")
    assert clinic.writes == [("apt_00417", "UNREACHABLE", {"unreachable_reason": "SILENCE"})]


def test_inbound_silence_during_identity_transfers_without_write() -> None:
    actions, clinic = _call(_inbound("c_in_silent"), [SILENCE, SILENCE, SILENCE])
    _ended(actions[-1], "TRANSFERRED", "NOT_UNDERSTOOD")
    assert clinic.writes == []


def test_silence_between_failures_neither_resets_nor_counts() -> None:
    actions, _ = _call(_outbound("c_silent_fail"), [NAME, "ờ để xem", SILENCE, "ờ để xem"])
    assert actions[3].utterance.startswith(t.SILENCE)
    _ended(actions[4], "TRANSFERRED", "NOT_UNDERSTOOD")


@pytest.mark.parametrize("start", [_outbound, _inbound])
def test_hold_two_silences_and_return_resume_identity(start) -> None:
    actions, clinic = _call(
        start("c_hold_return"), ["chờ chút nhé", SILENCE, SILENCE, "rồi, tôi đây", NAME, DOB]
    )
    assert actions[1].utterance == t.HOLD
    assert actions[2].utterance == actions[3].utterance == f"{t.SILENCE} {actions[0].utterance}"
    assert actions[4].utterance == actions[0].utterance
    assert all(not action.ended for action in actions)
    assert actions[5].utterance == t.ASK_DOB
    assert actions[6].state == "AWAITING_INTENT"
    assert clinic.writes == []


def test_hold_and_return_do_not_count_as_failed_understanding() -> None:
    actions, _ = _call(
        _outbound("c_hold_after_failure"),
        ["ờ để xem", "chờ chút nhé", SILENCE, SILENCE, "rồi, tôi đây", NAME, DOB],
    )
    assert actions[5].state == "AWAITING_IDENTITY"
    assert actions[6].utterance == t.ASK_DOB
    assert actions[7].state == "AWAITING_INTENT"


# --- Không nhớ / không muốn cung cấp (§1.1.1) ---------------------------------------------------


def test_cannot_provide_twice_is_identity_failed() -> None:
    actions, clinic = _call(
        _outbound("c_declined"), [NAME, "tôi không nhớ ngày sinh", "không nhớ thật mà"]
    )
    assert actions[2].utterance == t.ASK_DOB_AGAIN
    _ended(actions[3], "TRANSFERRED", "NOT_UNDERSTOOD")
    assert clinic.writes == [("apt_00417", "TRANSFERRED", {"transfer_reason": "NOT_UNDERSTOOD"})]


def test_outbound_refuses_name_twice_and_transfers_immediately() -> None:
    actions, clinic = _call(
        _outbound("c_declined_name"), ["tôi không khai tên đâu", "tôi không nói tên"]
    )
    assert actions[1].utterance == t.ASK_NAME_AGAIN
    _ended(actions[2], "TRANSFERRED", "NOT_UNDERSTOOD")
    assert clinic.writes == [("apt_00417", "TRANSFERRED", {"transfer_reason": "NOT_UNDERSTOOD"})]


def test_cannot_provide_once_then_answering_verifies() -> None:
    actions, _ = _call(_outbound("c_declined_once"), [NAME, "tôi quên mất rồi", DOB])
    assert actions[-1].state == "AWAITING_INTENT"


def test_inbound_cannot_provide_twice_transfers_without_write() -> None:
    actions, clinic = _call(_inbound("c_in_declined"), ["tôi không muốn nói", "không muốn nói"])
    assert actions[1].utterance == t.ASK_NAME_AGAIN
    _ended(actions[2], "TRANSFERRED")
    assert clinic.writes == []


# --- Nói nhu cầu trước khi xác minh (Hình 0, kịch bản Book) ---------------------------------------


def test_request_before_identity_asks_to_verify_first() -> None:
    actions, clinic = _call(_inbound("c_book_first"), ["Alô, tôi muốn đặt lịch khám ạ.", NAME, DOB])
    assert actions[1].utterance == t.ASK_NAME_FOR_REQUEST
    assert actions[3].state == "AWAITING_INTENT"
    _assert_no_disclosure(actions)
    # Nhu cầu nói trước xác minh không được dùng: chưa đọc slot nào
    assert clinic.writes == [] and all(call.operation != "get_slots" for call in clinic.calls)


def test_request_before_identity_repeated_exhausts_one_retry() -> None:
    actions, _ = _call(_outbound("c_cancel_first"), ["tôi muốn hủy lịch"] * 2)
    assert actions[1].utterance == t.ASK_NAME_FOR_REQUEST
    _ended(actions[2], "TRANSFERRED", "NOT_UNDERSTOOD")
    _assert_no_disclosure(actions)


# --- HTTP ------------------------------------------------------------------------------------------


def test_name_and_dob_in_one_turn_over_http(client) -> None:
    start = {
        "call_id": "c_http_both",
        "direction": "outbound",
        "appointment_id": "apt_00417",
        "caller_number": None,
        "locale": "vi-VN",
        "mode": "text",
        "max_turns": 20,
    }
    assert client.post("/v1/calls", json=start).status_code == 200
    body = client.post(
        "/v1/calls/c_http_both/turn",
        json={"turn": 1, "audio_url": None, "text": "Nguyễn Văn A, 14/03/1978", "silence_ms": 0},
    ).json()
    assert body["state"] == "AWAITING_INTENT" and body["ended"] is False


# --- QC qc-stt-05 / qc-w6-01: tên không dấu, người gọi nói tiếng Anh ------------------------------


@pytest.mark.parametrize(
    "lines",
    [
        ["Alo", "nguyen van a", DOB],
        ["Hello?", "Nguyen Van A", "March 14, 1978"],
        ["Hello?", "My name is Nguyen Van A, born on March 14th 1978"],
        ["I'm Nguyen Van A", "1978-03-14"],
        ["NGUYEN VAN A, 14/3/1978"],
    ],
)
def test_unaccented_or_english_identity_verifies(lines) -> None:
    actions, clinic = _call(_outbound("c_unaccented"), lines)
    assert actions[-1].state == "AWAITING_INTENT" and clinic.writes == []
    _assert_no_disclosure(actions)


@pytest.mark.parametrize(
    "lines",
    [
        ["nguyen van a", "14/03/1979"],  # ngày sinh vẫn so tuyệt đối
        ["Tran Van B"],
        ["Nguyễn Van A"],  # có dấu một phần: luật chặt
    ],
)
def test_unaccented_name_still_needs_the_exact_dob(lines) -> None:
    actions, clinic = _call(_outbound("c_unaccented_fail"), lines)
    _ended(actions[-1], "TRANSFERRED", "IDENTITY_FAILED")
    assert [w for w in clinic.writes if w[1] != "TRANSFERRED"] == []
    _assert_no_disclosure(actions)
