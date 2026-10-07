"""Lý do "đã khám chỗ khác rồi" là yêu cầu hủy — QC qc-cn-03-went-elsewhere.

Chỉ ở câu đọc lịch / "đổi hay hủy" outbound, chỉ khi luật không ra nhãn nào, và bằng luật (không tốn
request model). Mọi ca âm tính đi đường cũ.
"""

from datetime import datetime
from typing import Optional

import pytest

from callbot.engine.extraction import InformationExtractor, Intent, Provenance, QuestionId
from callbot.engine.extraction.cancel_reason import extract_cancel_reason
from callbot.engine.extraction.implied_cancel import implied_cancel
from callbot.engine.extraction.schema import VN_TZ, TurnContext
from callbot.engine.extraction.text import normalize

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=VN_TZ)
QUESTIONS = (QuestionId.CONFIRM_READBACK, QuestionId.ASK_INTENT)

IMPLIED = [
    ("Tôi khám ở bệnh viện khác rồi em ạ", "WENT_ELSEWHERE"),
    ("dạ tôi khám ở chỗ khác rồi", "WENT_ELSEWHERE"),
    ("tôi đã khám ở nơi khác", "WENT_ELSEWHERE"),
    ("tôi đi viện khác rồi", "WENT_ELSEWHERE"),
    ("Không, tôi khám chỗ khác rồi", "WENT_ELSEWHERE"),
    ("con tôi khám ở bệnh viện khác rồi", "WENT_ELSEWHERE"),
    ("toi kham cho khac roi", "WENT_ELSEWHERE"),
    ("Tôi khỏi rồi em", "NO_LONGER_NEEDED"),
]
NOT_IMPLIED = [
    # phủ định trong cùng mệnh đề
    "Tôi không khám ở bệnh viện khác đâu",
    "không tôi khám chỗ khác rồi",
    "tôi chưa khám chỗ khác",
    # chưa xảy ra: định / sẽ / trùng giờ thì có thể muốn dời
    "tôi định khám chỗ khác",
    "tôi sẽ đi khám chỗ khác",
    "giờ đó tôi có lịch khám ở bệnh viện khác",
    "da toi kham cho khac",
    # "rồi" ở đây là "sau đó", hoặc dự định đi kèm "rồi"
    "tôi sẽ khám ở bệnh viện khác rồi báo lại",
    "tôi định khám chỗ khác rồi",
    "giờ đó tôi có lịch khám ở bệnh viện khác rồi",
    # không chắc đã đi hay chưa
    "đã khám chỗ khác hay chưa thì tôi không nhớ",
    # đặt lịch ở nơi khác là lịch tương lai, dù có "đã"
    "Tôi đã đặt hẹn ở bệnh viện khác",
    "tôi đặt lịch ở bệnh viện khác rồi",
    # chữ khác nằm giữa hai cụm lý do
    "Tôi khỏi rồi nhưng không chắc là khỏe rồi",
    # câu hỏi, "nhưng", ngập ngừng
    "khám chỗ khác có được không em",
    "bệnh viện khác có rẻ hơn không",
    "tôi khám chỗ khác rồi à?",
    "tôi khám chỗ khác rồi nhưng mà vẫn muốn khám bên mình",
    "chắc là tôi khám chỗ khác rồi",
    # NO_LONGER_NEEDED chưa dứt khoát
    "tôi đỡ rồi",
    # nhiều lý do: không chọn hộ
    "Tôi khỏi rồi mà cũng khám chỗ khác rồi",
    # lý do khác vẫn có thể muốn đổi lịch
    "hôm đó tôi bận rồi",
]


class _NoModel:
    """Tầng ngữ nghĩa giả: ghi lại mọi lần bị gọi."""

    def __init__(self) -> None:
        self.calls = 0

    def analyze(self, context):
        self.calls += 1
        return None


def _extract(text: str, question: QuestionId, direction: str = "outbound", semantic=None):
    turn = TurnContext(turn=4, question_id=question, direction=direction, now=NOW, question_turn=3)
    return InformationExtractor(semantic=semantic).extract(turn, text)


@pytest.mark.parametrize("text, reason", [*IMPLIED, ("tôi hết đau rồi", "NO_LONGER_NEEDED")])
def test_definite_reason_is_a_cancel_request(text: str, reason: str) -> None:
    found = extract_cancel_reason(text)
    assert found.value == reason
    assert implied_cancel(text, found) == found.span


@pytest.mark.parametrize("text", NOT_IMPLIED)
def test_negated_planned_asked_or_mixed_reason_is_not_a_request(text: str) -> None:
    assert implied_cancel(text, extract_cancel_reason(text)) is None


@pytest.mark.parametrize("question", QUESTIONS)
@pytest.mark.parametrize("text, reason", IMPLIED)
def test_outbound_reading_steps_turn_the_reason_into_cancel_without_the_model(
    question: QuestionId, text: str, reason: str
) -> None:
    semantic = _NoModel()
    result = _extract(text, question, semantic=semantic)
    assert result.intent.value is Intent.CANCEL
    assert result.intent.span == result.cancel_reason.span
    assert result.cancel_reason.value == reason
    expected = Provenance.NORMALIZED if text == "toi kham cho khac roi" else Provenance.EXACT
    assert result.intent.provenance is expected
    assert semantic.calls == 0


@pytest.mark.parametrize("question", QUESTIONS)
@pytest.mark.parametrize("text", NOT_IMPLIED)
def test_other_reason_wording_keeps_the_old_path(question: QuestionId, text: str) -> None:
    assert _extract(text, question).intent.value is not Intent.CANCEL


@pytest.mark.parametrize(
    "text, intent",
    [
        ("tôi khám chỗ khác rồi, đổi sang tuần sau nhé", Intent.RESCHEDULE),
        ("tôi khám chỗ khác rồi, giữ lịch giúp tôi", Intent.CONFIRM),
        ("tôi khám chỗ khác rồi, cho tôi gặp nhân viên", Intent.REQUEST_HUMAN),
    ],
)
def test_a_rule_intent_wins_over_the_reason(text: str, intent: Intent) -> None:
    assert _extract(text, QuestionId.CONFIRM_READBACK).intent.value is intent


@pytest.mark.parametrize(
    "question, direction",
    [
        (QuestionId.ASK_INTENT, "inbound"),  # inbound hủy là ngoài kịch bản, không tự tạo
        (QuestionId.CANCEL_RECONFIRM, "outbound"),  # câu xác nhận hủy có luồng lý do riêng
        (QuestionId.SLOT_READBACK, "outbound"),
    ],
)
def test_only_outbound_reading_steps_promote(question: QuestionId, direction: str) -> None:
    result = _extract("tôi khám chỗ khác rồi", question, direction)
    assert result.intent.value in (Intent.NONE, None)


@pytest.mark.parametrize(
    "text",
    [
        "tôi hết đau rồi",  # "đau" là MENTION: để tuyến lâm sàng xét
        "tôi khám ở bệnh viện khác rồi, họ bảo tôi đau ngực",
    ],
)
def test_clinical_content_is_not_promoted(text: str) -> None:
    assert _extract(text, QuestionId.CONFIRM_READBACK).intent.value is not Intent.CANCEL


# --- Yêu cầu hủy nói gộp ở lượt danh tính (QC qc-cn-08): `deferred_intent` -----------------------


def _identity_turn(text: str, question=QuestionId.ASK_NAME, direction: str = "outbound"):
    turn = TurnContext(turn=1, question_id=question, direction=direction, now=NOW)
    return InformationExtractor().extract(turn, text)


@pytest.mark.parametrize(
    "text, question, reason",
    [
        (
            "Alo, tôi là Nguyễn Văn A, sinh 14/3/1978, gọi để hủy lịch khám vì tuần đó tôi đi công tác",
            QuestionId.ASK_NAME,
            "PATIENT_UNAVAILABLE",
        ),
        ("tôi muốn hủy lịch", QuestionId.ASK_NAME, "UNSPECIFIED"),
        ("14/3/1978, tôi gọi để hủy lịch", QuestionId.ASK_DOB, "UNSPECIFIED"),
        # đoạn trước ngày sinh là yêu cầu, không phải tên
        ("Tôi muốn hủy lịch vì bận, sinh 14/3/1978", QuestionId.ASK_DOB, "PATIENT_UNAVAILABLE"),
    ],
)
def test_cancel_said_with_identity_is_kept_aside(text, question, reason) -> None:
    result = _identity_turn(text, question)
    assert result.deferred_intent.value is Intent.CANCEL
    assert result.deferred_cancel_reason.value == reason


@pytest.mark.parametrize(
    "text, question, direction",
    [
        ("Tôi là Trần Văn Hủy, sinh 14/3/1978", QuestionId.ASK_NAME, "outbound"),  # tên đã trích
        # "Hủy" là tên dù không trích được tên (ASK_DOB không trích tên, hoặc trích thất bại)
        ("Trần Thị Hủy, sinh 14/3/1978", QuestionId.ASK_DOB, "outbound"),
        ("14/3/1978, Trần Văn Hủy đây", QuestionId.ASK_DOB, "outbound"),
        ("tôi là Hủy, sinh 14/3/1978", QuestionId.ASK_DOB, "outbound"),
        ("tôi tên Hủy", QuestionId.ASK_NAME, "outbound"),
        # "hủy" ngoài cụm yêu cầu rõ ràng không phải yêu cầu hủy
        ("14/3/1978, tôi là Hủy cho em hỏi chút", QuestionId.ASK_DOB, "outbound"),
        ("14/3/1978 nhé, Hủy luôn đây", QuestionId.ASK_DOB, "outbound"),
        # Hỏi về việc hủy, chưa phải yêu cầu
        ("sinh 14/3/1978, nhưng tôi muốn hủy lịch có được không", QuestionId.ASK_DOB, "outbound"),
        ("Nguyễn Văn A, sinh 14/3/1978, tôi muốn hủy lịch", QuestionId.ASK_NAME, "inbound"),
    ],
)
def test_identity_turn_without_an_outbound_cancel_request(text, question, direction) -> None:
    assert _identity_turn(text, question, direction).deferred_intent.value is not Intent.CANCEL


def test_name_huy_does_not_hide_a_cancel_request_in_the_same_turn() -> None:
    assert _identity_turn("tôi là Hủy, muốn hủy lịch").deferred_intent.value is Intent.CANCEL


@pytest.mark.parametrize(
    "text",
    [
        "Nguyễn Văn A, tôi không muốn hủy đâu",
        "14/03/1978, không hủy nữa nhé",
        "14/03/1978, thôi tôi vẫn đi khám, không hủy nữa",
        "14/03/1978, tôi đổi ý rồi",
        "14/03/1978, để tôi nghĩ lại đã",
        # đoạn đứng trước ngày sinh không phải tên thì không bị bỏ
        "Tôi đổi ý rồi, sinh 14/3/1978",
    ],
)
def test_identity_turn_with_other_content_drops_the_kept_cancel(text: str) -> None:
    """Không liệt kê cách đổi ý: còn nội dung ngoài tên / ngày sinh mà không phải yêu cầu hủy rõ
    ràng là NONE có span, Dialogue bỏ yêu cầu hủy đã giữ."""
    result = _identity_turn(text)
    assert result.deferred_intent.found and result.deferred_intent.value is Intent.NONE
    assert result.deferred_cancel_reason.found is False


@pytest.mark.parametrize(
    "text, question, said",
    [
        # đổi lịch thắng hủy; lời yêu cầu không còn tên
        (
            "Nguyễn Văn A, không đi được, đổi sang chiều nhé",
            QuestionId.ASK_NAME,
            "không đi được, đổi sang chiều nhé",
        ),
        # ngày sinh không thành tiêu chí; "15:30" giữ nguyên dấu
        (
            "14/03/1978, tôi muốn đổi sang 15:30 chiều ngày 20",
            QuestionId.ASK_DOB,
            "tôi muốn đổi sang 15:30 chiều ngày 20",
        ),
        ("đổi lịch sang chiều ngày 14 được không em", QuestionId.ASK_DOB, None),
    ],
)
def test_reschedule_said_with_identity_is_kept_aside(
    text: str, question: QuestionId, said: Optional[str]
) -> None:
    """PRD R-43: yêu cầu đổi lịch nói ở bước danh tính được giữ như yêu cầu hủy (thay yêu cầu hủy đã
    giữ); câu hỏi lịch sự "… được không" vẫn là yêu cầu."""
    result = _identity_turn(text, question)
    assert result.deferred_intent.value is Intent.RESCHEDULE
    assert result.deferred_request == (said or normalize(text))


@pytest.mark.parametrize(
    "text", ["14/03/1978, chắc là đổi lịch", "14/03/1978, vợ tôi bảo đổi lịch"]
)
def test_undecided_reschedule_at_the_identity_step_is_not_kept(text: str) -> None:
    result = _identity_turn(text, QuestionId.ASK_DOB)
    assert result.deferred_intent.found and result.deferred_intent.value is Intent.NONE


@pytest.mark.parametrize(
    "text, question",
    [
        ("Nguyễn Văn A", QuestionId.ASK_NAME),
        ("dạ tôi là Nguyễn Văn A ạ", QuestionId.ASK_NAME),
        ("14/03/1978 nhé em", QuestionId.ASK_DOB),
        ("Trần Thị Hủy, sinh 14/3/1978", QuestionId.ASK_DOB),
        ("tôi là Hủy, sinh 14/3/1978", QuestionId.ASK_DOB),
        # nhắc lại tên sau ngày sinh chỉ là bổ sung danh tính
        ("14/3/1978, tôi là Nguyễn Văn A", QuestionId.ASK_DOB),
        ("14/3/1978, Trần Văn Hủy đây", QuestionId.ASK_DOB),
    ],
)
def test_identity_only_turn_keeps_what_was_kept(text: str, question: QuestionId) -> None:
    assert _identity_turn(text, question).deferred_intent.found is False


@pytest.mark.parametrize(
    "text, intent",
    [
        ("Tôi muốn đổi lịch, à thôi hủy đi", Intent.CANCEL),
        ("hủy lịch, à nhầm, đổi lịch", Intent.RESCHEDULE),
        ("Hủy đi, à không, giữ lịch giúp tôi", Intent.CONFIRM),
        ("đổi lịch, à thôi", Intent.NONE),  # rút lại mà chưa nói nhu cầu mới: để tuyến sau đọc
    ],
)
def test_the_need_after_a_self_correction_wins(text: str, intent: Intent) -> None:
    assert (_extract(text, QuestionId.CONFIRM_READBACK).intent.value or Intent.NONE) is intent
