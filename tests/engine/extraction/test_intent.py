import pytest

from callbot.engine.extraction.intent import extract_intent
from callbot.engine.extraction.schema import Intent, Provenance


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Tôi sẽ đến", Intent.CONFIRM),
        ("đến được em ạ", Intent.CONFIRM),
        ("Hủy giúp tôi", Intent.CANCEL),
        ("huỷ lịch đi", Intent.CANCEL),  # kiểu bỏ dấu mới
        ("tôi không đi được nữa", Intent.CANCEL),
        ("Tôi đổi sang buổi chiều được không?", Intent.RESCHEDULE),
        ("dời lịch sang tuần sau", Intent.RESCHEDULE),
        ("cho tôi gặp nhân viên", Intent.REQUEST_HUMAN),
        ("bảo hiểm có chi trả không", Intent.OUT_OF_SCOPE),
        ("tôi muốn xin lại đơn thuốc", Intent.OUT_OF_SCOPE),
        ("gì cơ?", Intent.REPEAT_REQUEST),
        ("em nói lại giúp chị", Intent.REPEAT_REQUEST),
        ("hả?", Intent.REPEAT_REQUEST),
        ("tôi là vợ anh ấy", Intent.NOT_PATIENT),
        ("anh ấy đi vắng rồi", Intent.NOT_PATIENT),
        ("chị gọi nhầm số rồi", Intent.NOT_PATIENT),
        ("alo", Intent.NONE),
        ("ừm để tôi xem", Intent.NONE),
    ],
)
def test_outbound_labels(text: str, expected: Intent) -> None:
    assert extract_intent(text, "outbound").value is expected


@pytest.mark.parametrize(
    "text, expected",
    [
        # Nhiều nhãn: có phương án thay thế -> RESCHEDULE
        ("Không đến được, đổi sang chiều được không", Intent.RESCHEDULE),
        ("hủy lịch này rồi đặt lại lịch khác cho tôi", Intent.RESCHEDULE),
        ("hủy lịch đi, cho tôi gặp nhân viên", Intent.REQUEST_HUMAN),
        ("tôi là chồng chị ấy, muốn hủy lịch", Intent.NOT_PATIENT),
        ("đổi lịch được không, mà bảo hiểm có trả không", Intent.OUT_OF_SCOPE),
    ],
)
def test_priority(text: str, expected: Intent) -> None:
    assert extract_intent(text, "outbound").value is expected


@pytest.mark.parametrize(
    "text, not_expected",
    [
        ("không hủy", Intent.CANCEL),
        ("đừng hủy nhé", Intent.CANCEL),
        ("tôi không muốn hủy", Intent.CANCEL),
        ("không đổi", Intent.RESCHEDULE),
        ("chưa cần đổi lịch đâu", Intent.RESCHEDULE),
        ("giữ nguyên lịch", Intent.CANCEL),
        ("giữ nguyên lịch", Intent.RESCHEDULE),
        ("không cần gặp nhân viên", Intent.REQUEST_HUMAN),
    ],
)
def test_negation_blocks_action_labels(text: str, not_expected: Intent) -> None:
    assert extract_intent(text, "outbound").value is not not_expected


def test_direction_only_labels() -> None:
    assert extract_intent("tôi muốn đặt lịch khám", "inbound").value is Intent.BOOK
    assert extract_intent("tôi muốn đặt lịch khám", "outbound").value is Intent.NONE
    assert extract_intent("tôi sẽ đến", "inbound").value is Intent.NONE


@pytest.mark.parametrize(
    "text, expected",
    [
        ("tôi muốn xác nhận lịch khám", Intent.CONFIRM),
        ("xac nhan lich hen", Intent.CONFIRM),
        ("tôi không xác nhận lịch", Intent.NONE),
        ("sáng mai tôi đến được không", Intent.NONE),  # nhu cầu đặt lịch, không phải lịch có sẵn
        ("tôi muốn đặt lịch, xác nhận lịch giúp", Intent.BOOK),
    ],
)
def test_inbound_confirm_only_on_existing_appointment_wording(text: str, expected: Intent) -> None:
    """T-04: inbound "xác nhận lịch" là việc ngoài kịch bản -> Dialogue chuyển máy (§1.1.5)."""
    assert extract_intent(text, "inbound").value is expected


def test_allowed_restricts_labels() -> None:
    allowed = {Intent.REQUEST_HUMAN, Intent.NOT_PATIENT, Intent.REPEAT_REQUEST}
    assert extract_intent("tôi muốn hủy", "outbound", allowed).value is Intent.NONE
    assert extract_intent("cho gặp nhân viên", "outbound", allowed).value is Intent.REQUEST_HUMAN


def test_span_and_provenance() -> None:
    result = extract_intent("Dạ, hủy giúp tôi", "outbound")
    assert result.provenance is Provenance.EXACT
    assert result.span == "hủy"
    assert extract_intent("alo", "outbound").provenance is Provenance.NONE
