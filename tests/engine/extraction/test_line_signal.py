"""Tín hiệu đường dây — tên giá trị trùng `unreachable_reason` ở Phụ lục A (hợp đồng rev 1.1)."""

import pytest

from callbot.engine.extraction.line_signal import extract_line_signal
from callbot.engine.extraction.schema import LineSignal


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Xin vui lòng để lại lời nhắn sau tiếng bíp", LineSignal.VOICEMAIL),
        ("Bạn đã được chuyển tới hộp thư thoại", LineSignal.VOICEMAIL),
        (
            "Thuê bao quý khách vừa gọi tạm thời không liên lạc được, vui lòng để lại lời nhắn",
            LineSignal.VOICEMAIL,
        ),
        (
            "The person you are calling is not available, please leave a message after the tone",
            LineSignal.VOICEMAIL,
        ),
        ("Số máy quý khách vừa gọi hiện đang bận, xin vui lòng gọi lại sau", LineSignal.LINE_BUSY),
        ("Thuê bao đang bận", LineSignal.LINE_BUSY),
        ("The number you are calling is busy", LineSignal.LINE_BUSY),
        ("Thuê bao quý khách vừa gọi tạm thời không liên lạc được", LineSignal.NO_ANSWER),
        ("Số máy quý khách vừa gọi hiện đang ngoài vùng phủ sóng", LineSignal.NO_ANSWER),
        ("Số máy quý khách vừa gọi không có thực", LineSignal.NO_ANSWER),
        ("The number you have dialed cannot be reached", LineSignal.NO_ANSWER),
    ],
)
def test_line_signal(text: str, expected: LineSignal) -> None:
    assert extract_line_signal(text).value is expected


@pytest.mark.parametrize(
    "text",
    [
        "Alo ai đấy",
        "Nguyễn Văn A",
        "tôi đang bận, lát gọi lại nhé",  # người thật nói bận -> không phải LINE_BUSY
        "tôi không liên lạc được với anh ấy",  # người thật -> không phải NO_ANSWER
        "anh ấy không trả lời điện thoại",
        "Hello, who is this?",
    ],
)
def test_human_speech_is_not_a_line_signal(text: str) -> None:
    assert extract_line_signal(text).value is LineSignal.NONE
