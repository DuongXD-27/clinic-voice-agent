"""Câu chào xã giao ("alo", "dạ alo", "alo ai đấy", "xin chào") — cả câu chỉ có vậy.

Người nghe máy thường nói "alo" khi câu chào của bot còn đang phát hoặc chưa nghe rõ. Không phải tên,
không phải nhu cầu: Dialogue chào lại và hỏi lại, thay vì coi là chưa hiểu.
So trên bản bỏ dấu vì cả câu chỉ gồm các từ trong danh sách dưới đây (ASR hay trả "a lo", "alô").
"""

import re

from callbot.engine.extraction.text import clean, strip_diacritics

_HELLO = r"(?:a ?lo|xin chao|chao(?: (?:em|anh|chi|ban|co|chu|bac))?)"
_FILLER = (
    r"(?:da|vang|u|um|o|a|oi|nghe|day|em|anh|chi|toi nghe|nghe day|"
    r"ai (?:day|do|vay|the)|ai goi (?:day|do|vay|the)|ai the|ai a)"
)
_GREETING = re.compile(rf"(?:{_FILLER} )*{_HELLO}(?: (?:{_HELLO}|{_FILLER}))*")


def is_greeting(transcript: str) -> bool:
    return _GREETING.fullmatch(strip_diacritics(clean(transcript))) is not None
