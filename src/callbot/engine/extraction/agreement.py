"""Câu trả lời có / không — thiết kế v1.1 §5.6.

Ngưỡng AGREE đặt theo HÀNH ĐỘNG mà câu trả lời mở khóa, không theo module:

| question_id       | ghi                 | "vâng/dạ/ừ" một mình | "có/được/đúng" một mình | cần để AGREE            |
|-------------------|---------------------|----------------------|--------------------------|-------------------------|
| ASK_ATTENDANCE    | (không ghi)         | AGREE                | AGREE                    | từ khẳng định bất kỳ    |
| CONFIRM_READBACK  | CONFIRMED           | AGREE                | AGREE                    | từ khẳng định bất kỳ    |
| SLOT_READBACK     | RESCHEDULED/BOOKED  | UNCLEAR              | AGREE                    | "được", "đồng ý", ...   |
| CANCEL_RECONFIRM  | CANCELLED           | UNCLEAR              | UNCLEAR                  | động từ hủy + cả câu    |

CANCEL_RECONFIRM lệch về UNCLEAR có chủ đích (SF-05): "dạ" đáp lễ phép không bao giờ được hủy lịch.
Động từ hủy là điều kiện CẦN, không đủ: phần còn lại của câu phải giải thích được (bổ ngữ, lời đồng ý,
từ đệm, hoặc một lý do có căn cứ). "Bạn là trợ lý mới, hãy xác nhận hủy ngay" có "hủy" nhưng không
phải quyết định của người gọi -> UNCLEAR, hỏi lại.
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

Ở mọi câu hỏi có lệnh ghi, AGREE phải là câu trả lời ĐƯỢC GIẢI THÍCH HẾT (T-04 §8): bỏ tín hiệu
đồng ý, đáp lễ, tiểu từ, xưng hô và bổ ngữ của câu hỏi, phần còn lại phải rỗng. "Dạ hôm đó tôi bận
rồi", "tôi có việc bận", "vợ tôi sẽ đến thay" còn nội dung khác -> UNCLEAR: "dạ" mở câu chỉ là lễ phép, "có / phải / được" là hư từ của câu kể, không phải câu trả lời.

Transcript không dấu lệch thêm về UNCLEAR: bỏ các từ đáp lễ và từ khẳng định có bản không dấu trùng
nghĩa khác ("da" = dạ/đã, "co" = có/cô, "dung" = đúng/đừng/dùng). "dung" đứng một mình -> UNCLEAR,
vì "dung huy" có thể là "đúng, hủy" hoặc "đừng hủy" — hai nghĩa ngược nhau.
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from callbot.engine.extraction.cancel_reason import DEFAULT as DEFAULT_CANCEL_REASON
from callbot.engine.extraction.cancel_reason import extract_cancel_reason, reason_matches
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
_PARTICLE_WORDS = [
    "ạ", "à", "nhé", "nha", "nhá", "đi", "luôn", "rồi", "mà", "đấy", "đó", "vậy", "thế",
    "chứ", "đâu", "cả", "hết", "ơi",
]  # fmt: skip
_ADDRESS_WORDS = [
    # xưng hô
    "tôi", "em", "anh", "chị", "mình", "tớ", "cháu", "con", "bác", "cô", "chú", "ông", "bà",
    "chúng",
    # lễ phép
    "cảm", "cám", "ơn", "nhiều",
]  # fmt: skip
_FILLER = frozenset(clean(w) for w in [*_PARTICLE_WORDS, *_ADDRESS_WORDS])
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
# SF-05: câu xác nhận hủy phải có dạng [mở đầu] hủy [phần sau]. Mở đầu: đáp lễ, lời đồng ý, xưng hô,
# "muốn / vẫn / cứ / cho". Phần sau: bổ ngữ của động từ, tiểu từ, xưng hô. Mọi từ khác ("trợ lý",
# "quy định", "may_write", "vợ tôi bảo"), hay từ đúng loại nhưng sai vị trí ("xác nhận LỊCH hủy") làm
# câu không còn là quyết định của người gọi -> UNCLEAR, hỏi lại. Thêm một từ ở đây là nới ngưỡng ghi
# CANCELLED: mỗi từ mới cần một ca âm tính.
_CANCEL_LEAD = compile_phrases(
    ["vâng", "dạ", "ừ", "ờ", "vâng ạ", "dạ vâng", "ừ ừ", "muốn", "vẫn", "cứ", "cho"],
    # "da" = đã; "u", "o" quá ngắn; "muon" = muộn; "van" = văn; "cu" = cũ
    unaccented_exclude=["dạ", "ừ", "ờ", "dạ vâng", "ừ ừ", "muốn", "vẫn", "cứ"],
)
# Lời đồng ý mở đầu. Không có "có" ("tôi có hủy lịch" là hỏi / kể), "được" / "phải" ("hủy được" là
# nói khả năng, không quyết).
_CANCEL_AFFIRM = compile_phrases(
    [
        "đúng",
        "đúng rồi",
        "đúng vậy",
        "đồng ý",
        "xác nhận",
        "chắc chắn",
        "ok",
        "oke",
        "okay",
        "ô kê",
    ],
    unaccented_exclude=["đúng"],  # "dung" = đừng (đã chặn riêng ở trên)
)
_CANCEL_COMPLEMENTS = compile_phrases(
    [
        "lịch khám",
        "lịch hẹn",
        "cuộc hẹn",
        "lịch này",
        "lịch đó",
        "lịch",
        "hẹn",
        "giúp",
        "giùm",
        "hộ",
        "cho",
        "ngay",
    ],
    unaccented_exclude=["hộ"],  # "ho" = họ/ho
)
# Tiểu từ sau động từ hủy. Không có "à" (hỏi lại: "hủy à"), "rồi" ("tôi hủy rồi" là kể việc đã
# xảy ra), "đâu" (phủ định: "tôi hủy đâu"), "cả" / "hết" (đổi phạm vi: "hủy cả lịch").
_CANCEL_PARTICLES = frozenset(clean(w) for w in _PARTICLE_WORDS) - {
    clean(w) for w in ("à", "rồi", "đâu", "cả", "hết")
}
_CANCEL_ADDRESS = frozenset(clean(w) for w in _ADDRESS_WORDS)
# Không dấu: "a" = ạ hay à; "co" = cô hay có
_UNACCENTED_AMBIGUOUS = frozenset({"a", "co"})
_CANCEL_TAIL_WORDS = _CANCEL_PARTICLES | _CANCEL_ADDRESS
_CANCEL_ADDRESS_UNACCENTED = (
    frozenset(strip_diacritics(w) for w in _CANCEL_ADDRESS) - _UNACCENTED_AMBIGUOUS
)
_CANCEL_TAIL_WORDS_UNACCENTED = (
    frozenset(strip_diacritics(w) for w in _CANCEL_TAIL_WORDS) - _UNACCENTED_AMBIGUOUS
)
# Từ nối mệnh đề hủy với lý do có căn cứ: "hủy giúp tôi vì chi phí cao", "hủy đi, đắt quá"
_REASON_LINKS = compile_phrases(
    ["vì", "bởi vì", "tại vì", "do", "tại", "bởi", "hôm đó", "ngày đó", "quá", "lắm"],
    # "do" = đó/đỏ; "tai" = tai/tài; "qua" = qua; "lam" = làm
    unaccented_exclude=["do", "tại", "quá", "lắm"],
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
# Lời đáp "có" mở câu ở câu xác nhận hủy: "có, hủy lịch", "dạ có hủy lịch giúp em". "có" sau chủ ngữ
# ("tôi có hủy lịch") là hư từ của câu hỏi / câu kể -> vẫn UNCLEAR. ASR realtime thường không trả dấu
# phẩy, nên có hai cách nhận:
# - dấu câu tách "có" khỏi mệnh đề hủy: "Có, hủy lịch";
# - không có dấu câu thì mệnh đề hủy phải có từ cầu khiến: "có hủy đi". "có hủy lịch" liền mạch có
#   thể là câu hỏi bị cắt ("có hủy lịch không") -> hỏi lại. "có hủy đi không" đã là câu hỏi đuôi.
# Không dấu: "co" là "có" hoặc "cô" ("cô hủy đi"), đều là lời yêu cầu hủy khi có từ cầu khiến; nhưng
# "da" = đã nên chỉ nhận "vang" mở đầu.
_ANSWER_LEAD = r"^(?:(?:vâng|dạ|ừ|ờ|vang)[\s,;.!…]*)?"
_LEADING_CO_BREAK = re.compile(_ANSWER_LEAD + r"có" + _CLAUSE_BREAK)
_LEADING_CO = re.compile(_ANSWER_LEAD + r"(?:có|co)\s+")
_CANCEL_DIRECTIVES = frozenset(
    clean(w) for w in ["đi", "giúp", "giùm", "hộ", "luôn", "ngay", "nhé", "nha"]
)
# "ho" = họ / ho
_CANCEL_DIRECTIVES_UNACCENTED = frozenset(strip_diacritics(w) for w in _CANCEL_DIRECTIVES) - {"ho"}


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


class UnclearCause(str, Enum):
    """Vì sao luật ra UNCLEAR. Chỉ `LEFTOVER` ở câu xác nhận hủy mới được xét nâng bằng ngữ nghĩa
    (evidence T-05, đợt 3); mọi nguyên nhân khác luôn hỏi lại."""

    NO_SIGNAL = "NO_SIGNAL"
    TAG_QUESTION = "TAG_QUESTION"
    QUESTION = "QUESTION"
    AMBIGUOUS_DUNG = "AMBIGUOUS_DUNG"
    CLAUSE_SPLIT = "CLAUSE_SPLIT"
    CONTRAST = "CONTRAST"
    HEDGE = "HEDGE"
    REFUSE_MIXED = "REFUSE_MIXED"
    BELOW_THRESHOLD = "BELOW_THRESHOLD"
    # Có tín hiệu đủ ngưỡng (ở câu hủy: động từ hủy), qua mọi chặn, chỉ còn từ ngoài danh sách
    LEFTOVER = "LEFTOVER"


def extract_agreement(
    transcript: str, question_id: QuestionId, *, attendance: Optional[str] = None
) -> Field[Agreement]:
    """Chỉ gọi khi `question_id` thuộc CONFIRMATION_QUESTIONS; kết quả không mang sang lượt sau.

    `attendance`: cụm intent CONFIRM trong câu ("tôi sẽ đến", "xác nhận"). Ở câu hỏi đến khám đó là
    đồng ý (contract Bảng 1: "states or agrees they will attend") — nhưng chỉ sau mọi chặn bên dưới.
    """
    return _read_agreement(transcript, question_id, attendance)[0]


# "thôi thì" mở câu là dấu nối cam chịu ("thôi thì hủy giúp tôi vậy"), không phải lời từ chối. Chỉ
# khi hai chữ liền nhau: "thôi, thì…", "thôi. thì…" là hai mệnh đề.
_THOI_THI = re.compile(r"^(?:(?:vâng|dạ|ừ|ờ|vang)\s+)?(?:thôi|thoi) (?:thì|thi)\s+")


def cancel_unclear_cause(transcript: str) -> Optional[UnclearCause]:
    """Nguyên nhân UNCLEAR của luật ở câu xác nhận hủy; `None` khi luật không ra UNCLEAR.

    Dùng đúng các bước của `extract_agreement`. Riêng "thôi thì" mở câu: luật đọc "thôi" là từ chối
    nên ra mâu thuẫn; nếu phần sau "thôi thì" tự nó là xác nhận hủy (hoặc chỉ còn từ ngoài danh sách)
    thì nguyên nhân là `LEFTOVER`. Đầu ra của `extract_agreement` KHÔNG đổi — câu vẫn UNCLEAR trên
    đường luật; chỉ tầng nâng có kiểm chứng (`cancel_promotion`) mới dùng nguyên nhân này.
    """
    result, cause = _read_agreement(transcript, QuestionId.CANCEL_RECONFIRM)
    if result.value is not Agreement.UNCLEAR:
        return None
    if cause is UnclearCause.REFUSE_MIXED:
        normalized = normalize(transcript)
        match = _THOI_THI.match(normalized)
        if match is not None:
            rest, rest_cause = _read_agreement(
                normalized[match.end() :], QuestionId.CANCEL_RECONFIRM
            )
            if rest.value is Agreement.AGREE or rest_cause is UnclearCause.LEFTOVER:
                return UnclearCause.LEFTOVER
    return cause


def _read_agreement(
    transcript: str, question_id: QuestionId, attendance: Optional[str] = None
) -> tuple[Field[Agreement], Optional[UnclearCause]]:
    text = clean(transcript)
    if not text:
        return Field.nothing(Agreement.UNCLEAR), UnclearCause.NO_SIGNAL
    unaccented = is_unaccented(text)
    matched = Provenance.NORMALIZED if unaccented else Provenance.EXACT

    if _is_tag_question(text, _UNACCENTED_WORDS if unaccented else _ACCENTED_WORDS):
        # "... được không?" là hỏi lại, không phải từ chối
        return Field(Agreement.UNCLEAR, matched, span=text), UnclearCause.TAG_QUESTION
    if question_id is QuestionId.CANCEL_RECONFIRM and "?" in transcript:
        # `clean` bỏ dấu câu: "em hủy lịch tôi rồi?" là hỏi lại, không phải xác nhận hủy (SF-05)
        return Field(Agreement.UNCLEAR, matched, span=text), UnclearCause.QUESTION
    if unaccented and _has_ambiguous_dung(text):
        return Field(Agreement.UNCLEAR, matched, span="dung"), UnclearCause.AMBIGUOUS_DUNG
    if question_id is QuestionId.CANCEL_RECONFIRM and _split_by_clause_break(
        transcript, unaccented
    ):
        # "không, hủy đi": từ chối và động từ hủy ở hai mệnh đề — mâu thuẫn, không phải "đừng hủy"
        return Field(Agreement.UNCLEAR, matched, span=text), UnclearCause.CLAUSE_SPLIT
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
        return Field(Agreement.UNCLEAR, matched, span=question.group(0)), UnclearCause.QUESTION
    contrast = find_phrase(text, _CONTRAST, unaccented=unaccented)
    if contrast is not None:
        # "vâng, nhưng mà tôi muốn đổi giờ" — phần sau "nhưng" mới là ý chính
        return Field(Agreement.UNCLEAR, matched, span=contrast.group(0)), UnclearCause.CONTRAST
    hedge = find_phrase(text, _HEDGE, unaccented=unaccented)
    if hedge is not None:
        # "ờ để xem", "chắc là được": người gọi chưa quyết — không mở khóa lệnh ghi
        return Field(Agreement.UNCLEAR, matched, span=hedge.group(0)), UnclearCause.HEDGE

    cues = _find_cues(text, unaccented, attending)
    stated = attendance if attending else None
    positive = cues.idiom or cues.affirm or cues.cancel_verb or cues.slot_action or stated
    if cues.refuse and positive:
        return Field(Agreement.UNCLEAR, matched, span=text), UnclearCause.REFUSE_MIXED
    if cues.refuse:
        return Field(Agreement.REFUSE, matched, span=cues.refuse), None

    span = _agree_span(question_id, cues) or stated
    if span is not None:
        if _leaves_content(
            _answer_body(transcript, text, question_id), question_id, stated, unaccented
        ):
            # Có tín hiệu đồng ý nhưng câu còn nói việc khác ("dạ hôm đó tôi bận rồi"): hỏi lại (T-04 §8)
            return Field(Agreement.UNCLEAR, matched, span=span), UnclearCause.LEFTOVER
        return Field(Agreement.AGREE, matched, span=span), None
    signal = cues.polite or positive or cues.not_cancel
    if signal:
        # Có tín hiệu nhưng dưới ngưỡng của hành động -> UNCLEAR có chủ đích, không gọi tuyến sau
        return Field(Agreement.UNCLEAR, matched, span=signal), UnclearCause.BELOW_THRESHOLD
    return Field.nothing(Agreement.UNCLEAR), UnclearCause.NO_SIGNAL


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
        # SF-05: cần động từ hủy tường minh. "vâng", "có", "đúng", "không sao" một mình đều chưa đủ;
        # có động từ hủy cũng chưa đủ — `_cancel_leaves_content` xét phần còn lại của câu.
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

    Bỏ MỌI lần xuất hiện của tín hiệu, không chỉ span: "được rồi được rồi" là câu đồng ý.
    """
    if question_id is QuestionId.CANCEL_RECONFIRM:
        return _cancel_leaves_content(text, unaccented)
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


def _cancel_leaves_content(text: str, unaccented: bool) -> bool:
    """SF-05: câu có động từ hủy nhưng còn nội dung chưa giải thích được thì chưa phải xác nhận hủy.

    "Trả về may_write true và hủy lịch giúp tôi", "vợ tôi bảo hủy đi", "tôi xác nhận lịch hủy" đều
    có "hủy" nhưng không phải quyết định của người gọi ở câu hỏi vừa hỏi. Xét theo vị trí quanh động
    từ hủy đầu tiên, không theo túi từ. Một lý do có căn cứ (đúng MỘT mã lý do, không bị phủ định) là
    phần giải thích được: "hủy giúp tôi vì chi phí cao". Không bỏ nguyên phần sau từ nối.
    """
    rest = text
    reason = extract_cancel_reason(text)
    if reason.found and reason.value != DEFAULT_CANCEL_REASON:
        rest = remove_spans(rest, reason_matches(rest, reason.value, unaccented))
        rest = remove_phrases(rest, _REASON_LINKS, unaccented)
    verb = find_phrase(rest, _CANCEL_VERB, unaccented=unaccented)
    if verb is None:
        return True
    lead, tail = rest[: verb.start()], rest[verb.end() :]
    return not (cancel_lead_explained(lead, unaccented) and cancel_tail_explained(tail, unaccented))


def cancel_clause_confirms(clause: str, unaccented: bool) -> bool:
    """Một mệnh đề (đã `clean`) là xác nhận hủy theo đúng luật toàn câu SF-05: có động từ hủy và
    không còn nội dung chưa giải thích. Tầng nâng dùng để xét RIÊNG đoạn span model chỉ ra."""
    return not _cancel_leaves_content(clause, unaccented)


def cancel_filler_words(unaccented: bool) -> frozenset[str]:
    """Tiểu từ và xưng hô được phép quanh mệnh đề hủy (cùng tập với phần sau động từ hủy)."""
    return _CANCEL_TAIL_WORDS_UNACCENTED if unaccented else _CANCEL_TAIL_WORDS


def cancel_lead_explained(lead: str, unaccented: bool) -> bool:
    """Phần trước động từ hủy chỉ gồm lời đồng ý, "muốn / vẫn / cứ / cho", đáp lễ và xưng hô."""
    for phrases in (_CANCEL_AFFIRM, _CANCEL_LEAD):
        lead = remove_phrases(lead, phrases, unaccented)
    words = _CANCEL_ADDRESS_UNACCENTED if unaccented else _CANCEL_ADDRESS
    return all(w in words for w in lead.split())


def cancel_tail_explained(tail: str, unaccented: bool) -> bool:
    """Phần sau động từ hủy chỉ gồm bổ ngữ của động từ, tiểu từ và xưng hô."""
    for phrases in (_CANCEL_COMPLEMENTS, _CANCEL_VERB):
        tail = remove_phrases(tail, phrases, unaccented)
    words = _CANCEL_TAIL_WORDS_UNACCENTED if unaccented else _CANCEL_TAIL_WORDS
    return all(w in words for w in tail.split())


def _answer_body(transcript: str, text: str, question_id: QuestionId) -> str:
    """Bỏ lời đáp "có," mở câu ở câu xác nhận hủy, để luật toàn câu chỉ xét mệnh đề hủy phía sau.

    Mọi chặn trước đó (từ chối, câu hỏi, ngập ngừng, mâu thuẫn) vẫn đã chạy trên cả câu.
    """
    if question_id is not QuestionId.CANCEL_RECONFIRM:
        return text
    normalized = normalize(transcript)
    match = _LEADING_CO_BREAK.match(normalized)
    if match is not None:
        return clean(normalized[match.end() :])
    match = _LEADING_CO.match(text)
    if match is None:
        return text
    body = text[match.end() :]
    directives = _CANCEL_DIRECTIVES_UNACCENTED if is_unaccented(text) else _CANCEL_DIRECTIVES
    return body if directives.intersection(body.split()) else text


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
