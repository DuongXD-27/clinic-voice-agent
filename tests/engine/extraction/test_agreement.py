"""Bộ bẫy §5.6 / §9: ngưỡng AGREE theo hành động được mở khóa."""

import pytest

from callbot.engine.extraction.agreement import extract_agreement
from callbot.engine.extraction.schema import Agreement, Provenance, QuestionId

CANCEL = QuestionId.CANCEL_RECONFIRM
SLOT = QuestionId.SLOT_READBACK
CONFIRM = QuestionId.CONFIRM_READBACK


# --- CANCEL_RECONFIRM: tỉ lệ AGREE sai ≈ 0 (SF-05) --------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "vâng",
        "dạ",
        "ừ",
        "dạ vâng ạ",
        "có",
        "được",
        "đúng",
        "đúng rồi",
        "ok",
        "không sao",
        "không hủy",
        "không hủy nữa",
        "đừng hủy",
        "giữ lịch",
        "thôi",
        "hủy được không",
        "hủy à",
        "hủy thì có mất phí gì không",  # câu hỏi, không phải đồng ý
        "thôi hủy đi",
        "không, hủy đi",  # tín hiệu mâu thuẫn
        "vâng nhưng mà để tôi hỏi vợ đã",
        "để tôi nghĩ đã",
        "hôm đó tôi bận mất rồi",
    ],
)
def test_cancel_reconfirm_never_agrees_without_explicit_cancel(text: str) -> None:
    assert extract_agreement(text, CANCEL).value is not Agreement.AGREE


@pytest.mark.parametrize(
    "text", ["hủy đi", "hủy giúp tôi", "đúng, hủy", "dạ hủy luôn em ạ", "ừ huỷ đi"]
)
def test_cancel_reconfirm_agrees_on_explicit_cancel_verb(text: str) -> None:
    assert extract_agreement(text, CANCEL).value is Agreement.AGREE


@pytest.mark.parametrize(
    "text", ["không hủy", "không hủy nữa", "thôi", "để sau", "chưa", "giữ lịch", "đừng hủy"]
)
def test_cancel_reconfirm_refusals(text: str) -> None:
    assert extract_agreement(text, CANCEL).value is Agreement.REFUSE


# --- SLOT_READBACK ------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("vâng", Agreement.UNCLEAR),
        ("dạ", Agreement.UNCLEAR),
        ("có", Agreement.AGREE),
        ("được", Agreement.AGREE),
        ("Được, đổi giúp tôi.", Agreement.AGREE),
        ("đồng ý", Agreement.AGREE),
        ("chốt đi em", Agreement.AGREE),
        ("được không em", Agreement.UNCLEAR),
        ("không", Agreement.REFUSE),
        ("thôi để sau", Agreement.REFUSE),
    ],
)
def test_slot_readback_threshold(text: str, expected: Agreement) -> None:
    assert extract_agreement(text, SLOT).value is expected


# --- CONFIRM_READBACK: UNCLEAR trên câu đồng ý thật phải thấp -----------------------


@pytest.mark.parametrize(
    "text", ["vâng", "có", "được ạ", "ừ đúng rồi", "dạ", "không sao", "không vấn đề gì", "được chứ"]
)
def test_confirm_readback_accepts_any_affirmative(text: str) -> None:
    assert extract_agreement(text, CONFIRM).value is Agreement.AGREE


@pytest.mark.parametrize(
    "text, expected",
    [
        ("đúng không nhỉ", Agreement.UNCLEAR),
        ("dạ không", Agreement.REFUSE),
        ("sai rồi", Agreement.REFUSE),
        ("mấy giờ ấy nhỉ", Agreement.UNCLEAR),
        ("vâng nhưng mà tôi muốn đổi giờ", Agreement.UNCLEAR),
    ],
)
def test_confirm_readback_traps(text: str, expected: Agreement) -> None:
    assert extract_agreement(text, CONFIRM).value is expected


def test_provenance_marks_whether_any_cue_was_seen() -> None:
    # Có tín hiệu nhưng dưới ngưỡng -> EXACT (không gọi tuyến sau)
    assert extract_agreement("vâng", CANCEL).provenance is Provenance.EXACT
    # Không có tín hiệu nào -> NONE (tuyến sau được phép xét)
    assert extract_agreement("hôm đó tôi bận mất rồi", CANCEL).provenance is Provenance.NONE


# --- T-04: câu hỏi đến khám ----------------------------------------------------------


@pytest.mark.parametrize("question", [CONFIRM, SLOT])
@pytest.mark.parametrize(
    "text",
    [
        "ờ để xem",
        "chắc là được",
        "có lẽ vậy",
        "vâng để tôi xem lại",
        "để tôi hỏi vợ đã",
        "chưa chắc",
        "được, nhưng để tôi xem đã",
    ],
)
def test_hedging_never_agrees(question: QuestionId, text: str) -> None:
    """Ngập ngừng không mở khóa lệnh ghi, kể cả khi có "vâng" / "được"."""
    result = extract_agreement(text, question)
    assert result.value is Agreement.UNCLEAR and result.found


@pytest.mark.parametrize(
    "text",
    [
        "vâng",
        "dạ",
        "ừ",
        "ờ",
        "vâng em",
        "vâng, cảm ơn em",
        "giữ lịch nhé",
        "giữ nguyên lịch",
        "vâng, giữ lịch",
        "chắc chắn rồi",
    ],
)
def test_attendance_agrees_on_polite_words_and_keeping(text: str) -> None:
    assert extract_agreement(text, CONFIRM).value is Agreement.AGREE


@pytest.mark.parametrize(
    "text, span",
    [
        ("tôi sẽ đến", "sẽ đến"),
        ("không hủy đâu, tôi vẫn đến", "vẫn đến"),
    ],
)
def test_stated_attendance_agrees_only_at_attendance_questions(text: str, span: str) -> None:
    result = extract_agreement(text, CONFIRM, attendance=span)
    assert (result.value, result.span) == (Agreement.AGREE, span)
    assert extract_agreement(text, CANCEL, attendance=span).value is not Agreement.AGREE
    assert extract_agreement(text, SLOT, attendance=span).value is not Agreement.AGREE


@pytest.mark.parametrize(
    "text, expected",
    [
        ("tôi sẽ đến được không", Agreement.UNCLEAR),  # câu hỏi đuôi chặn trước
        ("không, tôi vẫn đến", Agreement.UNCLEAR),  # tín hiệu mâu thuẫn
        ("không hủy", Agreement.UNCLEAR),  # không hủy chưa phải là sẽ đến
        ("không giữ lịch", Agreement.UNCLEAR),
    ],
)
def test_attendance_traps(text: str, expected: Agreement) -> None:
    result = extract_agreement(text, CONFIRM, attendance="vẫn đến" if "đến" in text else None)
    assert result.value is expected and result.found


@pytest.mark.parametrize("text", ["giữ lịch", "giữ nguyên", "không hủy", "đừng hủy"])
def test_keeping_is_still_refusal_outside_attendance(text: str) -> None:
    """Cùng cụm, câu hỏi khác nghĩa: ở hủy / chọn slot vẫn là từ chối (SF-05 không đổi)."""
    assert extract_agreement(text, CANCEL).value is Agreement.REFUSE
    assert extract_agreement(text, SLOT).value is Agreement.REFUSE
