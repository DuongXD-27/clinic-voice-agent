"""normalize_phone: đưa caller_number về dạng mock nhận; không chuẩn hóa được -> None."""

import pytest

from callbot.engine.verification.phone import MOCK_PHONE_RE, normalize_phone


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("0912345600", "0912345600"),
        ("+84912345600", "0912345600"),
        ("84912345600", "0912345600"),
        ("84 912 345 600", "0912345600"),  # đầu số "84" trần, có khoảng trắng
        ("840912345600", "0912345600"),  # "84" + số nội địa còn nguyên số 0
        ("+840912345600", "0912345600"),
        ("0084912345600", "0912345600"),
        ("+84 912 345 600", "0912345600"),
        ("091-234-5600", "0912345600"),
        ("(+84) 912.345.600", "0912345600"),
        ("0999999999", "0999999999"),
        ("0212345678", "0212345678"),
    ],
)
def test_normalizes_to_mock_pattern(raw: str, expected: str) -> None:
    result = normalize_phone(raw)
    assert result == expected
    assert MOCK_PHONE_RE.match(result)


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "+15551234567",  # mã quốc gia khác
        "0112345678",  # đầu số ngoài danh sách mock
        "091234560",  # 9 số
        "09123456001",  # 11 số
        "02412345678",  # cố định 11 số — mock chỉ nhận 10
        "8491234560",  # "84" + 8 số: thiếu một chữ số
        "+840000000001",  # sau mã quốc gia là số không có đầu số hợp lệ
        "abc",
        "+84",
    ],
)
def test_unnormalizable_is_none(raw) -> None:
    assert normalize_phone(raw) is None
