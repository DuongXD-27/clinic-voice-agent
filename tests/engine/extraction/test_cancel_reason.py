import pytest

from callbot.engine.extraction.cancel_reason import extract_cancel_reason
from callbot.engine.extraction.schema import Provenance


@pytest.mark.parametrize(
    "text, expected",
    [
        ("hôm đó tôi bận", "PATIENT_UNAVAILABLE"),
        ("tôi đi công tác", "PATIENT_UNAVAILABLE"),
        ("hôm đó không đi được", "PATIENT_UNAVAILABLE"),
        ("tôi khỏi rồi", "NO_LONGER_NEEDED"),
        ("không cần khám nữa", "NO_LONGER_NEEDED"),
        ("tôi khám chỗ khác rồi", "WENT_ELSEWHERE"),
        ("đi viện khác", "WENT_ELSEWHERE"),
        ("đắt quá", "COST"),
        ("không đủ tiền", "COST"),
    ],
)
def test_explicit_reasons(text: str, expected: str) -> None:
    result = extract_cancel_reason(text)
    assert result.value == expected
    assert result.provenance is Provenance.EXACT


@pytest.mark.parametrize(
    "text",
    [
        "hủy đi",
        "tôi không bận nhưng muốn hủy",  # phủ định
        "bận mà cũng đắt quá",  # nhiều lý do -> không chọn hộ
        "vợ tôi bảo thế",  # không suy diễn
    ],
)
def test_unspecified(text: str) -> None:
    result = extract_cancel_reason(text)
    assert result.value == "UNSPECIFIED"
    assert result.provenance is Provenance.NONE
