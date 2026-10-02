"""Tín hiệu đường dây — thiết kế v1.1 §5.9, hợp đồng rev 1.1 §1.1.7, §4.2.5.

Chạy trước mọi bộ khác trên cuộc gọi outbound cho tới khi xác minh xong danh tính — hợp đồng nói
harness gửi VOICEMAIL bằng một clip lời chào hộp thư, nhưng không nói clip đến ở lượt nào.
Kết quả khác NONE -> Policy kết thúc `UNREACHABLE` với `unreachable_reason` cùng tên;
Dialogue KHÔNG để lại chi tiết lịch hẹn trên hộp thư thoại.

- VOICEMAIL xét trước: "thuê bao không liên lạc được, vui lòng để lại lời nhắn" là đã vào hộp thư.
  Lời chào cá nhân ("bạn đã gọi đến số của Lan, hiện không thể nghe máy") cũng là VOICEMAIL (T-08).
- NO_ANSWER / LINE_BUSY come only from PhoneStatus, never from transcripts.
"""

from callbot.engine.extraction.schema import Field, LineSignal, Provenance
from callbot.engine.extraction.text import clean, compile_phrases, find_phrase, is_unaccented

# Lời tương tác trực tiếp phủ định việc đang nghe một thông báo tự động. Xét trước các từ
# như "hộp thư thoại" / "để lại tin nhắn": người thật cũng nhắc đến những từ này.
_HUMAN_SPEECH = compile_phrases(
    [
        "không phải hộp thư thoại",
        "không phải lời nhắn tự động",
        "tôi đang nghe",
        "tôi nghe đây",
        "có việc gì",
        "gọi có chuyện gì",
        "em để lại tin nhắn",
        "em để lại lời nhắn",
        "nhắn tin giúp tôi",
        "gọi lại sau nhé",
        "gọi lại sau giúp tôi",
        "gọi lại cho tôi",
        "call me later",
        "call me back",
        "this is not voicemail",
        "this is not a voicemail",
    ]
    + [
        f"{speaker} để lại {message} {request}"
        for speaker in ("anh", "chị", "em", "bạn", "cô", "chú")
        for message in ("lời nhắn", "tin nhắn")
        for request in ("cho", "giúp")
    ]
    + [f"là của {relative} tôi" for relative in ("mẹ", "bố", "cha", "vợ", "chồng", "con")]
)

_VOICEMAIL = compile_phrases(
    [
        "để lại lời nhắn",
        "sau tiếng bíp",
        "sau tiếng tít",
        "hộp thư thoại",
        "hợp thư thoại của thuê bao",  # lỗi ASR có ngữ cảnh tổng đài
        "đây là hộp thư của",
        "hộp thư của quý khách đã đầy",
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
        "automated voice messaging system",
        "mailbox is full",
        # T-08: lời chào hộp thư cá nhân không nói "để lại lời nhắn". Chỉ nhận cụm người đã nghe máy
        # gần như không nói: xưng "bạn đã gọi đến số" dạng thông báo.
        # KHÔNG nhận "không nghe máy được", "sẽ gọi lại cho bạn", "gọi lại sau": người thật đang bận
        # vẫn nói các câu đó, kết thúc UNREACHABLE với họ là case fail.
        "bạn đã gọi đến số",
        "bạn đã gọi tới số",
        "bạn vừa gọi đến số",
        "you have reached",
        "you've reached",
        "can't take your call",
        "cannot take your call",
        "unable to take your call",
        "can't come to the phone",
        "please leave your name",
    ]
)
# Lời cảm ơn hoặc thông báo đang bận riêng lẻ chưa chứng minh là bản ghi.
_RECORDED_GREETING = compile_phrases(["cảm ơn bạn đã gọi"])
_RECORDED_UNAVAILABLE = compile_phrases(
    ["hiện không thể trả lời cuộc gọi", "hiện chúng tôi không thể trả lời"]
)


def extract_line_signal(transcript: str) -> Field[LineSignal]:
    text = clean(transcript)
    unaccented = is_unaccented(text)
    provenance = Provenance.NORMALIZED if unaccented else Provenance.EXACT

    def find(phrases):
        return find_phrase(text, phrases, unaccented=unaccented)

    if find(_HUMAN_SPEECH) is not None:
        return Field.nothing(LineSignal.NONE)

    voicemail = find(_VOICEMAIL)
    if voicemail is None and find(_RECORDED_GREETING) is not None:
        voicemail = find(_RECORDED_UNAVAILABLE)
    if voicemail is not None:
        return Field(LineSignal.VOICEMAIL, provenance, span=voicemail.group(0))

    return Field.nothing(LineSignal.NONE)
