"""Chuẩn hóa số gọi đến về dạng mock chấp nhận (`^(02|03|05|07|08|09)\\d{8}$`).

`caller_number` là metadata harness gửi trong `POST /v1/calls` (Listing 1), không phải lời khách nói —
nên chuẩn hóa ở bước đầu `Verifier.prepare()`, trước khi tra cứu, không thuộc Information Extraction.
Không chuẩn hóa được -> `None`: Verifier coi là không có ứng viên, KHÔNG gọi mock (tránh 400).
"""

import re
from typing import Optional

# Regex của clinic-mock `routes.py`: đầu số cố định + 8 chữ số (10 chữ số tất cả)
MOCK_PHONE_RE = re.compile(r"^(02|03|05|07|08|09)\d{8}$")
COUNTRY_CODE = "84"


def normalize_phone(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if raw.strip().startswith("+") or digits.startswith("00"):
        digits = digits.removeprefix("00")
        if not digits.startswith(COUNTRY_CODE):
            return None
        digits = "0" + digits[len(COUNTRY_CODE) :]
    elif len(digits) == 11 and digits.startswith(COUNTRY_CODE):
        # "84912345600" không có dấu + — vẫn là mã quốc gia
        digits = "0" + digits[len(COUNTRY_CODE) :]
    return digits if MOCK_PHONE_RE.match(digits) else None


__all__ = ["MOCK_PHONE_RE", "normalize_phone"]
