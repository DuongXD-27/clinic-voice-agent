import pytest

from callbot.engine.extraction.full_name import extract_full_name, read_full_name
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
        ("alo, tôi là Lê Hoa", "lê hoa"),
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
        ("tôi là bà Lê Na", "bà lê na"),
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
