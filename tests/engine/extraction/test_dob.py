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
        # ASR trộn chữ số với từ số; "linh" thay "không" khi đọc rời từng chữ số
        ("mười bốn tháng ba năm 2 không linh tư", date(2004, 3, 14)),
        ("mười bốn tháng ba năm hai không linh tư", date(2004, 3, 14)),
        ("mười bốn tháng ba năm 2 không không 4", date(2004, 3, 14)),
        ("mười bốn tháng ba năm 2 nghìn linh 4", date(2004, 3, 14)),
        ("mười bốn tháng ba năm một chín 9 0", date(1990, 3, 14)),
        ("mười bốn tháng 3 năm 2 không 1 5", date(2015, 3, 14)),
        ("mười 4 tháng ba năm 2004", date(2004, 3, 14)),
        ("ngày mùng 5 tháng 6 năm 2 không linh 5", date(2005, 6, 5)),
        # Năm đọc bằng chữ nhưng thiếu từ "năm"
        ("Mười bảy tháng tám một chín sáu tám", date(1968, 8, 17)),
        ("17 tháng 8 một chín sáu tám", date(1968, 8, 17)),
        ("mười bảy tháng tám một nghìn chín trăm sáu mươi tám", date(1968, 8, 17)),
        ("hai mốt tháng mười một một chín bảy tám", date(1978, 11, 21)),
        ("hai mốt tháng mười hai một chín bảy tám", date(1978, 12, 21)),
        # Năm đọc thành hai cặp: 19 | 90
        ("mười bảy tháng 8 1 chín chín mươi", date(1990, 8, 17)),
        ("mười bảy tháng tám năm một chín chín mươi", date(1990, 8, 17)),
        ("mười bảy tháng tám mười chín chín mươi lăm", date(1995, 8, 17)),
        ("mười bảy tháng tám hai không mười lăm", date(2015, 8, 17)),
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
        "14 tháng mười một",  # không được đọc thành tháng 10 năm "một"
        "14 tháng ba bảy tám",  # thiếu "năm": chỉ nhận năm đủ 4 chữ số
        "14/3",
        "sinh năm 1978",  # chỉ có năm
        "tôi 48 tuổi",  # nói tuổi thay năm sinh
        "ngày 14 tháng 3 âm lịch năm 1978",  # âm lịch
        "ngày 1 tháng 1 năm 20",  # 1920 và 2020 đều hợp lệ
        "mười bốn tháng ba năm linh tư",  # "linh" đứng đầu: không đọc rời được
        "mười bốn tháng ba năm một chín chín linh",  # "linh" đứng cuối
        "mười bốn tháng ba năm hai không mười",
        "mười bốn tháng ba năm hai 14",  # chữ số nhiều chữ lẫn với từ số
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


# --- Người gọi nói tiếng Anh / dạng ISO (QC qc-w6-01) ---------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "March 14, 1978",
        "14 March 1978",
        "the 14th of March, 1978",
        "March the 14th 1978",
        "Mar 14 1978",
        "born on March 14, 1978",
        "My birthday is March 14th 1978",
        "1978-03-14",
        "1978/3/14",
        "14 march 78",
    ],
)
def test_english_and_iso_dates(text: str) -> None:
    assert extract_dob(text, TODAY).value == date(1978, 3, 14)


@pytest.mark.parametrize(
    "text",
    [
        "March 14",  # thiếu năm: không điền năm hiện tại
        "Feb 30 1978",
        "March 14 or 15 1978",  # hai giá trị
        "March 14, 1978 or 1979",
    ],
)
def test_unusable_english_dates_are_invalid(text: str) -> None:
    assert extract_dob(text, TODAY).value == INVALID


def test_may_is_a_month_only_inside_a_full_english_date() -> None:
    assert extract_dob("May 5, 1990", TODAY).value == date(1990, 5, 5)
    assert extract_dob("nguyen thi may", TODAY).value is None
