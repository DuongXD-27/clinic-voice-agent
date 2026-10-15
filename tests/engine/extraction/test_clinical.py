"""Bộ bẫy §9: EMERGENCY / ADVICE_REQUEST đo recall; MENTION đo tỉ lệ bị chuyển máy nhầm."""

import pytest

from callbot.engine.extraction.clinical import extract_clinical
from callbot.engine.extraction.schema import ClinicalLevel


@pytest.mark.parametrize(
    "text",
    [
        "Tôi bị đau ngực",
        "bố tôi đang khó thở",
        "con tôi vừa co giật",
        "mẹ tôi bị ngất",
        "chảy máu nhiều quá",
        "Tôi bị đau ngực có sao không?",
        "đau ngực nhưng muốn đặt lịch khám",  # recall: vẫn EMERGENCY dù có ngữ cảnh đặt lịch
        "không khó thở lắm",  # recall: không xét phủ định
    ],
)
def test_emergency(text: str) -> None:
    assert extract_clinical(text).value is ClinicalLevel.EMERGENCY


@pytest.mark.parametrize(
    "text",
    [
        "đau bụng thế này có sao không",
        "tôi nên uống thuốc gì",
        "uống thuốc gì cho đỡ ho",
        "bị ho thì nên khám khoa nào",
        "có cần đi khám gấp không",
        "tôi bị sốt ba ngày rồi thì sao",
        "đau đầu hoài là bị bệnh gì vậy em",
        "huyết áp 150 có nguy hiểm không",
        "thuốc huyết áp có phải ngưng trước khi khám không",
        "tôi đang uống thuốc huyết áp, có cần ngừng trước khi khám không",
        "thuoc huyet ap co phai ngung truoc khi kham khong",
    ],
)
def test_advice_request_needs_asking(text: str) -> None:
    assert extract_clinical(text).value is ClinicalLevel.ADVICE_REQUEST


@pytest.mark.parametrize(
    "text",
    [
        "hay đau bụng nên muốn đặt lịch",
        "tái khám dạ dày",
        "tôi bị đau lưng, muốn đặt lịch khám được không",  # câu hỏi đuôi về lịch, không phải về triệu chứng
        "đổi lịch tái khám huyết áp sang chiều được không",
        "tôi đang bị sốt nên không đi được",
        "tôi muốn đặt lịch khám bệnh",
        "bệnh viện ở đâu vậy",
        "tôi uống thuốc huyết áp và muốn đổi lịch khám",
        "tôi đang uống thuốc huyết áp, mai đi khám",
    ],
)
def test_mention_is_not_transferred(text: str) -> None:
    assert extract_clinical(text).value not in (
        ClinicalLevel.EMERGENCY,
        ClinicalLevel.ADVICE_REQUEST,
    )


def test_mention_and_none() -> None:
    assert extract_clinical("hay đau bụng nên muốn đặt lịch").value is ClinicalLevel.MENTION
    assert extract_clinical("tôi muốn hủy lịch").value is ClinicalLevel.NONE
    assert extract_clinical("tôi muốn đặt lịch khám bệnh").value is ClinicalLevel.NONE


@pytest.mark.parametrize("text", ["Hủy lịch có sao không em", "đổi giờ có ảnh hưởng gì không"])
def test_assessment_question_about_the_booking_is_only_a_mention(text: str) -> None:
    """Không chuyển máy chỉ vì "có sao không": tầng ngữ nghĩa đọc lại câu (CLINICAL_UNRESOLVED)."""
    assert extract_clinical(text).value is ClinicalLevel.MENTION


@pytest.mark.parametrize(
    "text, level",
    [
        ("hủy lịch thì bệnh của tôi có sao không", ClinicalLevel.ADVICE_REQUEST),
        ("uống thuốc rồi hủy lịch có sao không", ClinicalLevel.ADVICE_REQUEST),
        ("tôi bị đau ngực, hủy lịch có sao không", ClinicalLevel.EMERGENCY),
    ],
)
def test_assessment_question_with_health_content_stays_clinical(text, level) -> None:
    assert extract_clinical(text).value is level
