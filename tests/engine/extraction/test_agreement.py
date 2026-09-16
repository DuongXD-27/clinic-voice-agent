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
