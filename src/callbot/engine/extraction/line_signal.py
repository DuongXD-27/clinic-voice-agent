"""Tín hiệu đường dây — thiết kế v1.1 §5.9, hợp đồng rev 1.1 §1.1.7, §4.2.5.

Chạy trước mọi bộ khác trên cuộc gọi outbound cho tới khi xác minh xong danh tính — hợp đồng nói
harness gửi VOICEMAIL bằng một clip lời chào hộp thư, nhưng không nói clip đến ở lượt nào.
Kết quả khác NONE -> Policy kết thúc `UNREACHABLE` với `unreachable_reason` cùng tên;
Dialogue KHÔNG để lại chi tiết lịch hẹn trên hộp thư thoại.

- VOICEMAIL xét trước: "thuê bao không liên lạc được, vui lòng để lại lời nhắn" là đã vào hộp thư.
- LINE_BUSY / NO_ANSWER chỉ nhận khi có dấu hiệu TỔNG ĐÀI ("thuê bao", "số máy quý khách", "ngoài vùng
  phủ sóng"...). Người nghe máy nói "tôi đang bận" hay "không liên lạc được với anh ấy" là người thật —
  kết thúc UNREACHABLE với họ là case fail.
"""

from callbot.engine.extraction.schema import Field, LineSignal, Provenance
from callbot.engine.extraction.text import clean, compile_phrases, find_phrase, is_unaccented

_VOICEMAIL = compile_phrases(
    [
        "để lại lời nhắn",
        "sau tiếng bíp",
        "sau tiếng tít",
        "hộp thư thoại",
        "lời nhắn thoại",
        "để lại tin nhắn",
        # clip lời chào có thể là tiếng Anh
        "leave a message",
        "leave your message",
        "after the tone",
        "after the beep",
        "voicemail",
        "voice mail",
        "record your message",
    ]
)
# Chỉ tổng đài mới nói những câu này
_OPERATOR = compile_phrases(
    [
        "thuê bao",
        "số máy quý khách vừa gọi",
        "quý khách vui lòng gọi lại sau",
        "ngoài vùng phủ sóng",
        "không có thực",
        "tạm thời không liên lạc được",
        "the number you have dialed",
        "the number you are calling",
        "the subscriber",
        "the person you are calling",
        "cannot be reached",
        "is not reachable",
        "does not exist",
        "line is busy",
        "please try again later",
    ]
)
_BUSY = compile_phrases(
    ["bận", "đang bận", "máy bận", "busy"], unaccented_exclude=["bận"]
)  # "ban" = bạn
_NO_ANSWER = compile_phrases(
    [
        "không liên lạc được",
        "tạm thời không liên lạc được",
        "ngoài vùng phủ sóng",
        "không có thực",
        "không trả lời",
        "cannot be reached",
        "is not reachable",
        "not available",
        "does not exist",
    ]
)


def extract_line_signal(transcript: str) -> Field[LineSignal]:
    text = clean(transcript)
    unaccented = is_unaccented(text)
    provenance = Provenance.NORMALIZED if unaccented else Provenance.EXACT

    def find(phrases):
        return find_phrase(text, phrases, unaccented=unaccented)

    voicemail = find(_VOICEMAIL)
    if voicemail is not None:
        return Field(LineSignal.VOICEMAIL, provenance, span=voicemail.group(0))

    operator = find(_OPERATOR)
    if operator is None:
        return Field.nothing(LineSignal.NONE)
    busy = find(_BUSY)
    if busy is not None:
        return Field(LineSignal.LINE_BUSY, provenance, span=busy.group(0))
    # Tổng đài không nói bận -> cuộc gọi không tới được người nghe
    no_answer = find(_NO_ANSWER)
    return Field(LineSignal.NO_ANSWER, provenance, span=(no_answer or operator).group(0))
