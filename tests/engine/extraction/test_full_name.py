import pytest

from callbot.engine.extraction.full_name import (
    extract_full_name,
    read_full_name,
    valid_name_span,
)
from callbot.engine.extraction.identity import Reason
from callbot.engine.extraction.schema import Provenance


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Nguyễn Văn A.", "nguyễn văn a"),
        ("Nguyễn Văn A mà", "nguyễn văn a"),
        ("Nguyễn Văn A nhé", "nguyễn văn a"),
        ("NGuyễn văn A nhé em", "nguyễn văn a"),
        ("à thì anh tên là Nguyễn Văn A nhé em", "nguyễn văn a"),
        ("Dạ, Nguyễn Văn A nhé em ạ", "nguyễn văn a"),
        ("Nguyễn Văn A, nha chị!", "nguyễn văn a"),
        ("nguyen van a nhe em", "nguyen van a"),
        ("Nguyễn Văn A nhe em", "nguyễn văn a"),
        ("Nguyen Van A nhé em", "nguyen van a"),
        ("Trần Thị Bích Ngọc Anh nhé em", "trần thị bích ngọc anh"),
        ("Nguyễn Thị Anh nhé em", "nguyễn thị anh"),
        ("Nguyễn Văn Em nhé anh", "nguyễn văn em"),
        ("Nguyen Van A Em", "nguyen van a em"),
        ("Dạ, tôi là Nguyễn Văn A", "nguyễn văn a"),
        ("tôi là Nguyễn Văn A", "nguyễn văn a"),
        ("dạ vâng tên tôi là Trần Thị Bích Ngọc ạ", "trần thị bích ngọc"),
        ("Em tên là Phạm Minh Hoàng", "phạm minh hoàng"),
        ("alo, tôi là Nguyễn Hoa", "nguyễn hoa"),
        ("Dạ tôi tên là Nguyễn Văn A, còn chị tôi là Nguyễn Thị B", "nguyễn văn a"),
        ("Toi la Nguyen Van A con em toi la Nguyen Van B", "nguyen van a"),
        ("Nguyen Van Ma", "nguyen van ma"),
        # Tên chứa từ khoá nghiệp vụ / đồng ý / từ chối vẫn phải lấy được (H2)
        ("Lê Văn Thôi", "lê văn thôi"),
        ("Trần Văn Được", "trần văn được"),
        ("Nguyễn Thị Anh", "nguyễn thị anh"),
        # Unicode tổ hợp (NFD) và kiểu bỏ dấu mới được chuẩn hoá
        ("Nguyễn Văn A", "nguyễn văn a"),
        ("Lê Thị Hoà", "lê thị hòa"),
    ],
)
def test_extracts_normalized_name(text: str, expected: str) -> None:
    result = extract_full_name(text)
    assert result.value == expected
    assert result.provenance is Provenance.NORMALIZED
    assert result.span == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "alo",
        "a lô",
        "ai đấy",
        "dạ",
        "vâng ạ",
        "Hoa",  # < 2 từ
        "Nguyễn Văn A 1978",  # chứa chữ số
        "anh cần gì",  # câu nói, không phải tên
        "không phải tôi",
        "tôi muốn hỏi về lịch khám của tôi",  # quá dài và có từ chức năng
        "Em tôi là Nguyễn Văn A, còn chị tôi là Nguyễn Thị B",
        "Tôi là Nguyễn Văn A hay Nguyễn Văn B",
        "Nguyễn Văn A, còn em tôi là Nguyễn Văn B",
        # Toàn chữ cái đơn: ASR nghe đánh vần / nói tắt, không phải họ tên
        "T T B",
        "T. T. B.",
        "t.t.b",
        "tôi là T T B",
        "A B C",
        "X Y",
    ],
)
def test_rejects_non_names(text: str) -> None:
    result = extract_full_name(text)
    assert result.value is None
    assert result.provenance is Provenance.NONE


@pytest.mark.parametrize("text", ["Ai đấy?", "ai the", "ai gọi vậy", "Dạ, cho hỏi ai đấy ạ?"])
def test_caller_identity_questions_do_not_enter_name_fallback(text: str) -> None:
    reading = read_full_name(text)
    assert not reading.field.found and reading.reason is Reason.NOT_A_NAME


# --- Tiếng đệm và danh xưng trước tên (demo 22-09: "à thì tôi là ông Nguyễn Văn a") -------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("à thì tôi là ông Nguyễn Văn a", "nguyễn văn a"),
        ("tôi là ông Nguyễn Văn A", "nguyễn văn a"),
        ("ừm, tôi tên Nguyễn Văn A", "nguyễn văn a"),
        ("thì tôi là Nguyễn Văn A", "nguyễn văn a"),
        ("ờ bà Trần Thị Mai đây", "trần thị mai"),
        # Còn dưới 3 từ sau danh xưng: có thể là họ thật (Chu, Ông) -> giữ, Verifier so cả hai dạng
        ("Chu Văn An", "chu văn an"),
        ("tôi là ông Văn Tùng", "ông văn tùng"),
        ("tôi là bà Nguyễn Lan", "bà nguyễn lan"),
    ],
)
def test_fillers_and_honorifics_before_the_name(text: str, expected: str) -> None:
    assert extract_full_name(text).value == expected


@pytest.mark.parametrize("text", ["a thi toi la nguyen van a", "u nguyen van a"])
def test_unaccented_fillers_are_not_stripped(text: str) -> None:
    """Không dấu: "a", "u", "thi" có thể là tên — luật không đoán, để tuyến sau / hỏi lại."""
    assert extract_full_name(text).value != "nguyen van a"


# --- Tự nhận ở cuối câu bằng danh xưng: "Nguyễn Văn A là tên chú" -----------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Nguyễn Văn A là tên tôi", "nguyễn văn a"),
        ("Nguyễn Văn A là tên ông", "nguyễn văn a"),
        ("Nguyễn Văn A là tên chú", "nguyễn văn a"),
        ("Nguyễn Văn A là tên bác", "nguyễn văn a"),
        ("Lê Thị Hoa là tên cô", "lê thị hoa"),
        ("Trần Thị Mai, đấy là tên bà", "trần thị mai"),
        ("Phạm Văn Nam là tên anh nhé", "phạm văn nam"),
        ("nguyen van a la ten chu", "nguyen van a"),
    ],
)
def test_self_claim_at_the_end_with_an_honorific(text: str, expected: str) -> None:
    assert extract_full_name(text).value == expected


@pytest.mark.parametrize(
    "text",
    [
        "Nguyễn Văn A là tên ông tôi",
        "Nguyễn Văn A là tên bố tôi",
        "Tên chú của tôi là Nguyễn Văn A",
    ],
)
def test_a_possessive_makes_it_a_relative_not_the_caller(text: str) -> None:
    reading = read_full_name(text)
    assert not reading.field.found and reading.reason is Reason.OTHER_PERSON


# --- Dấu hiệu họ tên: câu nói thường đúng hình dạng không được thành tên -----------------------

UNANCHORED_SPEECH = [
    "trời hôm nay đẹp quá",
    "hôm qua ăn phở",
    "mạng lag quá",
    "đang lái xe",
    # Từ đầu trùng họ
    "trần nhà",
    "hồ sơ bệnh án",
    "lương tháng",
    "lưu tin nhắn",
    "dương tính",
    "đồng ý nhé",
    "mai anh bận",
    "văn phòng",
    "hà nội",
    "phạm vi",
    "huỳnh quang",
    # Họ + tên đệm ghép thành từ thông dụng
    "trịnh trọng quá",
    "đồng minh thân thiết",
    "trần thế gian",
    # Tên đệm + từ thứ ba ghép thành từ thông dụng
    "hồ thu hoạch",
    "từ thị trấn lên",
    "lại thanh toán à",
    # Không dấu
    "troi hom nay dep qua",
    "dang lai xe",
    "tu van giup",
    "do thi lon",
    "ho thi biet",
    "phan van qua",
    "lai van the",
]


@pytest.mark.parametrize("text", UNANCHORED_SPEECH)
def test_ordinary_speech_is_left_to_slot_filling(text: str) -> None:
    reading = read_full_name(text)
    assert not reading.field.found
    assert reading.reason is Reason.UNANCHORED


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Nguyễn Lan", "nguyễn lan"),
        ("Huỳnh Mai", "huỳnh mai"),
        ("Phan Văn An", "phan văn an"),
        ("Hà Thị Hoa", "hà thị hoa"),
        ("Đồng Văn Minh", "đồng văn minh"),
        ("Mai Thanh Hà", "mai thanh hà"),
        ("Hồ Thu Hà", "hồ thu hà"),
        ("Nguyễn Thanh Toàn", "nguyễn thanh toàn"),
        ("tôi là bà Nguyễn Lan", "bà nguyễn lan"),
        ("tran thi mai", "tran thi mai"),
        ("huynh minh tuan", "huynh minh tuan"),
    ],
)
def test_anchored_names_stay_with_the_rule(text: str, expected: str) -> None:
    reading = read_full_name(text)
    assert reading.reason is Reason.OK
    assert reading.field.value == expected


@pytest.mark.parametrize(
    ("text", "model_name"),
    [
        ("Lê Na", "lê na"),
        ("Phan An", "phan an"),
        ("Hà Hà", "hà hà"),
        ("Hà Anh Tuấn", "hà anh tuấn"),
        ("Âu Dương Phong", "âu dương phong"),
        ("Lại Văn Sâm", "lại văn sâm"),
        ("tôi là bà Lê Na", "lê na"),
        ("le minh tuan", "le minh tuan"),
        ("ho van nam", "ho van nam"),
        # Trùng câu nói thường sau chuẩn hoá: tên hay không là việc của slot filling
        ("đồng minh thân", "đồng minh thân"),
        ("tôi tên Trịnh Trọng Nam", "trịnh trọng nam"),
        ("tôi là Lê Thanh Toán", "lê thanh toán"),
    ],
)
def test_unanchored_real_names_are_deferred_not_rejected(text: str, model_name: str) -> None:
    """Bảng dấu hiệu chỉ chặn luật; tên mô hình trả về không bị các bảng đó loại."""
    reading = read_full_name(text)
    assert not reading.field.found
    assert reading.reason is Reason.UNANCHORED
    assert valid_name_span(model_name)


# --- Người gọi nói tiếng Anh (QC qc-w6-01) ----------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "My name is Nguyen Van A",
        "I'm Nguyen Van A",
        "Yes, this is Nguyen Van A",
        "it's Nguyen Van A",
        "This is Nguyen Van A speaking",
        "Nguyen Van A here",
    ],
)
def test_english_self_introduction(text: str) -> None:
    assert extract_full_name(text).value == "nguyen van a"


def test_english_alternatives_are_multiple_names() -> None:
    assert read_full_name("Nguyen Van A or Tran Van B").reason is Reason.AMBIGUOUS


@pytest.mark.parametrize(
    "text",
    [
        "maybe Nguyen Van A",
        "I think it's Nguyen Van A",
        "My name is not Tran Van B, it's Nguyen Van A",
    ],
)
def test_english_hedged_name_is_uncertain(text: str) -> None:
    assert read_full_name(text).reason is Reason.UNCERTAIN


@pytest.mark.parametrize(
    "text",
    [
        "Sorry, my name is Nguyen Van A",
        "Actually, my name is Nguyen Van A",
        "sorry my name is Nguyen Van A",
    ],
)
def test_english_politeness_is_not_a_hedge(text: str) -> None:
    assert read_full_name(text).field.value == "nguyen van a"


def test_calling_about_something_is_not_a_hedge() -> None:
    # Luật chưa đọc tên sau một mệnh đề kể chuyện; không phân vân thì model đọc tên vẫn được hỏi
    reading = read_full_name("I'm calling about my appointment, my name is Nguyen Van A")
    assert reading.reason is not Reason.UNCERTAIN


def test_a_mid_sentence_sorry_is_a_correction() -> None:
    assert read_full_name("Nguyen Van A, sorry, Nguyen Van B").reason is Reason.UNCERTAIN
