from datetime import date

import pytest

from callbot.engine.extraction.dob import extract_dob
from callbot.engine.extraction.schema import INVALID, Provenance

TODAY = date(2026, 9, 15)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Ngày 14 tháng 3 năm 1978.", date(1978, 3, 14)),
        ("14/3/1978", date(1978, 3, 14)),
        ("14/03/1978", date(1978, 3, 14)),
        ("14-03-78", date(1978, 3, 14)),
        ("14 3 1978", date(1978, 3, 14)),
        ("14031978", date(1978, 3, 14)),
        ("mười bốn tháng ba năm bảy tám", date(1978, 3, 14)),
        ("mười bốn tháng ba năm một nghìn chín trăm bảy mươi tám", date(1978, 3, 14)),
        ("mười bốn tháng ba năm một chín bảy tám", date(1978, 3, 14)),
        ("một bốn không ba một chín bảy tám", date(1978, 3, 14)),
        ("hai mươi mốt tháng tư năm hai nghìn không trăm linh năm", date(2005, 4, 21)),
        ("hai mốt tháng mười hai năm tám lăm", date(1985, 12, 21)),
        ("ngày năm tháng năm năm một chín tám năm", date(1985, 5, 5)),
        ("mùng một tháng một năm 1990", date(1990, 1, 1)),
        ("dạ em sinh ngày 14 tháng 3 năm 1978 ạ", date(1978, 3, 14)),
        ("ngày 2 tháng 2 năm 10", date(2010, 2, 2)),  # 1910 -> 116 tuổi, chỉ 2010 hợp lệ
        ("ngày 29 tháng 2 năm 00", date(2000, 2, 29)),  # 1900 không nhuận
        # Cụm dẫn "năm sinh" / "sinh năm" / "ngày tháng năm sinh"
        ("14 tháng 3 sinh năm 1978", date(1978, 3, 14)),
        ("ngày 14 tháng 3 sinh năm 1978", date(1978, 3, 14)),
        ("14 tháng 3 năm sinh 1978", date(1978, 3, 14)),
        ("14/3 sinh năm 1978", date(1978, 3, 14)),
        ("14 3 sinh năm 1978", date(1978, 3, 14)),
        ("năm sinh 14 3 1978", date(1978, 3, 14)),
        ("sinh năm 14 3 1978", date(1978, 3, 14)),
        ("năm sinh 14031978", date(1978, 3, 14)),
        ("ngày tháng năm sinh 14/3/1978", date(1978, 3, 14)),
        ("ngay thang nam sinh 14/3/1978", date(1978, 3, 14)),
        ("14 thang 3 sinh nam 1978", date(1978, 3, 14)),
    ],
)
def test_valid_dates(text: str, expected: date) -> None:
    assert extract_dob(text, TODAY).value == expected


@pytest.mark.parametrize(
    "text",
    [
        "31/02/1980",  # ngày không tồn tại — không tự sửa
        "ngày 31 tháng 2 năm 1980",
        "14 tháng 3",  # thiếu năm — không điền năm hiện tại
        "14/3",
        "sinh năm 1978",  # chỉ có năm
        "tôi 48 tuổi",  # nói tuổi thay năm sinh
        "ngày 14 tháng 3 âm lịch năm 1978",  # âm lịch
        "ngày 1 tháng 1 năm 20",  # 1920 và 2020 đều hợp lệ
        "ngày 1 tháng 1 năm 2030",  # tương lai
        "ngày 1 tháng 1 năm 1900",  # quá 110 tuổi
        "14 tháng 3 năm 1978 à không 1979",  # tự sửa không đủ thông tin
        "14 tháng 3 hay 15 tháng 3 năm 1978",  # hai giá trị
        "một bốn không ba",  # đọc rời thiếu năm
    ],
)
def test_invalid_is_not_a_date(text: str) -> None:
    assert extract_dob(text, TODAY).value == INVALID


@pytest.mark.parametrize("text", ["không nhớ", "dạ vâng", "không", "", "alo"])
def test_no_date_content_is_none(text: str) -> None:
    result = extract_dob(text, TODAY)
    assert result.value is None
    assert result.provenance is Provenance.NONE


def test_self_correction_takes_last_value() -> None:
    assert extract_dob("ngày 14 à không 15 tháng 3 năm 1978", TODAY).value == date(1978, 3, 15)
    assert extract_dob("14/3/1978, à nhầm, 15/3/1978", TODAY).value == date(1978, 3, 15)


def test_provenance_distinguishes_digits_from_spoken_numbers() -> None:
    assert extract_dob("14/3/1978", TODAY).provenance is Provenance.EXACT
    assert extract_dob("mười bốn tháng ba năm bảy tám", TODAY).provenance is Provenance.NORMALIZED
