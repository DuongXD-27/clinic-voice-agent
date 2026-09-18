"""Tên bệnh nhân — thiết kế v1.1 §5.1 (phần trích xuất).

Bộ trích xuất "mù" với hồ sơ: không biết tên đúng là gì, nên trích sai gần như luôn
dẫn tới *từ chối nhầm* ở Verifier (hướng an toàn, SF-03). So khớp với hồ sơ nằm ở Verifier.

Chỉ chạy khi `question_id == ASK_NAME`. Không chạy intent nghiệp vụ trên câu này, nên tên
chứa từ khoá ("Lê Văn Thôi", "Trần Văn Được") vẫn lấy được.

Transcript không dấu: tên được trả nguyên dạng không dấu ("nguyen van a"). Verifier phải so theo
chế độ bỏ dấu thanh đã có trong thiết kế §5.1 (tuần 3+), không được đoán lại dấu cho tên.
"""

from typing import Optional

from callbot.engine.extraction.schema import Field, Provenance
from callbot.engine.extraction.spoken_numbers import is_number_token, parse_number
from callbot.engine.extraction.text import (
    PhraseSet,
    clean,
    compile_phrases,
    find_phrase,
    is_unaccented,
    normalize,
    strip_diacritics,
)

MIN_WORDS = 2
# Tên tiếng Việt dài nhất thường 5 từ; câu dài hơn gần như chắc là một câu nói, không phải tên.
MAX_WORDS = 6

_PREFIXES = compile_phrases(
    [
        "dạ",
        "vâng",
        "ạ",
        "alo",
        "a lô",
        "vâng ạ",
        "dạ vâng",
        "tôi là",
        "tên tôi là",
        "tôi tên là",
        "tên tôi",
        "em là",
        "tên em là",
        "em tên là",
        "tên em",
        "mình là",
        "tên mình là",
        "con là",
        "tên con là",
        "cháu là",
        "tên cháu là",
        "anh là",
        "chị là",
        "cô là",
        "chú là",
        "bác là",
        "ông là",
        "bà là",
        "họ tên là",
        "họ và tên là",
        "họ tên",
        "họ và tên",
    ],
    unaccented_exclude=["ạ"],  # "a" có thể là tên ("Nguyễn Văn A")
)
_SUFFIXES = compile_phrases(
    ["ạ", "đây", "đây ạ", "nhé", "nha", "ấy ạ", "mà"], unaccented_exclude=["ạ", "ấy ạ", "mà"]
)
_SELF_INTRODUCTIONS = compile_phrases(["tôi là", "tên tôi là", "tôi tên là"])
_OTHER_PERSON_INTRODUCTIONS = compile_phrases(
    [
        f"còn {relative} tôi là"
        for relative in ("em", "anh", "chị", "bố", "mẹ", "con", "vợ", "chồng")
    ]
)
_GREETINGS = frozenset(
    {"alo", "a lô", "xin chào", "chào", "chào em", "chào chị", "ai đấy", "ai vậy", "ai đó"}
)
# Từ chức năng không bao giờ là một phần tên: có chúng thì đây là câu nói, không phải tên.
# Cố ý KHÔNG đưa "được", "thôi", "anh" vào — đó là tên thật (Trần Văn Được, Lê Văn Thôi, Nguyễn Thị Anh).
_NON_NAME_WORDS = frozenset(
    {
        "là",
        "không",
        "gì",
        "ai",
        "đâu",
        "nào",
        "của",
        "muốn",
        "cần",
        "gọi",
        "hỏi",
        "tôi",
        "mình",
        "đấy",
        "vậy",
        "nhỉ",
        "sao",
        "chưa",
        "xin",
        "chào",
    }
)
# Không dấu: bỏ các từ trùng tên người khi mất dấu — "ai" (Ái), "dau" (Đậu), "nao", "can" (Cần), "hoi" (Hợi),
# "la" (La), "minh" (Minh), "day" (Đầy), "sao" (Sáo)
_NON_NAME_WORDS_UNACCENTED = frozenset(
    {"khong", "gi", "cua", "muon", "goi", "toi", "vay", "nhi", "chua", "xin", "chao"}
)
_GREETINGS_UNACCENTED = frozenset(strip_diacritics(g) for g in _GREETINGS)


def extract_full_name(transcript: str) -> Field[str]:
    name = clean(transcript)
    unaccented = is_unaccented(name)
    # Only isolate a first-person claim when the next clause explicitly names someone else.
    introduction = find_phrase(name, _SELF_INTRODUCTIONS, unaccented=unaccented)
    other_person = find_phrase(name, _OTHER_PERSON_INTRODUCTIONS, unaccented=unaccented)
    if (
        introduction
        and other_person
        and introduction.end() < other_person.start()
        and not _strip_repeated(name[: introduction.start()].strip(), _PREFIXES, unaccented, True)
    ):
        name = name[: other_person.start()].strip()
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


# Dấu hiệu phần ngày sinh bắt đầu trong câu trả lời gộp "tên + ngày sinh" (T-02)
_DATE_WORDS = frozenset({"ngày", "tháng", "năm", "mùng", "mồng"})
_DATE_WORDS_UNACCENTED = frozenset({"ngay", "thang", "nam", "mung", "mong"})
_DAY_STARTS = frozenset({"ngày", "mùng", "mồng"})
_DAY_STARTS_UNACCENTED = frozenset({"ngay", "mung", "mong"})
# Từ nối còn sót ở cuối phần tên: "Nguyễn Văn A và ngày sinh là ...". Không có "năm" / "sinh":
# vị trí cắt đã bỏ chúng, còn sót lại thì là tên ("Trần Văn Năm", "Nguyễn Văn Sinh").
_TRAILING_LINKS = frozenset({"là", "và", "thì"})
_TRAILING_LINKS_UNACCENTED = frozenset({"la", "va", "thi"})
_MONTH = frozenset({"tháng", "thang"})
_MAX_SPOKEN_DAY = 3  # "hai mươi mốt"
# Cắt ở "sinh" mà trước đó dưới 3 từ thì "Sinh" có thể là tên: "Nguyễn Văn Sinh ngày 14 ...", "Lê Na sinh ..."
_MIN_WORDS_BEFORE_SINH = 3


def name_before_dob(transcript: str) -> Optional[str]:
    """Phần tên đứng trước ngày sinh trong một câu, vd. "Nguyễn Văn A, sinh ngày 14/3/1978".

    Chỉ gọi khi đã trích được ngày sinh trong câu (span của `dob` là cả câu, không dùng để cắt được).
    Không tìm được ranh giới chắc chắn -> None: thà hỏi lại tên còn hơn đưa một tên bị cắt nhầm
    vào Verifier (tên sai -> chuyển máy ngay). Tên có thể là từ chỉ số ("Nguyễn Văn Tám", "Trần Văn
    Năm"), nên chỉ cắt ở dãy số đọc bằng chữ khi dãy đó không dính vào cuối tên.
    """
    unaccented = is_unaccented(clean(transcript))
    links = _TRAILING_LINKS_UNACCENTED if unaccented else _TRAILING_LINKS

    # Dấu phẩy là ranh giới rõ nhất (text mode): "Dạ, Nguyễn Văn Sinh, sinh năm 1978" — ghép các đoạn
    # cho tới đoạn có ngày sinh, rồi cắt trong đoạn đó.
    name: list[str] = []
    for segment in normalize(transcript).split(","):
        tokens = clean(segment).split()
        found = _date_start(tokens, unaccented)
        if found is None:
            name += tokens
            continue
        cut, at_sinh = found
        if cut < 0 or (at_sinh and 0 < cut < _MIN_WORDS_BEFORE_SINH):
            # "Nguyễn Văn Sinh ngày 14 ...": "Sinh" là tên hay từ nối? Không đoán.
            return None
        name += tokens[:cut]
        break
    else:
        return None  # không thấy phần ngày sinh

    while name and name[-1] in links:
        name.pop()
    return " ".join(name) or None


def _date_start(tokens: list[str], unaccented: bool) -> Optional[tuple[int, bool]]:
    """(vị trí từ đầu tiên của phần ngày sinh, có cắt ở "sinh" không); None nếu không có phần ngày sinh.

    Vị trí -1: có phần ngày sinh nhưng không cắt được chắc chắn.
    """
    date_words = _DATE_WORDS_UNACCENTED if unaccented else _DATE_WORDS
    day_starts = _DAY_STARTS_UNACCENTED if unaccented else _DAY_STARTS
    for i, token in enumerate(tokens):
        following = tokens[i + 1] if i + 1 < len(tokens) else ""
        if any(c.isdigit() for c in token) or token in day_starts:
            return i, False
        if token == "sinh" and (following in date_words or any(c.isdigit() for c in following)):
            # "năm sinh 1978": phần ngày bắt đầu từ "năm". Nhưng "Nam sinh năm 1978" (không dấu, tên Nam):
            # sau "sinh" đã là từ ngày tháng nên "nam" thuộc tên.
            if following not in date_words and i > 0 and tokens[i - 1] in date_words:
                return i - 1, True
            return i, True
        if not unaccented and is_number_token(token):
            run = i
            while run < len(tokens) and is_number_token(tokens[run]):
                run += 1
            if run < len(tokens) and tokens[run] in _MONTH:
                # Cả dãy phải đọc ra đúng một ngày: với "Nguyễn Văn Tám mười bốn tháng ba", dãy
                # "tám mười bốn" không phải ngày -> không biết "Tám" thuộc tên hay ngày
                day = parse_number(tokens[i:run]) if run - i <= _MAX_SPOKEN_DAY else None
                return (i if day is not None and 1 <= day <= 31 else -1), False
    return None


def _strip_repeated(text: str, phrases: PhraseSet, unaccented: bool, at_start: bool) -> str:
    """Bỏ lặp lại: "dạ vâng tên tôi là ..." -> bỏ lần lượt "dạ", "vâng", "tên tôi là"."""
    changed = True
    while changed and text:
        changed = False
        for phrase, _ in phrases.for_text(text, unaccented):
            if at_start and (text == phrase or text.startswith(phrase + " ")):
                text = text[len(phrase) :].strip()
                changed = True
                break
            if not at_start and (text == phrase or text.endswith(" " + phrase)):
                text = text[: len(text) - len(phrase)].strip()
                changed = True
                break
    return text
