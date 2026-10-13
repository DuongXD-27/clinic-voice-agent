"""Câu hỏi lâm sàng — thiết kế v1.1 §5.5. Chạy TRƯỚC intent.

§1.2.1 cấm bot chẩn đoán / giải thích triệu chứng / tư vấn thuốc / ra quyết định lâm sàng —
không cấm người gọi *nhắc tới* triệu chứng. Ba lớp có hướng hiệu chỉnh NGƯỢC nhau:

- EMERGENCY       -> RECALL. Bỏ sót là SF-04. Không xét phủ định, không xét ngữ cảnh đặt lịch:
                     "không khó thở" vẫn là EMERGENCY — chuyển máy nhầm rẻ hơn bỏ sót.
- ADVICE_REQUEST  -> RECALL, nhưng BẮT BUỘC có hành vi hỏi (từ nghi vấn, yêu cầu đánh giá).
- MENTION         -> PRECISION. Nhắc triệu chứng khi đặt lịch mà bị chuyển máy là case fail.
                     Vì vậy câu có từ triệu chứng + câu hỏi đuôi về lịch ("... đặt lịch được không")
                     KHÔNG được nâng lên ADVICE_REQUEST.

Đừng "làm cho nhất quán" giữa ba lớp này.

IE chỉ gắn nhãn; chuyển máy hay không là quyết định của Policy. Hợp đồng §1.2.1 ("MUST transfer
instead, every time") chưa nói rõ việc chỉ nhắc triệu chứng có phải chuyển máy không — đã hỏi
#residency-batch03 (thiết kế §10). Nếu câu trả lời là "có", chỉ cần Policy chuyển máy cả MENTION;
IE không đổi.

Transcript không dấu: chỉ dùng cụm tường minh. Luật "từ triệu chứng + câu hỏi -> ADVICE_REQUEST"
bị tắt, vì bỏ dấu làm "đau" trùng "đâu"/"đầu", "ho" trùng "họ" — nâng nhầm lên ADVICE là chuyển máy nhầm.
"""

from callbot.engine.extraction.schema import ClinicalLevel, Field, Provenance
from callbot.engine.extraction.text import (
    clean,
    compile_phrases,
    find_phrase,
    is_unaccented,
    remove_phrases,
    strip_diacritics,
)

_EMERGENCY = compile_phrases(
    [
        "đau ngực",
        "tức ngực",
        "đau thắt ngực",
        "khó thở",
        "không thở được",
        "thở không được",
        "ngạt thở",
        "co giật",
        "lên cơn co giật",
        "ngất",
        "ngất xỉu",
        "bất tỉnh",
        "hôn mê",
        "lịm đi",
        "chảy máu nhiều",
        "chảy máu không cầm",
        "mất máu",
        "nôn ra máu",
        "ho ra máu",
        "đi ngoài ra máu",
        "đột quỵ",
        "méo miệng",
        "yếu nửa người",
        "liệt nửa người",
        "sốc phản vệ",
        "ngộ độc",
        "uống nhầm thuốc",
        "quá liều",
        "tự tử",
        "tai nạn",
        "đau đầu dữ dội",
        "sốt cao co giật",
        "vỡ ối",
        "ra máu",
    ],
    # "tu tu" = từ từ, "ra mau" = ra mau (nhanh lên), "vo oi" = vợ ơi
    unaccented_exclude=["tự tử", "ra máu", "vỡ ối"],
)

# Hỏi đánh giá / tư vấn tường minh — không cần từ triệu chứng đi kèm
_ADVICE_PHRASES = compile_phrases(
    [
        # đánh giá mức độ
        "có sao không",
        "có nguy hiểm không",
        "có nặng không",
        "có bị làm sao không",
        "có bình thường không",
        "có ảnh hưởng gì không",
        "có lây không",
        "có phải bị",
        "bị bệnh gì",
        "bị làm sao",
        "là bệnh gì",
        "là bị gì",
        "bị gì vậy",
        "tại sao bị",
        "vì sao bị",
        "tại sao lại bị",
        "nguyên nhân do đâu",
        # thuốc
        "uống thuốc gì",
        "dùng thuốc gì",
        "thuốc gì",
        "uống gì cho",
        "uống bao nhiêu",
        "liều",
        "có nên uống",
        "uống được không",
        "ngừng thuốc",
        "bỏ thuốc được không",
        "kiêng gì",
        "nên ăn gì",
        # phân khoa / mức khẩn
        "khám khoa nào",
        "khoa nào thì phù hợp",
        "nên khám gì",
        "khám bác sĩ nào thì",
        "có cần đi khám",
        "có cần khám",
        "có cần khám gấp",
        "có cần đi viện",
        "có cần cấp cứu",
        "có gấp không",
        "có cần xét nghiệm",
        # xin cách xử lý
        "nên làm gì",
        "phải làm sao",
        "làm sao cho đỡ",
        "làm thế nào cho đỡ",
        "làm sao cho hết",
        "làm gì cho đỡ",
        "xử lý thế nào",
    ],
    # "lieu" = liệu, "co lay khong" = có lấy không, "co gap khong" = có gặp không
    unaccented_exclude=["liều", "có lây không", "có gấp không"],
)

# Xin tư vấn / hỏi bác sĩ tường minh (review 12-10 B14, eval R112 / R118): §1.2.1 chuyển máy mọi lúc, nên
# không được chờ tầng ngữ nghĩa (model lỗi, 4 câu chọn khung, inbound trước xác minh đều chỉ có luật).
# Câu còn nói về lịch mà không có từ bệnh / thuốc ("hỏi bác sĩ khám giờ nào") là hỏi lịch: chỉ MENTION.
_CONSULT_PHRASES = compile_phrases(
    [
        "tư vấn bác sĩ",
        "bác sĩ tư vấn",
        "tư vấn sức khỏe",
        "tư vấn sức khoẻ",
        "tư vấn bệnh",
        "tư vấn về bệnh",
        "tư vấn thuốc",
        "tư vấn về thuốc",
        "hỏi bác sĩ",
        "câu hỏi về bệnh",
        "hỏi về bệnh",
        "hỏi về thuốc",
        "hỏi về triệu chứng",
        "hỏi về sức khỏe",
        "hỏi về sức khoẻ",
    ]
)

_SYMPTOMS = compile_phrases(
    [
        "đau",
        "nhức",
        "sốt",
        "ho",
        "nôn",
        "buồn nôn",
        "chóng mặt",
        "hoa mắt",
        "mệt",
        "ngứa",
        "sưng",
        "viêm",
        "tiêu chảy",
        "táo bón",
        "mất ngủ",
        "huyết áp",
        "tiểu đường",
        "dạ dày",
        "triệu chứng",
        "bệnh",
        "thuốc",
        "dị ứng",
        "nổi mẩn",
        "phát ban",
        "chảy máu",
        "tê",
        "khàn tiếng",
        "khó tiêu",
        "đầy bụng",
    ]
)
# Cụm chứa từ triệu chứng nhưng không phải triệu chứng
_NOT_SYMPTOM = compile_phrases(
    ["bệnh viện", "bệnh nhân", "khám bệnh", "đơn thuốc", "hồ sơ bệnh án"]
)

_INTERROGATIVE_FINALS = frozenset({"không", "chưa", "sao", "gì", "nào", "à", "hả", "nhỉ", "chứ"})
_INTERROGATIVE_PHRASES = compile_phrases(
    ["có phải", "liệu", "thế nào", "ra sao", "làm sao", "tại sao", "vì sao"]
)
_MEDICATION = compile_phrases(["thuốc"])
_MEDICATION_ACTIONS = compile_phrases(
    [
        "ngưng",
        "ngừng",
        "dừng",
        "bỏ thuốc",
        "tiếp tục uống",
        "uống tiếp",
        "đổi thuốc",
        "tăng liều",
        "giảm liều",
    ]
)
_TRAILING_PARTICLES = frozenset({"ạ", "vậy", "thế", "em", "chị", "anh", "bác sĩ"})
_TRAILING_PARTICLES_UNACCENTED = frozenset(strip_diacritics(w) for w in _TRAILING_PARTICLES)
_INTERROGATIVE_FINALS_UNACCENTED = frozenset(strip_diacritics(w) for w in _INTERROGATIVE_FINALS)
# Có từ nói về lịch hẹn -> câu hỏi đuôi là hỏi về lịch, không phải hỏi về triệu chứng
_SCHEDULING = compile_phrases(
    ["đặt lịch", "lịch", "hẹn", "khung", "giờ", "đổi", "hủy", "tái khám", "đăng ký", "khám"]
)


def extract_clinical(transcript: str) -> Field[ClinicalLevel]:
    text = clean(transcript)
    if not text:
        return Field.nothing(ClinicalLevel.NONE)
    unaccented = is_unaccented(text)
    exact = Provenance.NORMALIZED if unaccented else Provenance.EXACT

    emergency = find_phrase(text, _EMERGENCY, unaccented=unaccented)
    if emergency is not None:
        return Field(ClinicalLevel.EMERGENCY, exact, span=emergency.group(0))

    advice = find_phrase(text, _ADVICE_PHRASES, unaccented=unaccented)
    if advice is not None:
        if _asks_about_the_booking(text, advice.group(0), unaccented):
            # "Hủy lịch có sao không em": hỏi về việc hủy, không hỏi về sức khỏe. Chưa chắc nên chỉ là
            # MENTION — tầng ngữ nghĩa đọc lại (CLINICAL_UNRESOLVED), không chuyển máy chỉ vì cụm này.
            return Field(ClinicalLevel.MENTION, exact, span=advice.group(0))
        return Field(ClinicalLevel.ADVICE_REQUEST, exact, span=advice.group(0))

    consult = find_phrase(text, _CONSULT_PHRASES, unaccented=unaccented)
    if consult is not None:
        rest = remove_phrases(
            remove_phrases(text, _CONSULT_PHRASES, unaccented), _NOT_SYMPTOM, unaccented
        )
        about_booking = (
            find_phrase(rest, _SCHEDULING, unaccented=unaccented) is not None
            and find_phrase(rest, _SYMPTOMS, unaccented=unaccented) is None
        )
        level = ClinicalLevel.MENTION if about_booking else ClinicalLevel.ADVICE_REQUEST
        return Field(level, exact, span=consult.group(0))

    # Câu hỏi điều chỉnh thuốc vẫn là tư vấn lâm sàng khi có chữ "khám"/"lịch".
    # Luật câu hỏi triệu chứng phía dưới cố ý bỏ qua ngữ cảnh lịch hẹn, nên xét riêng thuốc.
    if (
        find_phrase(text, _MEDICATION, unaccented=unaccented) is not None
        and find_phrase(text, _MEDICATION_ACTIONS, unaccented=unaccented) is not None
        and _is_question(text, unaccented=unaccented)
    ):
        return Field(ClinicalLevel.ADVICE_REQUEST, exact, span=text)

    symptom_text = remove_phrases(text, _NOT_SYMPTOM, unaccented)
    symptom = find_phrase(symptom_text, _SYMPTOMS, unaccented=unaccented)
    if symptom is None:
        return Field.nothing(ClinicalLevel.NONE)

    if (
        not unaccented
        and _is_question(symptom_text)
        and find_phrase(symptom_text, _SCHEDULING) is None
    ):
        # "đau bụng thế này có được không" — hỏi đánh giá triệu chứng, không nhắc tới lịch
        return Field(ClinicalLevel.ADVICE_REQUEST, Provenance.NORMALIZED, span=symptom_text)
    return Field(ClinicalLevel.MENTION, exact, span=symptom.group(0))


# Hỏi đánh giá mức độ: đối tượng có thể là sức khỏe ("đau thế này có sao không") hoặc chính việc
# với lịch hẹn ("hủy lịch có sao không", "đổi giờ có ảnh hưởng gì không")
_ASSESSMENT = compile_phrases(
    [
        "có sao không",
        "có nguy hiểm không",
        "có nặng không",
        "có bị làm sao không",
        "có bình thường không",
        "có ảnh hưởng gì không",
    ]
)
# Việc với lịch hẹn mà câu hỏi đánh giá có thể nói tới
_BOOKING_ACTIONS = compile_phrases(
    [
        "hủy lịch",
        "hủy hẹn",
        "đổi lịch",
        "đổi giờ",
        "đổi ngày",
        "dời lịch",
        "hủy",
        "đến muộn",
        "đến trễ",
    ]
)


def _asks_about_the_booking(text: str, advice: str, unaccented: bool) -> bool:
    """Câu hỏi đánh giá về việc với lịch hẹn, không có từ triệu chứng / bệnh / thuốc nào."""
    if find_phrase(advice, _ASSESSMENT, unaccented=unaccented) is None:
        return False
    if find_phrase(text, _BOOKING_ACTIONS, unaccented=unaccented) is None:
        return False
    symptom_text = remove_phrases(text, _NOT_SYMPTOM, unaccented)
    return find_phrase(symptom_text, _SYMPTOMS, unaccented=unaccented) is None


def _is_question(text: str, *, unaccented: bool = False) -> bool:
    words = text.split()
    trailing = _TRAILING_PARTICLES_UNACCENTED if unaccented else _TRAILING_PARTICLES
    finals = _INTERROGATIVE_FINALS_UNACCENTED if unaccented else _INTERROGATIVE_FINALS
    while words and words[-1] in trailing:
        words.pop()
    if len(words) >= 2 and words[-1] in finals:
        return True
    return find_phrase(text, _INTERROGATIVE_PHRASES, unaccented=unaccented) is not None
