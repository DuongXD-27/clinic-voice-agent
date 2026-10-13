"""Tên bệnh nhân — thiết kế v1.1 §5.1 (phần trích xuất).

Bộ trích xuất "mù" với hồ sơ: không biết tên đúng là gì, nên trích sai gần như luôn
dẫn tới *từ chối nhầm* ở Verifier (hướng an toàn, SF-03). So khớp với hồ sơ nằm ở Verifier.

Chỉ chạy khi `question_id == ASK_NAME`. Không chạy intent nghiệp vụ trên câu này, nên tên
chứa từ khoá ("Lê Văn Thôi", "Trần Văn Được", "Nguyễn Văn Cần", "Nguyễn Thị Ái") vẫn lấy được:
câu nghiệp vụ bị loại theo *cụm* ("hủy lịch", "bảo hiểm"), không theo từng từ, nên
"Nguyễn Thanh Toàn" không bị nhầm thành câu hỏi về thanh toán.

Không đoán dấu, không sửa lỗi ASR, không thêm họ, không đối chiếu hồ sơ ở đây. Transcript
không dấu được trả nguyên dạng ("nguyen van a"); Verifier so theo chế độ bỏ dấu của §5.1.

Kết quả đầy đủ nằm ở `read_full_name`: ngoài giá trị còn có *lý do*, để tuyến sau chỉ được
gọi khi luật chưa hiểu câu, chứ không phải khi luật đã xác định là phủ định / phân vân /
câu nghiệp vụ.

Luật chỉ tự nhận tên khi có dấu hiệu họ tên (họ + tên đệm, hoặc họ Nguyễn / Huỳnh). Câu đúng
hình dạng nhưng thiếu dấu hiệu ("hôm qua ăn phở", "Lê Na") trả UNANCHORED cho slot filling.
"""

import re
from typing import Optional

from callbot.engine.extraction.dob import EN_MONTHS
from callbot.engine.extraction.greeting import is_greeting
from callbot.engine.extraction.honorific import is_honorific, strip_honorific
from callbot.engine.extraction.identity import (
    AFFIRMATIONS,
    ALTERNATIVES,
    CORRECTIONS,
    NEGATIONS,
    UNCERTAINTY,
    Reading,
    Reason,
    english_hedge,
    strip_english_opener,
)
from callbot.engine.extraction.schema import Field, Provenance
from callbot.engine.extraction.spoken_numbers import is_number_token, parse_number
from callbot.engine.extraction.text import (
    PhraseSet,
    clean,
    compile_phrases,
    find_last_phrase,
    find_phrase,
    is_unaccented,
    normalize,
    strip_diacritics,
)

MIN_WORDS = 2
# Tên tiếng Việt dài nhất thường 5 từ; câu dài hơn gần như chắc là một câu nói, không phải tên.
MAX_WORDS = 6

# Người gọi tự xưng bằng nhiều đại từ tuỳ vai vế. Sinh đủ tổ hợp thay vì liệt kê tay: thiếu
# một dạng thì câu trả lời hoặc bị bỏ qua ("Tôi tên Nguyễn Văn A" -> NONE), hoặc tệ hơn, cả
# cụm tự giới thiệu đi thẳng vào Verifier như một cái tên ("em tên nguyễn văn a").
_SPEAKERS = ("tôi", "em", "mình", "con", "cháu", "anh", "chị", "cô", "chú", "bác", "ông", "bà")
_SELF_INTRO_PHRASES = [
    phrase
    for speaker in _SPEAKERS
    for phrase in (
        f"{speaker} là",
        f"{speaker} tên",
        f"{speaker} tên là",
        f"tên {speaker}",
        f"tên {speaker} là",
        f"họ tên của {speaker} là",
        f"họ và tên của {speaker} là",
        f"tên đầy đủ của {speaker} trên giấy tờ là",
    )
]
# "X tôi là ...": người gọi khai tên người khác, không phải tên mình.
_RELATIVES = (
    "em",
    "anh",
    "chị",
    "bố",
    "mẹ",
    "ba",
    "má",
    "con",
    "vợ",
    "chồng",
    "ông",
    "bà",
    "cháu",
    "cô",
    "chú",
    "bác",
)

# Người gọi nói tiếng Anh (QC qc-w6-01): "My name is Nguyen Van A", "I'm Nguyen Van A". Chỉ bỏ ở đầu
# câu như lời tự giới thiệu tiếng Việt; tên còn lại vẫn phải qua kiểm tra hình dạng họ tên.
_ENGLISH_INTROS = [
    "yes",
    "yeah",
    "my name is",
    "my full name is",
    "my name s",
    "the name is",
    "name is",
    "this is",
    "it is",
    "it s",
    "i am",
    "i m",
]

# Tiếng đệm đầu câu ("à thì tôi là ...", "ừm, tôi tên ...") bỏ như lời đáp lễ. Không dấu thì giữ:
# "a", "u", "o", "thi" có thể là một phần tên.
_FILLERS = ["à", "ừ", "ờ", "ừm", "thì"]
_PREFIXES = compile_phrases(
    ["dạ", "vâng", "ạ", "alo", "a lô", "vâng ạ", "dạ vâng"]
    + _FILLERS
    + _SELF_INTRO_PHRASES
    + ["họ tên là", "họ và tên là", "họ tên", "họ và tên", "chào em", "em ơi", "hú hú"]
    + _ENGLISH_INTROS,
    unaccented_exclude=["ạ", *_FILLERS],  # "a" có thể là tên ("Nguyễn Văn A")
)
# Họ tên đầy đủ tối thiểu còn lại sau khi bỏ danh xưng ("ông Nguyễn Văn A" -> 3 từ). Tên ngắn hơn
# giữ nguyên danh xưng ("Chu Văn An" có thể là họ Chu); Verifier tự so cả hai dạng.
MIN_WORDS_AFTER_HONORIFIC = 3
# Tự nhận ở CUỐI câu: "Nguyễn Văn A là tên chú", "Trần Thị Mai, đấy là tên bà". Người lớn tuổi hay
# tự xưng ông / bà / chú / bác thay cho "tôi"; không kèm "tôi / của tôi" thì là chính người gọi —
# có từ sở hữu ("là tên ông tôi") là người thân, xem `_RELATIVE_CLAIMS`.
_SELF_OUTRO_PHRASES = [
    f"{lead}là tên {possessive}{speaker}"
    for speaker in _SPEAKERS
    for lead in ("", "đấy ", "đó ", "đây ", "thì ")
    for possessive in ("", "của ")
]
# Chỉ bỏ danh xưng cuối câu khi có tiểu từ đứng TRƯỚC: "nhé em", "nha chị".
# Không bỏ riêng "em" / "anh", hay cả "em nhé": đó có thể là tên Nguyễn Văn Em.
_POLITE_ADDRESSES = [
    f"{particle} {addressee}"
    for particle in ("nhé", "nhá", "nha", "ạ", "đây", "đó", "cảm ơn", "cám ơn")
    for addressee in ("em", "anh", "chị", "bạn", "cô", "chú", "bác", "ông", "bà", "con", "cháu")
]
_SUFFIXES = compile_phrases(
    [
        "ạ",
        "đây",
        "đây ạ",
        "nhé",
        "nhá",
        "nha",
        "ấy ạ",
        "mà",
        "speaking",
        "here",
        *_SELF_OUTRO_PHRASES,
        *_POLITE_ADDRESSES,
        *(f"{phrase} ơi" for phrase in _POLITE_ADDRESSES),
    ],
    unaccented_exclude=[
        "ạ",
        "ấy ạ",
        "mà",
        *(p for p in _POLITE_ADDRESSES if p.startswith("ạ ")),
        *(f"{p} ơi" for p in _POLITE_ADDRESSES if p.startswith("ạ ")),
    ],
)
_SELF_INTRODUCTIONS = compile_phrases(_SELF_INTRO_PHRASES)
_OTHER_PERSON_INTRODUCTIONS = compile_phrases([f"còn {relative} tôi là" for relative in _RELATIVES])
# Người gọi khai tên người khác. Không có lời tự giới thiệu nào khác trong câu -> không phải
# tên người gọi, và tuyến sau cũng không được biến nó thành tên người gọi.
_RELATIVE_CLAIMS = compile_phrases(
    [
        phrase
        for relative in _RELATIVES
        for phrase in (
            f"{relative} tôi là",
            f"tên {relative} tôi",  # "... là tên ông tôi"
            f"{relative} của tôi",
            f"tên {relative} của tôi",  # "tên chú của tôi là ...": trùng vị trí với "tên chú"
        )
    ]
    + ["gọi hộ", "gọi giúp", "gọi thay"]
)
_GREETINGS = frozenset(
    {"alo", "a lô", "xin chào", "chào", "chào em", "chào chị", "ai đấy", "ai vậy", "ai đó"}
)
# Câu nghiệp vụ và lời đệm bị loại theo CỤM, không theo từ đơn: một từ trùng từ khoá
# ("Nguyễn Thanh Toàn", "Trần Văn Lịch") không đủ để kết luận đây không phải tên.
_NOT_A_NAME_PHRASES = compile_phrases(
    [
        "hủy lịch",
        "hủy hẹn",
        "hủy cuộc hẹn",
        "đổi lịch",
        "đổi hẹn",
        "dời lịch",
        "đặt lịch",
        "đặt hẹn",
        "lịch hẹn",
        "lịch khám",
        "đi khám",
        "tái khám",
        "khám bệnh",
        "bảo hiểm",
        "thanh toán tiền",
        "bác sĩ",
        "nhân viên",
        "tổng đài",
        "bệnh viện",
        "phòng khám",
        "để xem",
        "để tôi xem",
        "đợi chút",
        "chờ chút",
        "từ từ",
    ],
    unaccented_exclude=["từ từ"],  # "tu tu" mất dấu trùng "tự tử"
)
# Từ chức năng không bao giờ là một phần tên: có chúng thì đây là câu nói, không phải tên.
# Cố ý KHÔNG đưa vào: "được", "thôi", "anh" (Trần Văn Được, Lê Văn Thôi, Nguyễn Thị Anh),
# "ai" (Nguyễn Thị Ái), "cần" (Nguyễn Văn Cần) — những câu chứa chúng đã bị loại bằng cụm.
_NON_NAME_WORDS = frozenset(
    {
        "là",
        "không",
        "gì",
        "đâu",
        "nào",
        "của",
        "muốn",
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
# Không dấu: bỏ các từ trùng tên người khi mất dấu — "ai" (Ái), "dau" (Đậu), "nao", "can" (Cần),
# "hoi" (Hợi), "la" (La), "minh" (Minh), "day" (Đầy), "sao" (Sáo)
_NON_NAME_WORDS_UNACCENTED = frozenset(
    {"khong", "gi", "cua", "muon", "goi", "toi", "vay", "nhi", "chua", "xin", "chao"}
)
# So theo từng từ: từ có dấu tra bảng có dấu, từ không dấu tra bảng không dấu. Hai bảng
# không giao nhau về mặt chữ, nên hợp nhất là đủ và xử lý được cả câu mất dấu một phần.
_REJECTED_WORDS = _NON_NAME_WORDS | _NON_NAME_WORDS_UNACCENTED
_REJECTED_NAMES = _GREETINGS | frozenset(strip_diacritics(g) for g in _GREETINGS)
# Qua kiểm tra số từ chưa đủ để kết luận là tên. Lời nói còn sót phải được slot filling khoanh
# vùng lại; tắt/lỗi slot filling thì hỏi lại, không đưa cả "Nguyễn Văn A cảm ơn em" tới Verifier.
# Các từ mất dấu trùng tên (Chu, Vang, Roi, A...) không dùng riêng làm tín hiệu này.
_SPEECH_RESIDUE = compile_phrases(
    [
        "ạ",
        "nhé",
        "nhá",
        "ơi",
        "vâng",
        "chứ",
        "rồi",
        "nè",
        "cảm ơn",
        "cám ơn",
        "đúng rồi",
        "hello",
        "alo",
        "hi em",
        "hú hú",
        *_POLITE_ADDRESSES,
        *(f"{particle} {addressee}" for particle in ("đây", "đó") for addressee in _SPEAKERS),
    ],
    unaccented_exclude=[
        "ạ",
        "nhé",
        "nhá",  # "nha" mất dấu có thể là tên (Nguyễn Thị Nha)
        "ơi",
        "vâng",
        "chứ",
        "rồi",
        "nè",
        *(p for p in _POLITE_ADDRESSES if p.startswith("ạ ")),
    ],
)
# Cách người gọi trỏ tới trường ngày sinh — dùng để biết một mệnh đề đang nói về ngày sinh
# chứ không phải về tên.
_DOB_REFERENCES = compile_phrases(
    ["ngày sinh", "năm sinh", "sinh ngày", "sinh năm", "ngày tháng năm sinh"]
)
# ASR có thể bỏ dấu phẩy trước lời báo không nhớ ngày sinh. Chỉ tách một hậu tố
# trọn vẹn nói về ngày sinh; không cắt theo từ "không nhớ" đứng riêng (có thể nói về tên).
_DOB_SUBJECT = r"(?:ngày tháng năm sinh|ngày sinh|năm sinh)"
_DOB_UNCERTAINTY = r"(?:không nhớ(?: rõ| lắm| chính xác)?|không chắc|không rõ lắm)"
_DOB_ASIDE_PATTERN = (
    rf"(?<!\w)(?:(?:tôi )?{_DOB_UNCERTAINTY} (?:về )?{_DOB_SUBJECT}"
    rf"|{_DOB_SUBJECT} (?:thì )?(?:tôi )?{_DOB_UNCERTAINTY})(?: ạ)?$"
)
_DOB_ASIDE_SUFFIXES = (
    re.compile(_DOB_ASIDE_PATTERN),
    re.compile(strip_diacritics(_DOB_ASIDE_PATTERN)),
)

# --- Dấu hiệu tích cực của một họ tên ---------------------------------------------------------
# Loại câu nói thường bằng danh sách từ cấm không bao giờ đủ ("trời hôm nay đẹp quá", "trần nhà").
# Luật chỉ tự nhận tên khi có dấu hiệu họ tên; thiếu dấu hiệu thì trả UNANCHORED để slot filling
# quyết định. Các bảng dưới đây chỉ chặn luật, không chặn tên do slot filling trả về
# (`valid_name_span`): tên thật bị chặn nhầm không bị luật loại vĩnh viễn, nhưng có được nhận
# hay không vẫn tùy mô hình.


def _word_pairs(listing: str) -> frozenset[str]:
    return frozenset(" ".join(pair.split()) for pair in listing.split("|"))


# Họ không trùng từ thông dụng nào: đủ làm dấu hiệu, kể cả tên hai từ ("Nguyễn Lan").
_UNIQUE_SURNAMES = frozenset({"nguyễn", "huỳnh"})
# Không có "Lại": quá hay đứng đầu câu ("lại thu tiền à").
_SURNAMES = frozenset(
    """nguyễn trần lê phạm hoàng huỳnh phan vũ võ đặng bùi đỗ hồ ngô dương lý lưu trương đinh
    đoàn lâm mai trịnh cao hà tô tạ châu chu quách thái tăng lương kiều đào tống lạc mạc khúc
    kim la lục lữ mã nghiêm ninh phí phùng quan tôn thân thạch triệu từ văn viên vương vi âu
    ông bạch bế cù diệp doãn giang giáp hàn hầu hứa khổng khương lò mẫn nông ôn phó quản sầm
    sơn tiêu trình ứng đàm đồng đường nhan lăng lã hoa cung công bành biện cấn chế chử đậu kha
    khiếu khuất lỗ ngụy nhâm phương quang thiều tiết trà vưu lường cầm điêu mùa giàng thào vàng
    sùng lầu tráng ma lành quàng""".split()
)
# Tên đệm đặc trưng. Không có "Anh": "mai anh bận" không được thành tên.
_MIDDLE_NAMES = frozenset(
    """văn thị hữu đức công quốc ngọc thanh xuân hồng bảo gia quang đình trọng thế minh kim
    thu hoàng mạnh việt hải khánh phúc nhật duy thùy mỹ diệu""".split()
)
# Họ + tên đệm ghép thành từ thông dụng: "trịnh trọng quá", "đồng minh thân thiết".
_HEAD_COMPOUNDS = _word_pairs(
    """công văn|hoa văn|thân hữu|công hữu|công đức|vũ công|thủ công|ông công|nông công|hàn quốc|
    vương quốc|châu ngọc|bạch ngọc|mùa xuân|hoa hồng|hoàng gia|tăng gia|hồ quang|huỳnh quang|
    trịnh trọng|tôn trọng|quan trọng|nghiêm trọng|trần thế|thân thế|đồng minh|văn minh|
    quang minh|cao minh|hoàng kim|bạch kim|mùa thu|lê minh"""
)
# Tên đệm + từ thứ ba ghép thành từ thông dụng: "từ thị trấn lên", "hồ thu hoạch".
_TAIL_COMPOUNDS = _word_pairs(
    """thị trấn|thị xã|thị trường|thị lực|văn phòng|văn bản|văn hóa|công việc|công ty|công an|
    quốc tế|thanh toán|thanh tra|bảo hiểm|bảo vệ|bảo hành|gia đình|gia hạn|quang cảnh|đình chỉ|
    trọng tâm|trọng lượng|thế giới|thế nào|kim tiêm|hải quan|nhật ký|duy trì|mạnh khỏe|việt nam|
    hữu ích|mỹ phẩm|thu hoạch|thu tiền|thu nhập|minh họa|hoàng hôn|xuân hè|khánh thành|
    phúc lợi|hồng cầu|đức tin|ngọc trai"""
)
# Không dấu thì "X van" / "X thi" trùng câu nói thường ở các họ này: "tu van" (tư vấn),
# "do thi" (đô thị), "ho thi" (họ thì), "lai van" (lại vẫn), "phan van" (phân vân).
_UNACCENTED_AMBIGUOUS = frozenset(
    "lai ma tu do vi cung phan hoa cong la ho ong mai ha dong quan than chu".split()
)
_UNACCENTED_UNIQUE = frozenset({"nguyen", "huynh"})
_UNACCENTED_SURNAMES = frozenset(strip_diacritics(s) for s in _SURNAMES) - _UNACCENTED_AMBIGUOUS
# Không dấu chỉ tin "văn" / "thị": tên đệm khác mất dấu trùng quá nhiều từ ("the", "minh").
_UNACCENTED_MIDDLE_NAMES = frozenset({"van", "thi"})


def extract_full_name(transcript: str) -> Field[str]:
    return read_full_name(transcript).field


def valid_name_span(name: str) -> bool:
    """Validate a slot-filling span without treating a possible final name syllable as a particle.

    Selecting the boundary is the model's job here. The rule extractor must remain
    conservative when it sees an entire utterance ending in an ambiguous particle.
    Name-anchor tables do not apply: they only decide when the rule defers to the model.
    """
    normalized = clean(name)
    return (
        bool(normalized)
        and read_full_name(normalized, preserve_final_nha=True, require_anchor=False).field.value
        == normalized
    )


def read_full_name(
    transcript: str, *, preserve_final_nha: bool = False, require_anchor: bool = True
) -> Reading[str]:
    clauses = [clause for clause in (clean(c) for c in normalize(transcript).split(",")) if clause]
    text = " ".join(clauses)
    if not text:
        return Reading(Field.nothing(), Reason.NO_SIGNAL)
    # Dùng chung nhận diện với Dialogue. Lời chào đã rõ nghĩa không phải tên,
    # nên không mở tuyến slot filling để nhận lại "hello em" / "hi em" thành tên người gọi.
    if is_greeting(text):
        return Reading(Field.nothing(), Reason.NOT_A_NAME, text)
    if find_phrase(text, _NOT_A_NAME_PHRASES, mixed=True) is not None:
        return Reading(Field.nothing(), Reason.NOT_A_NAME, text)

    # Lời phân vân trong một mệnh đề nói riêng về ngày sinh là phân vân về NGÀY SINH:
    # "Nguyễn Văn A, tôi không nhớ rõ ngày sinh" vẫn khai tên rõ ràng, chỉ thiếu ngày.
    # Giữ ranh giới mệnh đề: "alo em, tôi là A" không được ghép thành "em tôi là A"
    # rồi hiểu nhầm đó là tên người thân. Chỉ bỏ mệnh đề xã giao đã nhận chắc chắn.
    # "Sorry, my name is …": lời mở câu tiếng Anh là lễ phép; "A, sorry, B" giữa câu vẫn là tự sửa.
    name_clauses = [
        _strip_dob_aside(strip_english_opener(c) if i == 0 else c) for i, c in enumerate(clauses)
    ]
    named = " ".join(c for c in name_clauses if c and not is_greeting(c) and not _is_dob_aside(c))
    if not named:
        return Reading(Field.nothing(), Reason.UNCERTAIN, text)
    if find_phrase(named, UNCERTAINTY, mixed=True) is not None or english_hedge(named, date=False):
        # "chắc là Nguyễn Văn A", "maybe Nguyen Van A": chưa đủ chắc để đi xác minh — hỏi lại, và
        # mô hình cũng không được biến câu này thành một tên.
        return Reading(Field.nothing(), Reason.UNCERTAIN, text)

    segment = _affirmed_segment(named)
    if segment is None:
        return Reading(Field.nothing(), Reason.NEGATED, text)
    if _competing_names(segment):
        return Reading(Field.nothing(), Reason.AMBIGUOUS, segment)

    own = _own_claim(segment)
    if own is None:
        return Reading(Field.nothing(), Reason.OTHER_PERSON, segment)
    segment = own

    name = _strip_repeated(segment, _PREFIXES, at_start=True)
    unstripped = name
    if preserve_final_nha and name.endswith(" nha"):
        # Slot filling chose the complete span "Nguyễn Thị Nha". Do not immediately undo that
        # choice using the whole-utterance rule that also handles "Nguyễn Văn A nha".
        name = f"{_strip_repeated(name[:-4], _SUFFIXES, at_start=False)} nha"
    else:
        name = _strip_repeated(name, _SUFFIXES, at_start=False)
    removed_suffix = unstripped[len(name) :].strip() if unstripped.startswith(name) else ""
    name = strip_honorific(name, MIN_WORDS_AFTER_HONORIFIC)
    words = name.split()
    if not preserve_final_nha and _ambiguous_ending(name, removed_suffix):
        return Reading(Field.nothing(), Reason.UNRESOLVED_BOUNDARY, segment)
    if find_phrase(name, _SPEECH_RESIDUE, mixed=True) is not None:
        return Reading(Field.nothing(), Reason.UNRESOLVED_BOUNDARY, segment)
    if (
        not name
        or name in _REJECTED_NAMES
        or any(c.isdigit() for c in name)
        or not MIN_WORDS <= len(words) <= MAX_WORDS
        or any(w in _REJECTED_WORDS for w in words)
        # "T T B", "A B C": ASR nghe người gọi đánh vần / nói tắt. Không tên nào toàn chữ cái
        # đơn, và đưa nó vào Verifier là chuyển máy ngay thay vì hỏi lại tên.
        or all(len(w) == 1 for w in words)
    ):
        return Reading(Field.nothing(), Reason.NO_SIGNAL, segment)
    if require_anchor and not _has_name_anchor(words):
        # "trời hôm nay đẹp quá", "trần nhà": đúng hình dạng nhưng không có dấu hiệu họ tên
        return Reading(Field.nothing(), Reason.UNANCHORED, segment)
    return Reading(Field(name, Provenance.NORMALIZED, span=name), Reason.OK, segment)


def _has_name_anchor(words: list[str]) -> bool:
    """Có dấu hiệu họ tên; danh xưng còn giữ ("bà Nguyễn Lan") được bỏ qua khi xét."""
    return _anchored(words) or (is_honorific(words[0]) and _anchored(words[1:]))


def _anchored(words: list[str]) -> bool:
    if len(words) < 2:
        return False
    if is_unaccented(" ".join(words)):
        return len(words) >= 3 and (
            words[0] in _UNACCENTED_UNIQUE
            or (words[0] in _UNACCENTED_SURNAMES and words[1] in _UNACCENTED_MIDDLE_NAMES)
        )
    if " ".join(words[:2]) in _HEAD_COMPOUNDS or " ".join(words[1:3]) in _TAIL_COMPOUNDS:
        return False
    if words[0] in _UNIQUE_SURNAMES:
        return True
    return len(words) >= 3 and words[0] in _SURNAMES and words[1] in _MIDDLE_NAMES


_BARE_PARTICLES = frozenset({"nhé", "nhe", "nhá", "ạ"})


def _ambiguous_ending(candidate: str, removed_suffix: str) -> bool:
    """A terminal particle may instead be the last syllable of someone's name."""
    explicit_address = any(
        removed_suffix == phrase or removed_suffix.startswith(phrase + " ")
        for phrase in _POLITE_ADDRESSES
        if phrase.startswith("nha ")
    )
    if removed_suffix.split()[:1] == ["nha"] and not explicit_address:
        return True
    # "Nguyễn Văn A em nhé" and "Nguyễn Văn Em nhé" have the same surface
    # boundary problem. Only an explicit "nhé em" puts the addressee outside the name.
    # Judge by the stripped suffix, not the sentence end: "em nhé ạ" stacks particles.
    trailing = removed_suffix.split()
    return (
        bool(trailing)
        and set(trailing) <= _BARE_PARTICLES
        and any(candidate.endswith(" " + speaker) for speaker in (*_SPEAKERS, "bạn"))
    )


def _strip_dob_aside(clause: str) -> str:
    for pattern in _DOB_ASIDE_SUFFIXES:
        match = pattern.search(clause)
        if match is not None:
            return clause[: match.start()].strip()
    return clause


def _is_dob_aside(clause: str) -> bool:
    """Mệnh đề chỉ nói về ngày sinh, kèm lời phân vân hoặc phủ định của riêng nó.

    Phạm vi phải gắn với đúng trường: "tôi không nhớ rõ ngày sinh" không nói gì về tên, nên
    nó không được làm mất một cái tên đã khai rõ ở mệnh đề trước.
    """
    return find_phrase(clause, _DOB_REFERENCES, mixed=True) is not None and (
        find_phrase(clause, UNCERTAINTY, mixed=True) is not None
        or find_phrase(clause, NEGATIONS, mixed=True) is not None
    )


def _competing_names(segment: str) -> bool:
    """ "A hay B" là hai ứng viên chỉ khi hai bên đều đủ dài để là một tên.

    "Nguyễn Thị Hay", "Nguyễn Hay Anh": "Hay" là một âm trong tên, không phải từ nối giữa
    hai cái tên đang phân vân.
    """
    for _, pattern in ALTERNATIVES.for_text(segment, mixed=True):
        for match in pattern.finditer(segment):
            before = segment[: match.start()].split()
            after = segment[match.end() :].split()
            if len(before) >= MIN_WORDS and len(after) >= MIN_WORDS:
                return True
    return False


def _affirmed_segment(text: str) -> Optional[str]:
    """Mệnh đề được khẳng định sau cùng; `None` nếu người gọi chỉ bác bỏ.

    "A, à nhầm B" -> B. "không phải A" -> None. "không phải A mà là B" -> B.

    Cụm nằm ở cuối vùng tên ("... Nguyễn Văn A, không phải" — phần ngày sinh phía sau đã bị
    cắt đi) thuộc về trường kia: nó không còn bác bỏ tên nào nữa, nên giữ phần trước nó.
    """
    negation = find_last_phrase(text, NEGATIONS, mixed=True)
    correction = find_last_phrase(text, CORRECTIONS, mixed=True)
    marker = max(
        (m for m in (negation, correction) if m is not None), key=lambda m: m.end(), default=None
    )
    if marker is None:
        return text
    tail = text[marker.end() :].strip()
    if not tail:
        return text[: marker.start()].strip()
    if marker is not negation:
        return tail
    affirmation = find_phrase(tail, AFFIRMATIONS, mixed=True)
    return tail[affirmation.end() :].strip() if affirmation is not None else None


def _earliest(text: str, phrases: PhraseSet) -> Optional[re.Match[str]]:
    """Lần khớp SỚM NHẤT trong câu; hoà thì lấy cụm dài hơn.

    `find_phrase` duyệt cụm dài trước rồi trả ngay, nên với "Tôi tên A, còn em tôi là B" nó
    bắt "tôi là" nằm *bên trong* "em tôi là" ở cuối câu và bỏ qua "tôi tên" ở đầu — rồi kết
    luận nhầm rằng người gọi chỉ khai tên người khác. Thứ tự trong câu mới là thứ quyết định
    ai đang giới thiệu ai.
    """
    matches = [
        m for _, pattern in phrases.for_text(text, mixed=True) for m in pattern.finditer(text)
    ]
    return min(matches, key=lambda m: (m.start(), -m.end())) if matches else None


def _own_claim(text: str) -> Optional[str]:
    """Phần câu nói về chính người gọi; `None` nếu câu chỉ khai tên người khác."""
    introduction = _earliest(text, _SELF_INTRODUCTIONS)
    other = _earliest(text, _OTHER_PERSON_INTRODUCTIONS)
    if (
        introduction is not None
        and other is not None
        and introduction.end() < other.start()
        and not _strip_repeated(text[: introduction.start()].strip(), _PREFIXES, at_start=True)
    ):
        # "Tôi là A, còn em tôi là B": chỉ lấy vế đầu
        return text[: other.start()].strip()
    relative = _earliest(text, _RELATIVE_CLAIMS)
    # Cùng vị trí bắt đầu ("tên chú" / "tên chú của tôi"): cụm người thân dài hơn mới là nghĩa đúng
    if relative is not None and (introduction is None or relative.start() <= introduction.start()):
        return None
    return text


# Dấu hiệu phần ngày sinh bắt đầu trong câu trả lời gộp "tên + ngày sinh" (T-02)
_DATE_WORDS = frozenset(
    {"ngày", "tháng", "năm", "mùng", "mồng", "ngay", "thang", "nam", "mung", "mong"}
)
_DAY_STARTS = frozenset({"ngày", "mùng", "mồng", "ngay", "mung", "mong"})
# Từ nối còn sót ở cuối phần tên: "Nguyễn Văn A và ngày sinh là ...". Không có "năm" / "sinh":
# vị trí cắt đã bỏ chúng, còn sót lại thì là tên ("Trần Văn Năm", "Nguyễn Văn Sinh").
_TRAILING_LINKS = frozenset({"là", "và", "thì", "la", "va", "thi"})
# Cụm nối tiếng Anh trước ngày sinh: "Nguyen Van A, born on March 14, 1978". Chỉ bỏ cả cụm, không
# bỏ từ lẻ: "my", "on" một mình có thể là âm tên không dấu ("Nguyen Thi My").
_ENGLISH_TRAILING_LINKS = [
    "born on",
    "born in",
    "born",
    "and my date of birth is",
    "my date of birth is",
    "date of birth is",
    "date of birth",
    "and my birthday is",
    "my birthday is",
    "birthday is",
    "birthday",
    "dob is",
    "dob",
    "and",
]
_MONTH = frozenset({"tháng", "thang"})
_MAX_SPOKEN_DAY = 3  # "hai mươi mốt"
# Cắt ở "sinh" mà trước đó dưới 3 từ TÊN thì "Sinh" có thể là tên: "Nguyễn Văn Sinh ngày 14 ...",
# "Lê Na sinh ...". Đếm sau khi bỏ tiền tố, nếu không "Tôi là" sẽ làm câu trông đủ dài.
_MIN_WORDS_BEFORE_SINH = 3


def name_before_dob(transcript: str, dob_zone: Optional[str] = None) -> Optional[str]:
    """Phần tên đứng trước ngày sinh trong một câu, vd. "Nguyễn Văn A, sinh ngày 14/3/1978".

    Chỉ gọi khi đã nhận ra một vùng ngày trong câu. Không tìm được ranh giới chắc chắn -> None:
    thà hỏi lại tên còn hơn đưa một tên bị cắt nhầm vào Verifier (tên sai -> chuyển máy ngay).
    Tên có thể là từ chỉ số ("Nguyễn Văn Tám", "Trần Văn Năm"), nên chỉ cắt ở dãy số đọc bằng
    chữ khi dãy đó không dính vào cuối tên.

    Ngày tiếng Anh ("born on May 14, 1978", "March the 14th, 1978") cắt đúng ở vùng `dob_zone` mà
    `read_dob` đã nhận, để hai bộ phân tích không dùng hai luật ranh giới khác nhau.
    """
    if dob_zone and _english_zone(dob_zone):
        return _name_before_zone(transcript, dob_zone)
    name: list[str] = []
    for segment in normalize(transcript).split(","):
        tokens = clean(segment).split()
        found = _date_start(tokens)
        if found is None:
            name += tokens
            continue
        cut, at_sinh = found
        if cut < 0:
            return None
        if at_sinh and 0 < _claim_length(name + tokens[:cut]) < _MIN_WORDS_BEFORE_SINH:
            # "Tôi là Nguyễn Văn Sinh ngày 14/3/1978": "Sinh" là tên hay từ nối? Không đoán,
            # và tuyệt đối không trả về "nguyễn văn".
            return None
        name += tokens[:cut]
        break
    else:
        return None  # không thấy phần ngày sinh
    return _without_trailing_links(name)


def _english_zone(zone: str) -> bool:
    """Vùng ngày do bộ đọc ngày tiếng Anh dựng ra (có tên tháng tiếng Anh)."""
    return any(word in EN_MONTHS for word in zone.split())


def _zone_at(words: list[str], zone: str) -> Optional[int]:
    target = zone.split()
    return next(
        (i for i in range(len(words) - len(target) + 1) if words[i : i + len(target)] == target),
        None,
    )


def _name_before_zone(transcript: str, zone: str) -> Optional[str]:
    words = clean(transcript).split()
    at = _zone_at(words, zone)
    if not at:
        return None  # vùng ngày ở đầu câu (tên đứng sau) hoặc không tìm thấy
    name = words[:at]
    if name[-1] == "sinh":
        if _claim_length(name[:-1]) < _MIN_WORDS_BEFORE_SINH:
            return None  # "Nguyễn Văn Sinh March 14 1978": không đoán
        name.pop()
    return _without_trailing_links(name)


def _without_trailing_links(name: list[str]) -> Optional[str]:
    name = list(name)
    while name and name[-1] in _TRAILING_LINKS:
        name.pop()
    stripped = True
    while stripped:
        stripped = False
        for phrase in _ENGLISH_TRAILING_LINKS:
            words = phrase.split()
            if len(name) > len(words) and name[-len(words) :] == words:
                del name[-len(words) :]
                stripped = True
                break
    return " ".join(name) or None


def introduces_oneself(transcript: str) -> bool:
    """Câu có lời tự giới thiệu ("tôi là", "tên tôi là"...), so như `name_after_dob`."""
    return find_phrase(clean(transcript), _SELF_INTRODUCTIONS, mixed=True) is not None


def name_after_dob(transcript: str, dob_zone: Optional[str] = None) -> Optional[str]:
    """Phần tên đứng SAU ngày sinh: "14/3/1978, tôi là Nguyễn Văn A".

    Chỉ nhận khi có lời tự giới thiệu rõ ràng. Không có nó thì phần đuôi câu có thể là bất
    cứ thứ gì ("14/3/1978 nhé em"), và đoán sẽ đưa rác vào Verifier.
    """
    text = clean(transcript)
    match = find_phrase(text, _SELF_INTRODUCTIONS, mixed=True)
    if match is None:
        return None
    tail = text[match.start() :].strip()
    if (
        not tail
        or _date_start(tail.split()) is not None
        or (dob_zone is not None and _zone_at(tail.split(), dob_zone) is not None)
    ):
        return None  # còn phần ngày tháng phía sau: đây không phải đuôi tên thuần
    return tail


def _claim_length(words: list[str]) -> int:
    """Số từ còn lại sau khi bỏ tiền tố tự giới thiệu.

    "Tôi là Nguyễn Văn Sinh" chỉ có hai từ tên, nên "Sinh" vẫn có thể là âm cuối của tên.
    """
    return len(_strip_repeated(" ".join(words), _PREFIXES, at_start=True).split())


def _date_start(tokens: list[str]) -> Optional[tuple[int, bool]]:
    """(vị trí từ đầu tiên của phần ngày sinh, có cắt ở "sinh" không); None nếu không có phần ngày sinh.

    Vị trí -1: có phần ngày sinh nhưng không cắt được chắc chắn.
    """
    for i, token in enumerate(tokens):
        following = tokens[i + 1] if i + 1 < len(tokens) else ""
        if any(c.isdigit() for c in token) or token in _DAY_STARTS:
            return i, False
        if token == "sinh" and (following in _DATE_WORDS or any(c.isdigit() for c in following)):
            # "năm sinh 1978": phần ngày bắt đầu từ "năm". Nhưng "Nam sinh năm 1978" (không dấu,
            # tên Nam): sau "sinh" đã là từ ngày tháng nên "nam" thuộc tên.
            if following not in _DATE_WORDS and i > 0 and tokens[i - 1] in _DATE_WORDS:
                return i - 1, True
            return i, True
        if not is_unaccented(token) and is_number_token(token):
            run = i
            while run < len(tokens) and is_number_token(tokens[run]):
                run += 1
            if run < len(tokens) and tokens[run] in _MONTH:
                # Cả dãy phải đọc ra đúng một ngày: với "Nguyễn Văn Tám mười bốn tháng ba", dãy
                # "tám mười bốn" không phải ngày -> không biết "Tám" thuộc tên hay ngày
                day = parse_number(tokens[i:run]) if run - i <= _MAX_SPOKEN_DAY else None
                return (i if day is not None and 1 <= day <= 31 else -1), False
    return None


def _strip_repeated(text: str, phrases: PhraseSet, at_start: bool) -> str:
    """Bỏ lặp lại: "dạ vâng tên tôi là ..." -> bỏ lần lượt "dạ", "vâng", "tên tôi là".

    So theo từng cụm ở chế độ `mixed` để câu mất dấu một phần ("Dạ toi la Nguyen Van A")
    cũng sạch tiền tố, mà chữ "A" cuối tên không dấu vẫn được giữ.
    """
    changed = True
    while changed and text:
        changed = False
        for phrase, _ in phrases.for_text(text, mixed=True):
            if at_start and (text == phrase or text.startswith(phrase + " ")):
                text = text[len(phrase) :].strip()
                changed = True
                break
            if not at_start and (text == phrase or text.endswith(" " + phrase)):
                text = text[: len(text) - len(phrase)].strip()
                changed = True
                break
    return text
