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
        ("Đổi cho tôi sang 5 giờ chiều ngày 14", Intent.RESCHEDULE),
        ("chuyển giúp chị qua tuần sau", Intent.RESCHEDULE),
        ("dời lịch hộ em sang chiều", Intent.RESCHEDULE),
        ("chuyen giup toi sang thu sau", Intent.RESCHEDULE),
        ("đừng đổi cho tôi sang", Intent.NONE),
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


@pytest.mark.parametrize(
    "text", ["giữ nguyên", "không đổi không hủy gì cả", "không đổi cũng không hủy", "không đổi gì"]
)
def test_keeping_the_appointment_is_confirm_outbound_only(text: str) -> None:
    """T-04 §8: trả lời "đổi hay hủy" bằng cách giữ lịch; inbound không có lịch để giữ."""
    assert extract_intent(text, "outbound").value is Intent.CONFIRM
    assert extract_intent(text, "inbound").value is not Intent.CONFIRM


# --- Ngoài phạm vi: câu hỏi / yêu cầu bot hiểu được nhưng không có luồng xử lý (§1.1.5) -------


@pytest.mark.parametrize(
    "text",
    [
        # người khác đi khám thay
        "vợ tôi sẽ đến thay",
        "để con tôi đi khám thay",
        "chồng tôi đi thay được không",
        "cho con tôi khám hộ được không",
        # địa chỉ / đường đi / gửi xe
        "địa chỉ ở đâu em nhỉ",
        "cho tôi xin địa chỉ phòng khám",
        "phòng khám ở đâu em",
        "gửi xe ở đâu em",
        "em chỉ đường giúp tôi",
        # đến muộn
        "tôi đến trễ không sao chứ",
        "tôi đến muộn 15 phút có được không",
        "tôi đi trễ một chút được không em",
        # xin gọi lại
        "dạ, tôi đang bận, gọi lại sau",
        "em gọi lại cho tôi lúc khác nhé",
        "lát nữa gọi lại giúp tôi",
        # không dấu
        "dia chi o dau em",
        "toi den muon duoc khong",
        "goi lai sau nhe",
    ],
)
def test_out_of_scope_requests(text: str) -> None:
    assert extract_intent(text, "outbound").value is Intent.OUT_OF_SCOPE
    assert extract_intent(text, "inbound").value is Intent.OUT_OF_SCOPE


@pytest.mark.parametrize(
    "text",
    [
        "tôi biết địa chỉ rồi, tôi sẽ đến",
        "tôi sẽ đến đúng giờ, không trễ đâu",
        "tôi sẽ đến, không đến trễ đâu",
        "vợ tôi sẽ đưa tôi đi",
        "Thay vì hủy thì cho tôi dời sang thứ sáu",
        "Để tôi hỏi vợ đã rồi gọi lại",
        "không cần gọi lại đâu",
        "vâng, tôi đang lái xe",
        "vâng, tôi đang ở ngoài đường",
        # bản không dấu trùng nghĩa khác: đến thấy, khám thấy, đi mượn, tôi trẻ, chị Dương
        "toi den thay dong qua",
        "kham thay binh thuong",
        "di kham thay binh thuong",
        "den kham thay dong qua",
        "toi di muon xe",
        "toi tre lam",
        "da chi duong day",
        # "thay" trong từ ghép khác, và phủ định có "ai" chen giữa
        "tôi phải đi thay băng",
        "không có ai đi thay đâu, tôi tự đến",
        "chẳng ai đến thay đâu",
    ],
)
def test_near_out_of_scope_wording_is_not_out_of_scope(text: str) -> None:
    assert extract_intent(text, "outbound").value is not Intent.OUT_OF_SCOPE


def test_someone_else_attending_beats_the_attendance_keyword() -> None:
    """ "sẽ đến" là từ khóa CONFIRM, nhưng người khác đến thay thì ngoài phạm vi (PRIORITY)."""
    result = extract_intent("vợ tôi sẽ đến thay", "outbound")
    assert (result.value, result.span) == (Intent.OUT_OF_SCOPE, "đến thay")


def test_explicit_callback_request_also_counts_before_identity() -> None:
    """Yêu cầu gọi lại tường minh nằm ngoài kịch bản ở cả bước danh tính (§1.1.5)."""
    busy = "tôi đang lái xe không nghe máy được, lát gọi lại sau giúp tôi"
    assert extract_intent(busy, "outbound").value is Intent.OUT_OF_SCOPE
    assert extract_intent(busy, "outbound", business_step=False).value is Intent.OUT_OF_SCOPE
    address = extract_intent("địa chỉ phòng khám ở đâu", "outbound", business_step=False)
    assert address.value is Intent.OUT_OF_SCOPE


@pytest.mark.parametrize(
    "text, expected",
    [
        # "toi muon" không dấu là "tôi muốn", không phải "tới muộn"
        ("toi muon doi lich", Intent.RESCHEDULE),
        ("toi muon huy lich", Intent.CANCEL),
        ("da toi muon doi sang chieu", Intent.RESCHEDULE),
        # nhu cầu trong phạm vi thắng yêu cầu ngoài kịch bản đi kèm
        ("hôm đó tôi đến muộn mất, đổi sang chiều được không", Intent.RESCHEDULE),
        ("tôi sợ đến trễ, cho tôi dời sang 10 giờ", Intent.RESCHEDULE),
        ("tôi muốn đến thay đổi giờ khám", Intent.RESCHEDULE),
        ("hủy đi rồi gọi lại cho tôi sau", Intent.CANCEL),
        ("tôi không đến được, vợ tôi đi thay", Intent.CANCEL),
    ],
)
def test_in_scope_request_wins_over_out_of_scope_request(text: str, expected: Intent) -> None:
    assert extract_intent(text, "outbound").value is expected


def test_booking_with_a_late_arrival_question_stays_a_booking() -> None:
    text = "tôi muốn đặt lịch, mà tôi đến muộn chút được không"
    assert extract_intent(text, "inbound").value is Intent.BOOK
    assert extract_intent("toi muon dat lich kham", "inbound").value is Intent.BOOK


# --- Từ khóa trong câu kể không đủ để quyết cả câu -----------------------------------------------


@pytest.mark.parametrize(
    "text, intent",
    [
        # Chính người bệnh nói mình vắng: không phải người khác nghe máy
        ("Tôi đi vắng nên muốn đổi lịch", Intent.RESCHEDULE),
        # "nhân viên" trong câu kể / phủ định không phải xin gặp người
        ("Nhân viên đã hẹn tôi đến hôm đó", Intent.CONFIRM),
        ("Tôi không muốn gặp bất kỳ nhân viên nào", Intent.NONE),
        # Biết địa chỉ không phải hỏi địa chỉ
        ("Tôi biết địa chỉ bệnh viện rồi, tôi sẽ đến", Intent.CONFIRM),
    ],
)
def test_keyword_inside_a_statement_does_not_decide_the_turn(text: str, intent: Intent) -> None:
    assert extract_intent(text, "outbound").value is intent


@pytest.mark.parametrize(
    "text, intent",
    [
        ("anh ấy đi vắng rồi", Intent.NOT_PATIENT),
        ("đi vắng rồi", Intent.NOT_PATIENT),
        ("nhân viên", Intent.REQUEST_HUMAN),
        ("cho tôi nhân viên đi", Intent.REQUEST_HUMAN),
        ("chuyển tôi sang nhân viên nhé", Intent.REQUEST_HUMAN),
        ("nếu hết giờ thì chuyển nhân viên", Intent.REQUEST_HUMAN),
        ("cho tôi xin địa chỉ phòng khám", Intent.OUT_OF_SCOPE),
        ("địa chỉ phòng khám ở đâu vậy em", Intent.OUT_OF_SCOPE),
    ],
)
def test_explicit_requests_are_still_recognised(text: str, intent: Intent) -> None:
    assert extract_intent(text, "outbound").value is intent
