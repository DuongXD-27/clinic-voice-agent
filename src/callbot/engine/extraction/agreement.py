"""Câu trả lời có / không — thiết kế v1.1 §5.6.

Ngưỡng AGREE đặt theo HÀNH ĐỘNG mà câu trả lời mở khóa, không theo module:

| question_id       | ghi                 | "vâng/dạ/ừ" một mình | "có/được/đúng" một mình | cần để AGREE            |
|-------------------|---------------------|----------------------|--------------------------|-------------------------|
| ASK_ATTENDANCE    | (không ghi)         | AGREE                | AGREE                    | từ khẳng định bất kỳ    |
| CONFIRM_READBACK  | CONFIRMED           | AGREE                | AGREE                    | từ khẳng định bất kỳ    |
| SLOT_READBACK     | RESCHEDULED/BOOKED  | UNCLEAR              | AGREE                    | "được", "đồng ý", ...   |
| CANCEL_RECONFIRM  | CANCELLED           | UNCLEAR              | UNCLEAR                  | động từ hủy tường minh  |

CANCEL_RECONFIRM lệch về UNCLEAR có chủ đích (SF-05): "dạ" đáp lễ phép không bao giờ được hủy lịch.
Tín hiệu mâu thuẫn ("thôi hủy đi", "không, hủy đi") -> UNCLEAR, Dialogue hỏi lại bằng câu A/B.
Ngập ngừng ("để xem", "chắc là được", "có lẽ") -> UNCLEAR ở mọi câu hỏi xác nhận, kể cả khi có "vâng" (T-04).

Từ đáp lễ ("vâng", "dạ", "ạ") chỉ là tín hiệu khi đứng riêng hoặc mở đầu câu: "kẹt tiền quá em ạ" là kể
lý do, không phải trả lời có / không.

`clean` bỏ dấu câu nên "không, hủy đi" và "không hủy đi" thành cùng một chuỗi, dù nghĩa ngược nhau.
`_split_by_clause_break` đọc bản CÒN dấu câu để tách hai trường hợp: cụm từ chối hủy bị dấu câu cắt
đôi là hai mệnh đề ngược nhau, không phải lời từ chối. Dấu câu của ASR chỉ là một tín hiệu — câu
mâu thuẫn không có dấu câu do tầng ngữ nghĩa xử lý (`extraction/semantic.py`), không phải luật này.

"Giữ lịch" nghĩa ngược nhau theo câu hỏi: ở CANCEL_RECONFIRM / SLOT_READBACK là từ chối hủy / đổi;
ở câu hỏi đến khám (CONFIRM_READBACK, ASK_ATTENDANCE) là khẳng định. "Không hủy" ở câu hỏi đến khám
chỉ là không muốn hủy — không phải từ chối đến khám (T-04).

Ở câu hỏi có lệnh ghi (trừ CANCEL_RECONFIRM, đã có ngưỡng SF-05), AGREE phải là câu trả lời ĐƯỢC GIẢI
THÍCH HẾT (T-04 §8): bỏ tín hiệu đồng ý, đáp lễ, tiểu từ, xưng hô và bổ ngữ của câu hỏi, phần còn lại phải
rỗng. "Dạ hôm đó tôi bận rồi", "tôi có việc bận", "vợ tôi sẽ đến thay" còn nội dung khác -> UNCLEAR:
"dạ" mở câu chỉ là lễ phép, "có / phải / được" là hư từ của câu kể, không phải câu trả lời.

Transcript không dấu lệch thêm về UNCLEAR: bỏ các từ đáp lễ và từ khẳng định có bản không dấu trùng
nghĩa khác ("da" = dạ/đã, "co" = có/cô, "dung" = đúng/đừng/dùng). "dung" đứng một mình -> UNCLEAR,
vì "dung huy" có thể là "đúng, hủy" hoặc "đừng hủy" — hai nghĩa ngược nhau.
"""

import re
from dataclasses import dataclass
from typing import Optional

from callbot.engine.extraction.schema import Agreement, Field, Provenance, QuestionId
from callbot.engine.extraction.text import (
    PhraseSet,
    clean,
    compile_phrases,
    find_phrase,
    is_unaccented,
    normalize,
    phrase_pattern,
    remove_phrases,
    remove_spans,
    strip_diacritics,
)

_AGREE_IDIOMS = compile_phrases(
    [
        "không sao",
        "không vấn đề gì",
        "không có gì",
        "không sao đâu",
        "không vấn đề",
        "không thành vấn đề",
        "không có vấn đề gì",
    ]
)
_REFUSE_COMMON = [
    "không",
    "thôi",
    "để sau",
    "chưa",
    "không đồng ý",
    "sai",
    "sai rồi",
    "không phải",
    "không được",
    "không đúng",
    "đừng",
    "khoan",
    "từ từ",
    "để tôi nghĩ",
    "suy nghĩ lại",
    "không muốn",
    "nhầm",
    "chưa được",
    "để khi khác",
    "thôi khỏi",
]
# Từ chối hủy / đổi: REFUSE ở câu hỏi hủy / chọn slot; ở câu hỏi đến khám xem _KEEP và _NOT_CANCEL
_KEEP_WORDS = ["giữ lịch", "giữ nguyên", "giữ nguyên lịch", "vẫn giữ lịch"]
_NOT_CANCEL_WORDS = ["không hủy", "không hủy nữa", "đừng hủy"]
_REFUSE_UNACCENTED_EXCLUDE = ["đừng", "không đúng"]  # "dung" mơ hồ -> luật riêng bên dưới
_REFUSE = compile_phrases(
    [*_REFUSE_COMMON, *_KEEP_WORDS, *_NOT_CANCEL_WORDS],
    unaccented_exclude=[*_REFUSE_UNACCENTED_EXCLUDE, "đừng hủy"],
)
_ATTENDANCE_REFUSE = compile_phrases(_REFUSE_COMMON, unaccented_exclude=_REFUSE_UNACCENTED_EXCLUDE)
_KEEP = compile_phrases(_KEEP_WORDS)
# Ở câu hỏi đến khám, "không hủy / không cần đổi" chỉ là không muốn thay lịch: không phải từ chối đến
# khám, chưa phải đồng ý (T-04, §8). Ở câu hỏi hủy / chọn slot, các cụm đổi lịch không nằm trong
# `_REFUSE` riêng vì "không" đã đủ là từ chối ở đó.
_NOT_CHANGE_WORDS = [
    "không cần hủy",
    "không đổi",
    "không đổi nữa",
    "không đổi gì",
    "không cần đổi",
    "không đổi lịch",
    "không cần đổi lịch",
    "khỏi đổi",
]
_NOT_CANCEL = compile_phrases(
    [*_NOT_CANCEL_WORDS, *_NOT_CHANGE_WORDS], unaccented_exclude=["đừng hủy"]
)
# Mệnh đề phụ không phủ định việc đến khám. Chỉ bỏ cả cụm có nghĩa rõ ràng,
# không bỏ riêng "không" / "biết" rồi vô tình đồng ý một câu còn điều kiện.
_ATTENDANCE_ASIDES = compile_phrases(["biết địa chỉ rồi", "không trễ đâu", "không muộn đâu"])
# Ngập ngừng: người gọi chưa quyết, dù câu có "vâng" / "được" (T-04). Không có "chắc" đứng một mình:
# "chắc chắn" là khẳng định; "chắc được", "chắc đến" là đoán (T-04 §8).
_HEDGE = compile_phrases(
    [
        "để xem",
        "để tôi xem",
        "để em xem",
        "xem đã",
        "xem lại",
        "chắc là",
        "chắc vậy",
        "chắc được",
        "chắc đến",
        "chắc đi",
        "có lẽ",
        "không chắc",
        "chưa chắc",
        "chưa biết",
        "không biết",
        "tính sau",
        "để tôi hỏi",
        "hy vọng",
        "hi vọng",
        "mong là",
        "cố gắng",
        "nếu",
    ]
)
_POLITE = compile_phrases(
    ["vâng", "dạ", "ừ", "ờ", "ừm", "ạ", "à", "vâng ạ", "dạ vâng", "ừ ừ"],
    unaccented_exclude=["dạ", "ừ", "ờ", "ừm", "ạ", "à", "ừ ừ"],  # "da" = đã; "a", "u", "o" quá ngắn
)
# Đáp lễ đủ để đồng ý ở câu hỏi đến khám (T-04 Q-2). "à" (hỏi lại), "ạ", "ừm" (đang nghĩ) đứng riêng
# chỉ là tín hiệu chưa rõ (T-04 §8).
_POLITE_AGREE = frozenset(
    clean(p) for p in ["vâng", "dạ", "ừ", "ờ", "vâng ạ", "dạ vâng", "ừ ừ"]
) | frozenset(strip_diacritics(clean(p)) for p in ["vâng", "vâng ạ", "dạ vâng"])
_AFFIRM = compile_phrases(
    [
        "có",
        "được",
        "đúng",
        "đúng rồi",
        "đúng vậy",
        "chính xác",
        "đồng ý",
        "xác nhận",
        "ok",
        "oke",
        "okay",
        "ô kê",
        "chuẩn",
        "phải",
        "chắc chắn",
        "chắc chắn rồi",
        "tất nhiên",
        "tất nhiên rồi",
        "được rồi",
        "nhất định",
        "nhất định rồi",
        "đương nhiên",
        "đương nhiên rồi",
    ],
    unaccented_exclude=["có", "đúng"],  # "co" = cô/cỏ/cơ; "dung" = đừng/dùng
)
# Chỉ ở câu hỏi đến khám: "đến chứ" là khẳng định sẽ đến, không có từ đồng ý nào khác trong câu
_ATTEND_AFFIRM = compile_phrases(["đến chứ", "đi chứ"])
_SLOT_ACTION = compile_phrases(
    ["đổi đi", "đặt đi", "chốt", "chốt đi", "lấy khung đó", "lấy giờ đó", "lấy luôn"],
    unaccented_exclude=["đổi đi"],  # "doi di" = đợi đi
)
_CANCEL_VERB = compile_phrases(["hủy"])
_CONTRAST = compile_phrases(
    ["nhưng", "nhưng mà", "có điều", "tuy nhiên", "mà khoan"], unaccented_exclude=["nhưng"]
)
_QUESTION_WORDS = compile_phrases(
    ["gì", "bao giờ", "mấy giờ", "thế nào", "sao", "bao nhiêu", "ở đâu", "ai"]
)

# Phần được phép còn lại trong câu AGREE ở câu hỏi có lệnh ghi (T-04 §8). Bổ ngữ xét theo cụm trước,
# rồi từ đệm theo từng từ. Thiếu một từ ở đây chỉ làm câu đồng ý bị đọc lại (an toàn); thêm nhầm một
# từ nội dung thì mở khóa lệnh ghi — mỗi từ mới cần một ca âm tính trong eval/confirm.
_FILLER_WORDS = [
    # tiểu từ
    "ạ", "à", "nhé", "nha", "nhá", "đi", "luôn", "rồi", "mà", "đấy", "đó", "vậy", "thế",
    "chứ", "đâu", "cả", "hết", "ơi",
    # xưng hô
    "tôi", "em", "anh", "chị", "mình", "tớ", "cháu", "con", "bác", "cô", "chú", "ông", "bà",
    "chúng",
    # lễ phép
    "cảm", "cám", "ơn", "nhiều",
]  # fmt: skip
_FILLER = frozenset(clean(w) for w in _FILLER_WORDS)
_FILLER_UNACCENTED = frozenset(strip_diacritics(w) for w in _FILLER)
_ATTEND_COMPLEMENTS = compile_phrases(
    [
        "đi khám",
        "đến khám",
        "khám",
        "đúng giờ",
        "đúng hẹn",
        "theo lịch",
        "lịch này",
        "lịch đó",
        "lịch",
        "hôm đó",
        "có mặt",
        "như vậy",
        "như thế",
        "vẫn",
        "sẽ",
        "cứ",
        "đến",
    ],
    unaccented_exclude=["đúng giờ", "đúng hẹn"],  # "dung" = đừng
)
_SLOT_COMPLEMENTS = compile_phrases(
    ["khung đó", "khung này", "giờ đó", "khung", "đổi", "đặt", "giúp", "cho", "này", "lịch"],
    unaccented_exclude=["đổi"],  # "doi" = đợi
)

# Không có "chứ": "được chứ" là khẳng định, không phải hỏi lại
_TAG_FINALS = frozenset({"không", "chưa", "à", "hả", "nhỉ"})
_TRAILING_PARTICLES = frozenset({"ạ", "vậy", "thế", "nhé", "em", "chị", "anh"})
_POLITE_WORDS = frozenset({"vâng", "dạ", "ừ", "ờ", "ừm", "ạ", "à"})
_REFUSE_WORDS = frozenset({"không", "thôi", "chưa", "đừng", "khoan", "sai"})
# "dung roi", "dung vay" chỉ có thể là "đúng rồi", "đúng vậy"
_UNAMBIGUOUS_DUNG_FOLLOWERS = frozenset({"roi", "vay"})


@dataclass(frozen=True)
class _WordSets:
    tag_finals: frozenset[str]
    trailing: frozenset[str]
    polite: frozenset[str]
    refuse: frozenset[str]

    def unaccented(self) -> "_WordSets":
        stripped = _WordSets(
            *(frozenset(strip_diacritics(w) for w in words) for words in vars(self).values())
        )
        # "a" cuối câu là "ạ" (lễ phép) hoặc "à" (hỏi lại): "huy a" = "hủy ạ" hay "hủy à?" -> coi là câu hỏi
        return _WordSets(
            stripped.tag_finals, stripped.trailing - {"a"}, stripped.polite, stripped.refuse
        )


_ACCENTED_WORDS = _WordSets(_TAG_FINALS, _TRAILING_PARTICLES, _POLITE_WORDS, _REFUSE_WORDS)
_UNACCENTED_WORDS = _ACCENTED_WORDS.unaccented()


_ATTENDANCE_QUESTIONS = frozenset({QuestionId.CONFIRM_READBACK, QuestionId.ASK_ATTENDANCE})

# Cụm từ chối hủy bị dấu câu cắt đôi: "không, hủy đi". Dựng từ chính `_NOT_CANCEL_WORDS` để danh
# sách chỉ có một nguồn; bản không dấu bỏ "đừng hủy" đúng như `_NOT_CANCEL` (xem `unaccented_exclude`).
_CLAUSE_BREAK = r"\s*[,;.!?…]+\s*"


def _split_pattern(phrase: str) -> re.Pattern[str]:
    words = phrase.split()
    return re.compile(r"(?<!\w)" + _CLAUSE_BREAK.join(re.escape(w) for w in words) + r"(?!\w)")


_SPLIT_ACCENTED = tuple(
    _split_pattern(clean(p)) for p in _NOT_CANCEL_WORDS if len(clean(p).split()) > 1
)
_SPLIT_UNACCENTED = tuple(
    _split_pattern(strip_diacritics(clean(p)))
    for p in _NOT_CANCEL_WORDS
    if len(clean(p).split()) > 1 and p != "đừng hủy"
)


@dataclass(frozen=True)
class _Cues:
    refuse: Optional[str]
    idiom: Optional[str]
    affirm: Optional[str]
    polite: Optional[str]
    cancel_verb: Optional[str]
    slot_action: Optional[str]
    not_cancel: Optional[str] = (
        None  # "không hủy" ở câu hỏi đến khám: không phải từ chối, chưa phải đồng ý
    )


def extract_agreement(
    transcript: str, question_id: QuestionId, *, attendance: Optional[str] = None
) -> Field[Agreement]:
    """Chỉ gọi khi `question_id` thuộc CONFIRMATION_QUESTIONS; kết quả không mang sang lượt sau.

    `attendance`: cụm intent CONFIRM trong câu ("tôi sẽ đến", "xác nhận"). Ở câu hỏi đến khám đó là
    đồng ý (contract Bảng 1: "states or agrees they will attend") — nhưng chỉ sau mọi chặn bên dưới.
    """
    text = clean(transcript)
    if not text:
        return Field.nothing(Agreement.UNCLEAR)
    unaccented = is_unaccented(text)
    matched = Provenance.NORMALIZED if unaccented else Provenance.EXACT

    if _is_tag_question(text, _UNACCENTED_WORDS if unaccented else _ACCENTED_WORDS):
        # "... được không?" là hỏi lại, không phải từ chối
        return Field(Agreement.UNCLEAR, matched, span=text)
    if unaccented and _has_ambiguous_dung(text):
        return Field(Agreement.UNCLEAR, matched, span="dung")
    if question_id is QuestionId.CANCEL_RECONFIRM and _split_by_clause_break(
        transcript, unaccented
    ):
        # "không, hủy đi": từ chối và động từ hủy ở hai mệnh đề — mâu thuẫn, không phải "đừng hủy"
        return Field(Agreement.UNCLEAR, matched, span=text)
    attending = question_id in _ATTENDANCE_QUESTIONS
    idiom = find_phrase(text, _AGREE_IDIOMS, unaccented=unaccented)
    # "không đổi gì cả" ở câu hỏi đến khám: "gì" thuộc cụm trung tính, không phải câu hỏi
    neutral = find_phrase(text, _NOT_CANCEL, unaccented=unaccented) if attending else None
    question = find_phrase(
        remove_spans(text, [m for m in (idiom, neutral) if m]),
        _QUESTION_WORDS,
        unaccented=unaccented,
    )
    if question is not None:
        return Field(Agreement.UNCLEAR, matched, span=question.group(0))
    contrast = find_phrase(text, _CONTRAST, unaccented=unaccented)
    if contrast is not None:
        # "vâng, nhưng mà tôi muốn đổi giờ" — phần sau "nhưng" mới là ý chính
        return Field(Agreement.UNCLEAR, matched, span=contrast.group(0))
    hedge = find_phrase(text, _HEDGE, unaccented=unaccented)
    if hedge is not None:
        # "ờ để xem", "chắc là được": người gọi chưa quyết — không mở khóa lệnh ghi
        return Field(Agreement.UNCLEAR, matched, span=hedge.group(0))

    cues = _find_cues(text, unaccented, attending)
    stated = attendance if attending else None
    positive = cues.idiom or cues.affirm or cues.cancel_verb or cues.slot_action or stated
    if cues.refuse and positive:
        return Field(Agreement.UNCLEAR, matched, span=text)
    if cues.refuse:
        return Field(Agreement.REFUSE, matched, span=cues.refuse)

    span = _agree_span(question_id, cues) or stated
    if span is not None:
        if _leaves_content(text, question_id, stated, unaccented):
            # Có tín hiệu đồng ý nhưng câu còn nói việc khác ("dạ hôm đó tôi bận rồi"): hỏi lại (T-04 §8)
            return Field(Agreement.UNCLEAR, matched, span=span)
        return Field(Agreement.AGREE, matched, span=span)
    signal = cues.polite or positive or cues.not_cancel
    if signal:
        # Có tín hiệu nhưng dưới ngưỡng của hành động -> UNCLEAR có chủ đích, không gọi tuyến sau
        return Field(Agreement.UNCLEAR, matched, span=signal)
    return Field.nothing(Agreement.UNCLEAR)


def _find_cues(text: str, unaccented: bool, attending: bool = False) -> _Cues:
    idiom = find_phrase(text, _AGREE_IDIOMS, unaccented=unaccented)
    rest = remove_spans(text, [idiom] if idiom else [])
    not_cancel = None
    if attending:
        # Bỏ "không hủy" trước khi tìm từ chối, để "không" trong đó không thành REFUSE
        not_cancel = find_phrase(rest, _NOT_CANCEL, unaccented=unaccented)
        rest = remove_spans(rest, [not_cancel] if not_cancel else [])
        rest = remove_phrases(rest, _ATTENDANCE_ASIDES, unaccented)
    refuse = find_phrase(rest, _ATTENDANCE_REFUSE if attending else _REFUSE, unaccented=unaccented)
    rest_positive = remove_spans(rest, [refuse] if refuse else [])

    def positive(phrases: PhraseSet, allow_negated: bool = False) -> Optional[str]:
        return _group(
            find_phrase(rest_positive, phrases, allow_negated=allow_negated, unaccented=unaccented)
        )

    return _Cues(
        refuse=_group(refuse),
        idiom=_group(idiom),
        affirm=positive(_AFFIRM)
        or (positive(_KEEP) or positive(_ATTEND_AFFIRM) if attending else None),
        # Xét trên câu gốc, trước khi bỏ span khác: "ạ" cuối câu kể lý do là lễ phép, không phải đáp lời
        polite=_group(_leading_phrase(text, _POLITE, unaccented)),
        cancel_verb=positive(_CANCEL_VERB),
        slot_action=positive(_SLOT_ACTION),
        not_cancel=_group(not_cancel),
    )


def _leading_phrase(text: str, phrases: PhraseSet, unaccented: bool) -> Optional[re.Match[str]]:
    """Cụm đáp lễ chỉ là câu trả lời khi đứng riêng hoặc mở đầu câu ("vâng", "dạ, hủy đi").

    Ở giữa / cuối câu ("dạo này kẹt tiền quá em ạ") nó chỉ là tiểu từ lễ phép của một câu khác.
    """
    for _, pattern in phrases.for_text(text, unaccented):
        match = pattern.match(text)
        if match is not None:
            return match
    return None


def _agree_span(question_id: QuestionId, cues: _Cues) -> Optional[str]:
    """Tín hiệu đủ ngưỡng AGREE cho hành động của câu hỏi, hoặc None."""
    if question_id is QuestionId.CANCEL_RECONFIRM:
        # SF-05: chỉ động từ hủy tường minh. "vâng", "có", "đúng", "không sao" một mình đều chưa đủ.
        return cues.cancel_verb
    if question_id is QuestionId.SLOT_READBACK:
        return cues.affirm or cues.slot_action or cues.idiom
    if question_id in (QuestionId.CONFIRM_READBACK, QuestionId.ASK_ATTENDANCE):
        polite = cues.polite if cues.polite in _POLITE_AGREE else None
        return cues.affirm or cues.idiom or polite
    return None


# Ở câu hỏi "đổi hay hủy", "thôi" mở câu là chuyển ý ("thôi tôi vẫn đến"), không phải từ chối
_INTENT_ANSWER_FILLER = compile_phrases(["thôi", "gì cả", "gì hết"])


def attendance_leaves_content(transcript: str, span: Optional[str]) -> bool:
    """Cụm intent CONFIRM (`span`) không giải thích hết câu trả lời "đổi hay hủy" (T-04 §8).

    "hôm đó tôi sẽ đi công tác" có cụm "sẽ đi" nhưng nói việc khác: router cho tầng ngữ nghĩa xét,
    thay vì đọc lại lịch theo luật. Cùng bảng từ đệm với câu hỏi đến khám.
    """
    text = clean(transcript)
    unaccented = is_unaccented(text)
    text = remove_phrases(text, _INTENT_ANSWER_FILLER, unaccented)
    return _leaves_content(text, QuestionId.CONFIRM_READBACK, span, unaccented)


def mentions_keeping(transcript: str) -> bool:
    """Câu có cụm "không hủy / không (cần) đổi": từ chối THAY lịch, không phải từ chối đến khám."""
    return find_phrase(clean(transcript), _NOT_CANCEL) is not None


def _leaves_content(
    text: str, question_id: QuestionId, stated: Optional[str], unaccented: bool
) -> bool:
    """Câu còn từ nội dung ngoài tín hiệu đồng ý, đáp lễ, tiểu từ, xưng hô và bổ ngữ (T-04 §8).

    Chỉ áp dụng ở câu hỏi có ngưỡng "từ khẳng định bất kỳ"; CANCEL_RECONFIRM đã đòi động từ hủy.
    Bỏ MỌI lần xuất hiện của tín hiệu, không chỉ span: "được rồi được rồi" là câu đồng ý.
    """
    # Bổ ngữ bỏ TRƯỚC tín hiệu: bỏ "đúng" trước thì "đúng giờ" còn trơ lại "giờ"
    if question_id is QuestionId.SLOT_READBACK:
        sets = (_SLOT_COMPLEMENTS, _AGREE_IDIOMS, _AFFIRM, _SLOT_ACTION, _POLITE)
    elif question_id in _ATTENDANCE_QUESTIONS:
        sets = (
            _ATTENDANCE_ASIDES,
            _AGREE_IDIOMS,
            _NOT_CANCEL,
            _KEEP,
            _ATTEND_AFFIRM,
            _ATTEND_COMPLEMENTS,
        )
        sets = (*sets, _AFFIRM, _POLITE)
    else:
        return False
    rest = phrase_pattern(stated).sub(" ", text) if stated else text
    for phrases in sets:
        rest = remove_phrases(rest, phrases, unaccented)
    filler = _FILLER_UNACCENTED if unaccented else _FILLER
    return any(word not in filler for word in rest.split())


def _is_tag_question(text: str, words_of: _WordSets) -> bool:
    words = text.split()
    while len(words) > 1 and words[-1] in words_of.trailing:
        words.pop()
    if len(words) < 2 or words[-1] not in words_of.tag_finals:
        return False
    # "dạ không", "thôi không" là từ chối; "được không", "hủy luôn không" là hỏi lại
    head = [w for w in words[:-1] if w not in words_of.polite]
    return bool(head) and not all(w in words_of.refuse for w in head)


def _split_by_clause_break(transcript: str, unaccented: bool) -> bool:
    """Cụm "không hủy" chỉ thành hình sau khi `clean` bỏ dấu câu, nên đọc lại bản CÒN dấu câu.

    "không, hủy đi" là từ chối rồi đổi ý (hoặc ASR chấm câu sai) — hai tín hiệu ngược nhau, phải
    hỏi lại. "không hủy đi" liền mạch mới là lời giữ lịch.
    """
    text = normalize(transcript)
    patterns = _SPLIT_UNACCENTED if unaccented else _SPLIT_ACCENTED
    return any(pattern.search(text) for pattern in patterns)


def _has_ambiguous_dung(text: str) -> bool:
    words = text.split()
    return any(
        word == "dung" and (i + 1 == len(words) or words[i + 1] not in _UNAMBIGUOUS_DUNG_FOLLOWERS)
        for i, word in enumerate(words)
    )


def _group(match) -> Optional[str]:
    return match.group(0) if match else None
