"""Chuẩn hóa số gọi đến về dạng mock chấp nhận (`^(02|03|05|07|08|09)\\d{8}$`).

`caller_number` là metadata harness gửi trong `POST /v1/calls` (Listing 1), không phải lời khách nói —
nên chuẩn hóa ở bước đầu `Verifier.prepare()`, trước khi tra cứu, không thuộc Information Extraction.
Không chuẩn hóa được -> `None`: Verifier coi là không có ứng viên, KHÔNG gọi mock (tránh 400).

Đầu số quốc gia nhận cả ba cách viết: "+84…", "0084…" và "84…" không có dấu cộng (harness hay bỏ
dấu "+"). Sau mã quốc gia là 9 chữ số ("84912345600") hoặc số nội địa đủ 10 chữ số còn nguyên số 0
("840912345600").

Số nội địa rơi mất số 0 đầu (đi qua kiểu số nguyên, Excel/CSV) còn đúng 9 chữ số: thêm lại số 0
("849123456" -> "0849123456", "912345600" -> "0912345600"). Chuỗi 9 chữ số không có cách đọc hợp lệ
nào khác — "84" + 7 chữ số không bao giờ là số Việt Nam — nên không lẫn với mã quốc gia.
"""

import re
from typing import Optional

# Regex của clinic-mock `routes.py`: đầu số cố định + 8 chữ số (10 chữ số tất cả)
MOCK_PHONE_RE = re.compile(r"^(02|03|05|07|08|09)\d{8}$")
COUNTRY_CODE = "84"
# Sau mã quốc gia: 9 chữ số (bỏ số 0 đầu) hoặc 10 chữ số (giữ số 0 đầu)
_NATIONAL_LENGTHS = (9, 10)
# Số nội địa 10 chữ số mất số 0 đầu
_DROPPED_ZERO_LENGTH = 9


def normalize_phone(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if raw.strip().startswith("+") or digits.startswith("00"):
        digits = digits.removeprefix("00")
        if not digits.startswith(COUNTRY_CODE):
            return None
        digits = _national(digits[len(COUNTRY_CODE) :])
    elif digits.startswith(COUNTRY_CODE) and len(digits) - len(COUNTRY_CODE) in _NATIONAL_LENGTHS:
        # "84912345600" / "840912345600" không có dấu + — vẫn là mã quốc gia
        digits = _national(digits[len(COUNTRY_CODE) :])
    elif len(digits) == _DROPPED_ZERO_LENGTH:
        digits = _national(digits)
    return digits if MOCK_PHONE_RE.match(digits) else None


def _national(rest: str) -> str:
    """Phần sau mã quốc gia về dạng nội địa: "912345600" -> "0912345600", "0912345600" giữ nguyên."""
    return rest if rest.startswith("0") else "0" + rest


__all__ = ["MOCK_PHONE_RE", "normalize_phone"]
