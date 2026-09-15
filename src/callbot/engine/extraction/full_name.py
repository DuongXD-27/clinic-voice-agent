"""Tên bệnh nhân — thiết kế v1.1 §5.1 (phần trích xuất).

Bộ trích xuất "mù" với hồ sơ: không biết tên đúng là gì, nên trích sai gần như luôn
dẫn tới *từ chối nhầm* ở Verifier (hướng an toàn, SF-03). So khớp với hồ sơ nằm ở Verifier.

Chỉ chạy khi `question_id == ASK_NAME`. Không chạy intent nghiệp vụ trên câu này, nên tên
chứa từ khoá ("Lê Văn Thôi", "Trần Văn Được") vẫn lấy được.

Transcript không dấu: tên được trả nguyên dạng không dấu ("nguyen van a"). Verifier phải so theo
chế độ bỏ dấu thanh đã có trong thiết kế §5.1 (tuần 3+), không được đoán lại dấu cho tên.
"""

from callbot.engine.extraction.schema import Field, Provenance
from callbot.engine.extraction.text import PhraseSet, clean, compile_phrases, is_unaccented, strip_diacritics

MIN_WORDS = 2
# Tên tiếng Việt dài nhất thường 5 từ; câu dài hơn gần như chắc là một câu nói, không phải tên.
MAX_WORDS = 6

_PREFIXES = compile_phrases(
    [
        "dạ", "vâng", "ạ", "alo", "a lô", "vâng ạ", "dạ vâng",
        "tôi là", "tên tôi là", "tôi tên là", "tên tôi", "em là", "tên em là", "em tên là", "tên em",
        "mình là", "tên mình là", "con là", "tên con là", "cháu là", "tên cháu là",
        "anh là", "chị là", "cô là", "chú là", "bác là", "ông là", "bà là",
        "họ tên là", "họ và tên là", "họ tên", "họ và tên",
    ],
    unaccented_exclude=["ạ"],  # "a" có thể là tên ("Nguyễn Văn A")
)
_SUFFIXES = compile_phrases(["ạ", "đây", "đây ạ", "nhé", "nha", "ấy ạ"], unaccented_exclude=["ạ", "ấy ạ"])
_GREETINGS = frozenset({"alo", "a lô", "xin chào", "chào", "chào em", "chào chị", "ai đấy", "ai vậy", "ai đó"})
# Từ chức năng không bao giờ là một phần tên: có chúng thì đây là câu nói, không phải tên.
# Cố ý KHÔNG đưa "được", "thôi", "anh" vào — đó là tên thật (Trần Văn Được, Lê Văn Thôi, Nguyễn Thị Anh).
_NON_NAME_WORDS = frozenset(
    {"là", "không", "gì", "ai", "đâu", "nào", "của", "muốn", "cần", "gọi", "hỏi", "tôi", "mình",
     "đấy", "vậy", "nhỉ", "sao", "chưa", "xin", "chào"}
)
# Không dấu: bỏ các từ trùng tên người khi mất dấu — "ai" (Ái), "dau" (Đậu), "nao", "can" (Cần), "hoi" (Hợi),
# "la" (La), "minh" (Minh), "day" (Đầy), "sao" (Sáo)
_NON_NAME_WORDS_UNACCENTED = frozenset({"khong", "gi", "cua", "muon", "goi", "toi", "vay", "nhi", "chua", "xin", "chao"})
_GREETINGS_UNACCENTED = frozenset(strip_diacritics(g) for g in _GREETINGS)


def extract_full_name(transcript: str) -> Field[str]:
    name = clean(transcript)
    unaccented = is_unaccented(name)
    name = _strip_repeated(name, _PREFIXES, unaccented, at_start=True)
    name = _strip_repeated(name, _SUFFIXES, unaccented, at_start=False)

    words = name.split()
    greetings = _GREETINGS_UNACCENTED if unaccented else _GREETINGS
    non_name_words = _NON_NAME_WORDS_UNACCENTED if unaccented else _NON_NAME_WORDS
    if (
        not name
        or name in greetings
        or any(c.isdigit() for c in name)
        or not MIN_WORDS <= len(words) <= MAX_WORDS
        or any(w in non_name_words for w in words)
    ):
        return Field.nothing()
    return Field(name, Provenance.NORMALIZED, span=name)


def _strip_repeated(text: str, phrases: PhraseSet, unaccented: bool, at_start: bool) -> str:
    """Bỏ lặp lại: "dạ vâng tên tôi là ..." -> bỏ lần lượt "dạ", "vâng", "tên tôi là"."""
    changed = True
    while changed and text:
        changed = False
        for phrase, _ in phrases.for_text(text, unaccented):
            if at_start and (text == phrase or text.startswith(phrase + " ")):
                text = text[len(phrase):].strip()
                changed = True
                break
            if not at_start and (text == phrase or text.endswith(" " + phrase)):
                text = text[: len(text) - len(phrase)].strip()
                changed = True
                break
    return text
