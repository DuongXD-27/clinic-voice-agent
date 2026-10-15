"""Câu chào xã giao / hỏi bên gọi là ai — cả câu chỉ có vậy.

Người nghe máy thường nói "alo" khi câu chào của bot còn đang phát hoặc chưa nghe rõ. Không phải tên,
không phải nhu cầu: Dialogue chào lại và hỏi lại, thay vì coi là chưa hiểu.
So trên bản bỏ dấu vì cả câu chỉ gồm các từ trong danh sách dưới đây (ASR hay trả "a lo", "alô").
"""

import re

from callbot.engine.extraction.text import clean, strip_diacritics

_HELLO = r"(?:a ?lo|xin chao|chao|hello|hi)(?: (?:em|anh|chi|ban|co|chu|bac))?"
_FILLER = r"(?:da|vang|u|um|o|a|oi|nghe|day|em|anh|chi|nhi|toi nghe|nghe day)"
_ADDRESS = r"(?:em|anh|chi|ban|co|chu|bac|ong|ba|chau|con)"
# Gọi/đáp máy là hành vi giữ liên lạc, không phải tên hay câu trả lời đồng ý.
_CONTACT = (
    rf"(?:hu hu(?: hu)*|{_ADDRESS} oi|"
    rf"(?:(?:toi|{_ADDRESS}) )?(?:dang )?nghe(?: (?:day|may))?)"
)
_WHO = (
    r"(?:cho (?:toi )?hoi )?(?:"
    r"ai (?:day|do|vay|the|a)|"
    r"ai (?:dang )?goi(?: (?:day|do|vay|the))?|"
    r"(?:em|anh|chi|ban) la ai(?: (?:day|do|vay|the))?|"
    r"ben nao(?: (?:dang )?goi)?(?: (?:day|do|vay|the))?|"
    rf"{_ADDRESS} goi tu dau|ben {_ADDRESS} la ben nao|"
    r"(?:benh vien|tong dai|don vi) nao(?: (?:day|do|vay|the))?|"
    r"dau day ben kia la ai|(?:co phai )?(?:benh vien|vinmec) (?:a|ha|khong|phai khong|dung khong))"
)
_SOCIAL = rf"(?:{_HELLO}|{_WHO}|{_CONTACT})"
_GREETING = re.compile(rf"(?:{_FILLER} )*{_SOCIAL}(?: (?:{_SOCIAL}|{_FILLER}))*")
_IDENTITY_QUESTION = re.compile(rf"(?<!\w){_WHO}(?!\w)")
_HOLD = re.compile(r"(?:cho|doi|khoan)(?: toi)?(?: mot)? (?:chut|lat)(?: nhe|a|da|em)?")
_RETURN = re.compile(r"(?:da )?(?:roi )?toi day(?: roi| a| em)?")


def _social_text(transcript: str) -> str:
    text = clean(transcript)
    # "hụ hụ" / "hư hư" có thể là tiếng ho hay âm khác, không đồng nhất với "hú hú".
    if any(strip_diacritics(word) == "hu" and word not in {"hu", "hú"} for word in text.split()):
        return ""
    return strip_diacritics(text)


def is_greeting(transcript: str) -> bool:
    return _GREETING.fullmatch(_social_text(transcript)) is not None


def is_identity_question(transcript: str) -> bool:
    """Hỏi bot là ai: cần giới thiệu lại cả khi đã qua lời chào mở đầu.

    Chỉ nhận cả câu xã giao, tránh nuốt tên / nhu cầu / tín hiệu ưu tiên đi kèm.
    """
    text = _social_text(transcript)
    return _GREETING.fullmatch(text) is not None and _IDENTITY_QUESTION.search(text) is not None


def is_hold_request(transcript: str) -> bool:
    """Xin giữ máy, chưa trả lời câu hỏi đang chờ."""
    return _HOLD.fullmatch(strip_diacritics(clean(transcript))) is not None


def is_return_signal(transcript: str) -> bool:
    """Quay lại đường dây, chưa cung cấp danh tính hay xác nhận."""
    return _RETURN.fullmatch(strip_diacritics(clean(transcript))) is not None
