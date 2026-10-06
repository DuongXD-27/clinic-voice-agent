"""cancel_reason (§5.8) — chỉ cụm tường minh, và phân biệt "không nói lý do" với "nhiều lý do".

Dialogue dùng `provenance` để biết lượt nào được phép thay lý do đã ghi nhận (T-05 §3.2).
"""

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
        ("chi phí cao", "COST"),
    ],
)
def test_explicit_reasons(text: str, expected: str) -> None:
    result = extract_cancel_reason(text)
    assert result.value == expected
    assert result.provenance is Provenance.EXACT


@pytest.mark.parametrize(
    "text, expected",
    [
        ("toi di cong tac", "PATIENT_UNAVAILABLE"),
        ("khong can kham nua", "NO_LONGER_NEEDED"),
        ("toi kham cho khac roi", "WENT_ELSEWHERE"),
        ("chi phi cao", "COST"),
    ],
)
def test_explicit_reasons_without_diacritics(text: str, expected: str) -> None:
    result = extract_cancel_reason(text)
    assert result.value == expected
    assert result.provenance is Provenance.NORMALIZED


@pytest.mark.parametrize(
    "text",
    [
        "hủy đi",
        "tôi không bận nhưng muốn hủy",  # phủ định
        "vợ tôi bảo thế",  # không suy diễn
        "huy di",
    ],
)
def test_no_reason_signal_leaves_the_field_untouched(text: str) -> None:
    """Không có tín hiệu nào: Dialogue giữ nguyên lý do đã ghi nhận ở lượt trước."""
    result = extract_cancel_reason(text)
    assert (result.value, result.provenance, result.span) == ("UNSPECIFIED", Provenance.NONE, None)


@pytest.mark.parametrize(
    "text, span, provenance",
    [
        ("bận mà cũng đắt quá", "bận + đắt quá", Provenance.EXACT),
        # Span đọc theo thứ tự cố định của bảng lý do, không theo thứ tự người gọi nói
        ("đắt quá mà cũng bận", "bận + đắt quá", Provenance.EXACT),
        ("tôi khỏi rồi mà cũng khám chỗ khác", "khỏi rồi + khám chỗ khác", Provenance.EXACT),
        (
            "toi di cong tac ma cung kham cho khac",
            "di cong tac + kham cho khac",
            Provenance.NORMALIZED,
        ),
    ],
)
def test_several_reasons_are_reported_as_seen_but_unspecified(
    text: str, span: str, provenance: Provenance
) -> None:
    """Nhiều lý do -> UNSPECIFIED (không chọn hộ), nhưng `found` vẫn True: Dialogue phải thay lý do
    cũ bằng UNSPECIFIED chứ không giữ ngầm giá trị trước đó (§3.2.3)."""
    result = extract_cancel_reason(text)
    assert (result.value, result.provenance, result.span) == ("UNSPECIFIED", provenance, span)
    assert result.found


@pytest.mark.parametrize(
    "text",
    [
        "Tôi muốn hủy, không phải vì không đủ tiền",
        "chẳng phải tôi bận",
        "khong phai vi het tien",
    ],
)
def test_a_denied_reason_is_not_recorded(text: str) -> None:
    assert extract_cancel_reason(text).found is False


@pytest.mark.parametrize(
    "text, reason",
    [
        ("không phải do bận đâu, tôi khỏi rồi", "NO_LONGER_NEEDED"),
        ("không phải đi công tác đâu, tôi không đủ tiền", "COST"),
        ("tôi phải đi công tác", "PATIENT_UNAVAILABLE"),  # "phải" không đi sau từ phủ định
    ],
)
def test_the_reason_left_after_a_denial_is_kept(text: str, reason: str) -> None:
    assert extract_cancel_reason(text).value == reason
