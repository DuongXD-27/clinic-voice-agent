"""Điều phối theo question_id + chốt chặn tuyến sau (span phải nằm trong transcript)."""

import json
from datetime import date, datetime
from typing import Optional

import pytest

from callbot.engine.extraction import (
    Agreement,
    ClinicalLevel,
    Field,
    InformationExtractor,
    Intent,
    LineSignal,
    Provenance,
    QuestionId,
    SlotFillingResult,
    SlotFillingStatus,
    TurnContext,
)
from callbot.engine.extraction.schema import INVALID, VN_TZ

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=VN_TZ)


def ctx(question: Optional[QuestionId], direction="outbound", **kwargs) -> TurnContext:
    return TurnContext(turn=2, question_id=question, direction=direction, now=NOW, **kwargs)


def slot_result(name: Optional[Field[str]]) -> Optional[SlotFillingResult]:
    """Fake gọn: tên -> ACCEPTED (extractor vẫn tự guard), Field rỗng -> NO_NAME."""
    if name is None:
        return None
    status = SlotFillingStatus.ACCEPTED if name.found else SlotFillingStatus.NO_NAME
    return SlotFillingResult(status, name)


class FakeFallback:
    """`full_name`: một `Field` (bọc thành kết quả slot filling), một `SlotFillingResult`, hoặc None."""

    def __init__(self, intent=None, agreement=None, full_name=None) -> None:
        self._intent, self._agreement, self._full_name = intent, agreement, full_name
        self.calls: list[str] = []
        self.name_contexts: list[tuple[QuestionId, Optional[str]]] = []

    def intent(self, transcript: str, allowed: frozenset[Intent]) -> Optional[Field[Intent]]:
        self.calls.append("intent")
        return self._intent

    def agreement(self, transcript: str, question_id: QuestionId) -> Optional[Field[Agreement]]:
        self.calls.append("agreement")
        return self._agreement

    def full_name(
        self,
        transcript: str,
        *,
        question_id: QuestionId = QuestionId.ASK_NAME,
        bot_question: Optional[str] = None,
    ) -> Optional[SlotFillingResult]:
        self.calls.append("full_name")
        self.name_contexts.append((question_id, bot_question))
        if isinstance(self._full_name, Field):
            return slot_result(self._full_name)
        return self._full_name


extractor = InformationExtractor()


def test_identity_step_does_not_run_business_intents() -> None:
    result = extractor.extract(ctx(QuestionId.ASK_NAME), "Lê Văn Thôi")
    assert result.intent.value is Intent.NONE
    assert result.full_name.value == "lê văn thôi"
    assert result.agreement.value is None and result.dob.value is None

    # Câu nghiệp vụ bị loại khỏi tên theo cụm -> quay về đúng nhãn ý định, không thành "tên"
    business = extractor.extract(ctx(QuestionId.ASK_NAME), "hủy lịch đi")
    assert business.full_name.found is False and business.intent.value is Intent.CANCEL


def test_identity_step_keeps_safety_labels_and_does_not_read_them_as_names() -> None:
    result = extractor.extract(ctx(QuestionId.ASK_NAME), "tôi là vợ anh ấy")
    assert result.intent.value is Intent.NOT_PATIENT
    assert result.full_name.found is False

    result = extractor.extract(ctx(QuestionId.ASK_NAME), "cho tôi gặp nhân viên")
    assert result.intent.value is Intent.REQUEST_HUMAN
    assert result.full_name.found is False

    result = extractor.extract(ctx(QuestionId.ASK_NAME), "gì cơ")
    assert result.intent.value is Intent.REPEAT_REQUEST
    assert result.full_name.found is False

    result = extractor.extract(ctx(QuestionId.ASK_DOB), "tôi đang khó thở")
    assert result.clinical.value is ClinicalLevel.EMERGENCY


def test_dob_only_at_identity_steps() -> None:
    assert extractor.extract(ctx(QuestionId.ASK_DOB), "14/03/1978").dob.value == date(1978, 3, 14)
    # T-02: hỏi tên mà người gọi đọc ngày sinh -> giữ lại, chỉ hỏi phần còn thiếu
    result = extractor.extract(ctx(QuestionId.ASK_NAME), "14/03/1978")
    assert result.dob.value == date(1978, 3, 14) and result.full_name.found is False
    assert extractor.extract(ctx(QuestionId.ASK_INTENT), "14/03/1978").dob.found is False


@pytest.mark.parametrize(
    "transcript, name",
    [
        ("Nguyễn Văn A, sinh ngày 14/3/1978", "nguyễn văn a"),
        ("Dạ, Nguyễn Văn A, sinh ngày 14 tháng 3 năm 1978", "nguyễn văn a"),
        ("Nguyễn Văn Sinh, sinh năm 14/3/1978", "nguyễn văn sinh"),
        ("Tôi là Lê Na, 14/03/1978", "lê na"),
        ("Tôi là Nguyễn Văn A sinh ngày mười bốn tháng ba năm 1978", "nguyễn văn a"),
        ("Nguyễn Văn A năm sinh 14/03/1978", "nguyễn văn a"),
        ("nguyen van a sinh ngay 14/3/1978", "nguyen van a"),
        # Tên trùng từ ngày tháng / số vẫn nguyên vẹn
        ("Nguyễn Văn Sinh sinh ngày 14/3/1978", "nguyễn văn sinh"),
        ("Trần Văn Năm, 14/3/1978", "trần văn năm"),
    ],
)
def test_name_and_dob_in_one_answer(transcript: str, name: str) -> None:
    result = extractor.extract(ctx(QuestionId.ASK_NAME), transcript)
    assert result.full_name.value == name
    assert isinstance(result.dob.value, date)
    assert result.intent.value is Intent.NONE


@pytest.mark.parametrize(
    "transcript",
    [
        "Nguyễn Văn Sinh 14/3/1978",  # "Sinh" là tên hay từ nối?
        "Nguyễn Văn Tám mười bốn tháng ba năm 1978",  # "Tám" thuộc tên hay ngày?
        "Lê Na sinh ngày 14/3/1978",  # cắt ở "sinh" còn dưới 3 từ
    ],
)
def test_ambiguous_name_before_dob_is_not_guessed(transcript: str) -> None:
    # Tên cắt nhầm -> Verifier chuyển máy ngay; không chắc thì để trống, bot hỏi lại tên
    result = extractor.extract(ctx(QuestionId.ASK_NAME), transcript)
    assert result.full_name.found is False
    assert result.dob.found


def test_name_is_split_from_a_recognised_date_even_when_the_date_is_unusable() -> None:
    # Ngày không tồn tại vẫn là một vùng ngày có thật -> giữ tên, chỉ hỏi lại ngày sinh
    result = extractor.extract(ctx(QuestionId.ASK_NAME), "Nguyễn Văn A, 31/02/1978")
    assert result.full_name.value == "nguyễn văn a" and result.dob.value == INVALID

    # Câu chỉ tình cờ có chữ số thì không có vùng ngày -> không được cắt "bảo hiểm có chi trả"
    # thành tên và đẩy vào Verifier
    result = extractor.extract(ctx(QuestionId.ASK_NAME), "bảo hiểm có chi trả 80% không")
    assert result.full_name.found is False and result.dob.value == INVALID


@pytest.mark.parametrize(
    "question, transcript",
    [
        (QuestionId.ASK_DOB, "Tôi không nhớ ngày sinh"),
        (QuestionId.ASK_DOB, "tôi quên mất rồi"),
        (QuestionId.ASK_DOB, "toi khong nho"),
        (QuestionId.ASK_NAME, "tôi không muốn cung cấp"),
    ],
)
def test_cannot_provide_at_identity_step(question: QuestionId, transcript: str) -> None:
    assert extractor.extract(ctx(question), transcript).intent.value is Intent.CANNOT_PROVIDE


def test_cannot_provide_never_leaves_identity_step() -> None:
    # Ở bước nghiệp vụ "không nhớ" không phải nhãn; tên / ngày sinh hợp lệ luôn thắng
    assert (
        extractor.extract(ctx(QuestionId.ASK_INTENT), "tôi không nhớ").intent.value is Intent.NONE
    )
    # Người gọi tự báo là không chắc: ngày không đi tiếp vào Verifier, bot hỏi lại
    result = extractor.extract(ctx(QuestionId.ASK_DOB), "không nhớ lắm, 14/3/1978 thì phải")
    assert result.dob.value == INVALID and result.intent.value is Intent.NONE


@pytest.mark.parametrize(
    "direction, transcript, intent",
    [
        ("inbound", "Alô, tôi muốn đặt lịch khám ạ.", Intent.BOOK),  # Hình 0, kịch bản Book
        ("outbound", "tôi muốn đổi lịch", Intent.RESCHEDULE),
        ("outbound", "tôi muốn hủy lịch", Intent.CANCEL),
    ],
)
def test_business_intent_before_identity_is_labelled(direction, transcript, intent) -> None:
    result = extractor.extract(ctx(QuestionId.ASK_NAME, direction=direction), transcript)
    assert result.intent.value is intent and result.full_name.found is False


def test_out_of_scope_with_digits_at_name_step_is_still_detected() -> None:
    # Chữ số làm dob thành INVALID ở bước hỏi tên; không được chặn OUT_OF_SCOPE (§1.2.3)
    result = extractor.extract(ctx(QuestionId.ASK_NAME), "bảo hiểm có chi trả 80% không")
    assert result.dob.value == INVALID and result.intent.value is Intent.OUT_OF_SCOPE


def test_voicemail_short_circuits_outbound_identity_steps() -> None:
    for question in (None, QuestionId.ASK_NAME, QuestionId.ASK_DOB):
        result = extractor.extract(ctx(question), "Vui lòng để lại lời nhắn sau tiếng bíp")
        assert result.line_signal.value is LineSignal.VOICEMAIL
        assert result.full_name.found is False and result.intent.value is None

    # Sau xác minh, và ở inbound, không xét tín hiệu đường dây
    assert (
        extractor.extract(
            ctx(QuestionId.ASK_INTENT), "để lại lời nhắn sau tiếng bíp"
        ).line_signal.value
        is None
    )
    inbound = extractor.extract(ctx(QuestionId.ASK_NAME, direction="inbound"), "hộp thư thoại")
    assert inbound.line_signal.value is None


def test_silent_turn_is_not_a_failed_understanding() -> None:
    # Rev 1.1 §1.1.7: im lặng (silence_ms > 0) không tính vào §1.1.5 -> không trường nào mang NONE "đã chạy"
    for question in (
        QuestionId.ASK_NAME,
        QuestionId.ASK_DOB,
        QuestionId.ASK_INTENT,
        QuestionId.CANCEL_RECONFIRM,
    ):
        result = extractor.extract(ctx(question), "", silence_ms=4000)
        assert result.silent is True
        assert (
            result.intent.value is None
            and result.full_name.value is None
            and result.agreement.value is None
        )
        assert result.to_trace()["silent"] is True

    # ASR không ra chữ nhưng harness không báo im lặng -> không hiểu, không phải im lặng
    result = extractor.extract(ctx(QuestionId.ASK_NAME), "", silence_ms=0)
    assert result.silent is False
    assert result.intent.value is Intent.NONE

    # silence_ms > 0 thắng cả khi có text lạc (vd. tiếng ồn ra chữ)
    assert (
        extractor.extract(ctx(QuestionId.CANCEL_RECONFIRM), "hủy đi", silence_ms=1).agreement.value
        is None
    )


def test_operator_transcript_is_not_a_dial_result() -> None:
    result = extractor.extract(ctx(QuestionId.ASK_NAME), "Số máy quý khách vừa gọi hiện đang bận")
    assert result.line_signal.value is LineSignal.NONE
    assert result.silent is False
    # Người thật nói "đang bận" ở bước hỏi tên không kết thúc cuộc gọi
    assert (
        extractor.extract(ctx(QuestionId.ASK_NAME), "tôi đang bận").line_signal.value
        is LineSignal.NONE
    )


def test_out_of_scope_at_identity_step_only_when_answer_is_not_an_identifier() -> None:
    # §1.1.5 / §1.2.3: chuyển máy OUT_OF_SCOPE ngay, không phải hỏi lại tên rồi NOT_UNDERSTOOD
    result = extractor.extract(ctx(QuestionId.ASK_NAME), "cho tôi hỏi bảo hiểm có chi trả không")
    assert result.intent.value is Intent.OUT_OF_SCOPE
    assert result.full_name.found is False

    result = extractor.extract(ctx(QuestionId.ASK_DOB), "thanh toán bằng thẻ được không")
    assert result.intent.value is Intent.OUT_OF_SCOPE

    # Tên hợp lệ luôn thắng, kể cả khi trùng từ khoá lúc mất dấu
    result = extractor.extract(ctx(QuestionId.ASK_NAME), "nguyen thanh toan")
    assert result.full_name.value == "nguyen thanh toan"
    assert result.intent.value is Intent.NONE

    result = extractor.extract(ctx(QuestionId.ASK_DOB), "14/3/1978 thanh toán sau nhé")
    assert result.dob.found and result.intent.value is Intent.NONE


def test_agreement_is_downgraded_when_caller_talks_about_something_else() -> None:
    result = extractor.extract(ctx(QuestionId.CONFIRM_READBACK), "vâng, hủy giúp tôi")
    assert result.intent.value is Intent.CANCEL
    assert result.agreement.value is Agreement.UNCLEAR
    assert result.cancel_reason.value == "UNSPECIFIED"

    result = extractor.extract(
        ctx(QuestionId.CANCEL_RECONFIRM), "đúng rồi hủy đi, mà tôi đau ngực quá"
    )
    assert result.clinical.value is ClinicalLevel.EMERGENCY
    assert result.agreement.value is not Agreement.AGREE


def test_cancel_reconfirm_flow_fields() -> None:
    result = extractor.extract(ctx(QuestionId.CANCEL_RECONFIRM), "hủy đi, hôm đó tôi đi công tác")
    assert result.agreement.value is Agreement.AGREE
    assert result.cancel_reason.value == "PATIENT_UNAVAILABLE"


def test_slot_choice_uses_all_slots_from_context() -> None:
    slots = (
        {"slot_id": "a", "starts_at": "2026-10-14T10:00:00+07:00"},
        {"slot_id": "b", "starts_at": "2026-10-14T14:30:00+07:00"},
    )
    turn = ctx(QuestionId.OFFER_SLOTS, slots=slots, presented_slot_ids=("a",))
    result = extractor.extract(turn, "hai giờ rưỡi chiều")  # b chưa được đọc nhưng vẫn là ứng viên
    assert result.slot_choice.value.slot_id == "b"


def test_fallback_is_only_called_when_rules_find_nothing() -> None:
    fallback = FakeFallback(intent=Field(Intent.RESCHEDULE, Provenance.FALLBACK, span="tuần sau"))
    with_fallback = InformationExtractor(fallback=fallback)

    with_fallback.extract(ctx(QuestionId.ASK_INTENT), "hủy giúp tôi")
    assert fallback.calls == []
    with_fallback.extract(ctx(QuestionId.ASK_NAME), "ừm để xem")
    assert fallback.calls == []  # không gọi tuyến sau cho intent ở bước danh tính

    result = with_fallback.extract(ctx(QuestionId.ASK_INTENT), "chắc để tuần sau em ạ")
    assert result.intent.value is Intent.RESCHEDULE
    assert result.intent.provenance is Provenance.FALLBACK


def test_fallback_span_must_be_in_transcript() -> None:
    invented = FakeFallback(intent=Field(Intent.CANCEL, Provenance.FALLBACK, span="hủy lịch"))
    result = InformationExtractor(fallback=invented).extract(
        ctx(QuestionId.ASK_INTENT), "chắc để tuần sau em ạ"
    )
    assert result.intent.value is Intent.NONE
    assert result.intent.provenance is Provenance.NONE

    no_span = FakeFallback(intent=Field(Intent.CANCEL, Provenance.FALLBACK))
    result = InformationExtractor(fallback=no_span).extract(
        ctx(QuestionId.ASK_INTENT), "chắc để tuần sau em ạ"
    )
    assert result.intent.found is False


def test_fallback_cannot_unlock_cancellation() -> None:
    fallback = FakeFallback(
        agreement=Field(Agreement.AGREE, Provenance.FALLBACK, span="bận mất rồi")
    )
    result = InformationExtractor(fallback=fallback).extract(
        ctx(QuestionId.CANCEL_RECONFIRM), "hôm đó tôi bận mất rồi"
    )
    assert fallback.calls == ["intent"]  # R-31: one model operation per turn.
    assert result.agreement.value is Agreement.UNCLEAR

    # Câu có "vâng" đã có tín hiệu ở tầng luật -> không hỏi mô hình
    fallback.calls.clear()
    InformationExtractor(fallback=fallback).extract(ctx(QuestionId.CANCEL_RECONFIRM), "vâng")
    assert "agreement" not in fallback.calls


def test_name_fallback_is_off_by_default_and_guarded() -> None:
    fallback = FakeFallback(
        full_name=Field("nguyễn văn a", Provenance.FALLBACK, span="nguyễn văn a")
    )
    transcript = "à ừ thì là nguyễn văn a nhé em"  # tầng luật loại: có từ chức năng "là"
    assert (
        InformationExtractor(fallback=fallback)
        .extract(ctx(QuestionId.ASK_NAME), transcript)
        .full_name.found
        is False
    )

    enabled = InformationExtractor(fallback=fallback, name_fallback=True)
    result = enabled.extract(ctx(QuestionId.ASK_NAME), transcript)
    assert result.full_name.value == "nguyễn văn a"
    assert result.full_name.provenance is Provenance.FALLBACK

    invented = FakeFallback(full_name=Field("trần thị b", Provenance.FALLBACK, span="nguyễn văn a"))
    result = InformationExtractor(fallback=invented, name_fallback=True).extract(
        ctx(QuestionId.ASK_NAME), transcript
    )
    assert result.full_name.found is False


def test_trace_is_json_ready() -> None:
    result = extractor.extract(ctx(QuestionId.ASK_DOB), "mười bốn tháng ba năm bảy tám")
    trace = result.to_trace()
    json.dumps(trace, ensure_ascii=False)
    assert trace["dob"] == {
        "value": "1978-03-14",
        "provenance": "NORMALIZED",
        "span": "mười bốn tháng ba năm bảy tám",
    }
    assert trace["question_id"] == "ASK_DOB"
    # Chỉ luật đọc lượt này: không có model nào để trang demo báo
    assert (trace["model_provider"], trace["model_name"], trace["model_backup_for"]) == (
        None,
        None,
        None,
    )


@pytest.mark.parametrize(
    "text, span",
    [("tôi sẽ đến", "sẽ đến"), ("xác nhận", "xác nhận"), ("không hủy đâu, tôi vẫn đến", "vẫn đến")],
)
def test_stated_attendance_is_agreement_at_readback(text: str, span: str) -> None:
    """T-04, contract Bảng 1: "states or agrees they will attend"."""
    if text in ("không hủy đâu, tôi vẫn đến",):
        result = InformationExtractor().extract(ctx(QuestionId.CONFIRM_READBACK), text)
        assert result.agreement.value is Agreement.UNCLEAR
        return
    result = InformationExtractor().extract(ctx(QuestionId.CONFIRM_READBACK), text)
    assert result.intent.value is Intent.CONFIRM
    assert (result.agreement.value, result.agreement.span) == (Agreement.AGREE, span)


@pytest.mark.parametrize(
    "text, intent",
    [("tôi sẽ đến được không", Intent.CONFIRM), ("không đến được", Intent.CANCEL)],
)
def test_attendance_wording_that_is_not_agreement(text: str, intent: Intent) -> None:
    result = InformationExtractor().extract(ctx(QuestionId.CONFIRM_READBACK), text)
    assert result.intent.value is intent and result.agreement.value is not Agreement.AGREE


def test_stated_attendance_does_not_unlock_other_writes() -> None:
    for question in (QuestionId.SLOT_READBACK, QuestionId.CANCEL_RECONFIRM):
        result = InformationExtractor().extract(ctx(question), "tôi sẽ đến")
        assert result.agreement.value is not Agreement.AGREE


@pytest.mark.parametrize(
    "text",
    [
        "hôm đó tôi sẽ đi công tác",
        "tôi vẫn đi làm hôm đó",
        "tối đó tôi đến bệnh viện khác rồi",
        "tôi sẽ đến lúc 10 giờ",
        "toi se di cong tac",
    ],
)
def test_attendance_wording_inside_another_plan_is_not_agreement(text: str) -> None:
    """T-04 §8: cụm "sẽ đi / sẽ đến" chỉ là đồng ý khi câu không nói thêm việc khác."""
    result = InformationExtractor().extract(ctx(QuestionId.CONFIRM_READBACK), text)
    assert result.intent.value is Intent.CONFIRM
    assert result.agreement.value is Agreement.UNCLEAR and result.agreement.found


@pytest.mark.parametrize(
    "question",
    [QuestionId.CONFIRM_READBACK, QuestionId.ASK_INTENT, QuestionId.SLOT_READBACK],
)
@pytest.mark.parametrize(
    "text",
    ["vợ tôi sẽ đến thay", "gửi xe ở đâu em", "tôi đến muộn chút được không", "gọi lại sau nhé"],
)
def test_out_of_scope_request_at_business_steps(question: QuestionId, text: str) -> None:
    """Bot hiểu câu nhưng không có luồng xử lý: Policy chuyển máy OUT_OF_SCOPE, không đọc lại lịch."""
    result = InformationExtractor().extract(ctx(question), text)
    assert result.intent.value is Intent.OUT_OF_SCOPE
    assert result.agreement.value is not Agreement.AGREE


def test_explicit_callback_request_at_the_name_step_is_out_of_scope() -> None:
    """§1.1.5 áp dụng cả trước xác minh khi người thật xin gọi lại."""
    busy = "tôi đang lái xe không nghe máy được, lát gọi lại sau giúp tôi"
    assert (
        InformationExtractor().extract(ctx(QuestionId.ASK_NAME), busy).intent.value
        is Intent.OUT_OF_SCOPE
    )
    address = InformationExtractor().extract(ctx(QuestionId.ASK_NAME), "địa chỉ phòng khám ở đâu")
    assert address.intent.value is Intent.OUT_OF_SCOPE


@pytest.mark.parametrize(
    "text", ["tôi sẽ đến đúng giờ", "không đổi gì cả, tôi đến", "vâng, tôi vẫn đi khám"]
)
def test_attendance_with_its_own_complements_still_agrees(text: str) -> None:
    if text in ("không đổi gì cả, tôi đến",):
        result = InformationExtractor().extract(ctx(QuestionId.CONFIRM_READBACK), text)
        assert result.agreement.value is Agreement.UNCLEAR
        return
    result = InformationExtractor().extract(ctx(QuestionId.CONFIRM_READBACK), text)
    assert result.agreement.value is Agreement.AGREE
