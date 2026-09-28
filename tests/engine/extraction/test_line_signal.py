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
        # T-08: lời chào hộp thư cá nhân, không có "để lại lời nhắn"
        ("Xin chào, bạn đã gọi đến số của Lan. Hiện không thể nghe máy", LineSignal.VOICEMAIL),
        ("Cảm ơn bạn đã gọi, tôi hiện không thể trả lời cuộc gọi", LineSignal.VOICEMAIL),
        ("xin chao, ban da goi den so cua Lan", LineSignal.VOICEMAIL),
        ("Hi, you've reached Lan, I can't take your call right now", LineSignal.VOICEMAIL),
        ("You have reached the voicemail box of 0912345600", LineSignal.VOICEMAIL),
        ("Sorry I can't come to the phone, please leave your name", LineSignal.VOICEMAIL),
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
        # T-08: người thật đang bận nói với bot — không phải hộp thư
        "giờ tôi không nghe máy được lâu, em nói nhanh nhé",
        "tôi đang lái xe không nghe máy được, lát gọi lại sau giúp tôi",
        "tôi sẽ gọi lại cho bạn sau",
        "bạn gọi đến có việc gì thế",
        "bạn gọi nhầm số rồi",
        "hiện tại tôi không nghe rõ",
        "cảm ơn em",
        "I can't talk right now, call me later",
        "yes, you reached the right person",
        "Tôi đang bận, em để lại tin nhắn giúp tôi",
        "Tôi hiện không thể nghe máy, gọi lại sau nhé",
        "Đây không phải hộp thư thoại, tôi đang nghe đây",
        "toi dang ban em de lai tin nhan giup toi",
        "day khong phai hop thu thoai toi dang nghe day",
        "This is not a voicemail, I am listening",
        "I can't take your call right now, call me later",
        # Không có bằng chứng bản ghi; câu này thuộc REVIEW trong corpus.
        "Xin chào, tôi là Lan, hiện không nghe máy được",
        "Chị để lại lời nhắn cho chồng tôi được không",
        "Anh để lại tin nhắn cho vợ tôi giúp nhé",
        "chi de lai loi nhan cho chong toi duoc khong",
        "Vâng, cảm ơn bạn đã gọi, có việc gì không ạ",
        "Cảm ơn bạn đã gọi, gọi có chuyện gì vậy",
        "Số thuê bao này là của mẹ tôi, mẹ tôi đang bận",
        "Thuê bao này là của bố tôi, ông đang bận",
    ],
)
def test_human_speech_is_not_a_line_signal(text: str) -> None:
    assert extract_line_signal(text).value is LineSignal.NONE


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Hộp thư của quý khách đã đầy, không thể nhận thêm tin nhắn", LineSignal.VOICEMAIL),
        ("Xin chào, đây là hộp thư của Minh", LineSignal.VOICEMAIL),
        ("Bạn đã gọi tới số của Tuấn, hiện Tuấn không bắt máy được", LineSignal.VOICEMAIL),
        (
            "Your call has been forwarded to an automated voice messaging system",
            LineSignal.VOICEMAIL,
        ),
        ("The mailbox is full and cannot accept any messages", LineSignal.VOICEMAIL),
        ("hợp thư thoại của thuê bao", LineSignal.VOICEMAIL),
        ("Thuê bao quý khách vừa gọi hiện đang có cuộc gọi khác", LineSignal.LINE_BUSY),
        (
            "Cảm ơn bạn đã gọi cho cửa hàng Hoa Mai, hiện chúng tôi không thể trả lời",
            LineSignal.VOICEMAIL,
        ),
        ("Thuê bao đang bận, xin để lại lời nhắn sau tiếng bíp", LineSignal.VOICEMAIL),
    ],
)
def test_automated_announcements_remain_recognized(text, expected):
    assert extract_line_signal(text).value is expected
