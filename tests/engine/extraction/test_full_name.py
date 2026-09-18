import pytest

from callbot.engine.extraction.full_name import extract_full_name
from callbot.engine.extraction.schema import Provenance


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Nguyễn Văn A.", "nguyễn văn a"),
        ("Nguyễn Văn A mà", "nguyễn văn a"),
        ("Nguyễn Văn A nhé", "nguyễn văn a"),
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
