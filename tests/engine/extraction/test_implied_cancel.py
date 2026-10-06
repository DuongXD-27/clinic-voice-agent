"""Lý do "đã khám chỗ khác rồi" là yêu cầu hủy — QC qc-cn-03-went-elsewhere.

Chỉ ở câu đọc lịch / "đổi hay hủy" outbound, chỉ khi luật không ra nhãn nào, và bằng luật (không tốn
request model). Mọi ca âm tính đi đường cũ.
"""

from datetime import datetime

import pytest

from callbot.engine.extraction import InformationExtractor, Intent, Provenance, QuestionId
from callbot.engine.extraction.cancel_reason import extract_cancel_reason
from callbot.engine.extraction.implied_cancel import implied_cancel
from callbot.engine.extraction.schema import VN_TZ, TurnContext

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
