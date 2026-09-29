"""Bộ bẫy §5.6 / §9: ngưỡng AGREE theo hành động được mở khóa."""

import pytest

from callbot.engine.extraction.agreement import extract_agreement, gives_up_slot_change, is_bare_da
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
        # T-10 D-2: "vâng / ừ" là đồng ý; "dạ" một mình không bao giờ (PRD R-23, GC-CONF-01)
        ("vâng", Agreement.AGREE),
        ("ừ", Agreement.AGREE),
        ("dạ vâng", Agreement.AGREE),
        ("vang", Agreement.AGREE),
        ("dạ", Agreement.UNCLEAR),
        ("dạ ạ", Agreement.UNCLEAR),
        ("ok", Agreement.AGREE),
        ("có", Agreement.AGREE),
        ("được", Agreement.AGREE),
        ("Được, đổi giúp tôi.", Agreement.AGREE),
        ("đổi giúp tôi", Agreement.AGREE),
        ("đổi luôn", Agreement.AGREE),
        ("đồng ý", Agreement.AGREE),
        ("chốt đi em", Agreement.AGREE),
        ("được không em", Agreement.UNCLEAR),
        ("chắc là được", Agreement.UNCLEAR),
        ("vâng nhưng để tôi hỏi vợ đã", Agreement.UNCLEAR),
        ("dạ hôm đó tôi bận", Agreement.UNCLEAR),
        ("không", Agreement.REFUSE),
        ("không, khung khác", Agreement.REFUSE),
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


# --- Đáp lễ chỉ là tín hiệu khi đứng riêng / mở đầu câu --------------------------------------------


ALL_CONFIRMATIONS = [CANCEL, SLOT, CONFIRM, QuestionId.ASK_ATTENDANCE]


@pytest.mark.parametrize("question", ALL_CONFIRMATIONS)
@pytest.mark.parametrize(
    "text", ["Dạo này kẹt tiền quá em ạ", "Dạo này kẹt tiền quá em", "Về quê rồi em ạ"]
)
def test_trailing_particle_is_not_an_answer(question: QuestionId, text: str) -> None:
    """Demo 22-09: "ạ" cuối câu kể lý do từng thành tín hiệu mâu thuẫn (và AGREE ở câu đến khám)."""
    field = extract_agreement(text, question)
    assert not field.found and field.value is Agreement.UNCLEAR


@pytest.mark.parametrize("question", ALL_CONFIRMATIONS)
@pytest.mark.parametrize("text", ["vâng", "dạ vâng ạ", "dạ, để tôi xem đã"])
def test_standalone_or_leading_polite_word_is_still_a_signal(
    question: QuestionId, text: str
) -> None:
    assert extract_agreement(text, question).found


@pytest.mark.parametrize(
    ("text", "question", "expected"),
    [
        ("hủy lịch ạ", CANCEL, Agreement.AGREE),  # động từ hủy tường minh, "ạ" cuối không đổi gì
        ("vâng, hủy đi", CANCEL, Agreement.AGREE),
        ("vâng", CANCEL, Agreement.UNCLEAR),  # SF-05: đáp lễ một mình không hủy
        ("vâng", CONFIRM, Agreement.AGREE),
        ("tôi đến được ạ", CONFIRM, Agreement.AGREE),  # "được" vẫn là khẳng định
        ("tôi đến ạ", CONFIRM, Agreement.UNCLEAR),  # không còn nhờ "ạ" cuối câu mà thành AGREE
        ("dạ không", CONFIRM, Agreement.REFUSE),  # phủ định vẫn thắng đáp lễ mở đầu
        ("vâng, mấy giờ ạ", CONFIRM, Agreement.UNCLEAR),  # câu hỏi vẫn thắng đáp lễ mở đầu
        ("vang", CONFIRM, Agreement.AGREE),  # không dấu: giữ luật hiện tại
        ("toi ban lam em a", CONFIRM, Agreement.UNCLEAR),
    ],
)
def test_polite_position_keeps_priorities(
    text: str, question: QuestionId, expected: Agreement
) -> None:
    assert extract_agreement(text, question).value is expected


# --- T-04 §8: AGREE chỉ khi câu được giải thích hết -----------------------------------------------


@pytest.mark.parametrize("question", [CONFIRM, SLOT])
@pytest.mark.parametrize(
    "text",
    [
        # từ khẳng định là hư từ của câu kể
        "hôm đó tôi có việc bận",
        "tôi phải đi làm hôm đó",
        "tôi được nghỉ hôm đó mà",
        "hôm đó đúng ngày giỗ nhà tôi",
        "tôi đang chuẩn bị đi xa",
        # đáp lễ mở câu, phần sau là việc khác
        "dạ hôm đó tôi bận rồi",
        "vâng, hôm đó tôi phải đi công tác",
        "dạ tôi khám ở chỗ khác rồi",
        "vâng tôi nghe",
        "dạ em ơi cho chị hỏi chút",
        # đoán / cố gắng / điều kiện
        "chắc được",
        "hy vọng là được",
        "nếu rảnh thì được",
        # giờ khác, câu hỏi đuôi "chứ"
        "vâng, 3 giờ chiều nhé",
        "tôi đến trễ không sao chứ",
    ],
)
def test_affirmative_word_inside_another_statement_never_agrees(
    question: QuestionId, text: str
) -> None:
    result = extract_agreement(text, question)
    assert result.value is Agreement.UNCLEAR and result.found


@pytest.mark.parametrize("text", ["à", "ạ", "ừm"])
def test_filler_sound_alone_is_not_a_confirmation(text: str) -> None:
    """T-04 §8: "à?" là hỏi lại, "ừm" là đang nghĩ; "vâng / dạ / ừ / ờ" vẫn là xác nhận."""
    result = extract_agreement(text, CONFIRM)
    assert result.value is Agreement.UNCLEAR and result.found


@pytest.mark.parametrize(
    "text",
    [
        "tôi sẽ có mặt",
        "vâng, hôm đó tôi đến",
        "dạ đúng rồi em",
        "được rồi được rồi",
        "vâng vâng",
        "dạ vâng, cảm ơn em nhiều",
        "nhất định rồi",
        "đương nhiên",
        "đến chứ",
        "đi chứ",
        "không thành vấn đề",
        "không có vấn đề gì",
    ],
)
def test_short_attendance_answers_still_agree(text: str) -> None:
    assert extract_agreement(text, CONFIRM).value is Agreement.AGREE


@pytest.mark.parametrize("text", ["Được, đổi giúp tôi.", "được khung đó", "chốt đi em"])
def test_short_slot_answers_still_agree(text: str) -> None:
    assert extract_agreement(text, SLOT).value is Agreement.AGREE


@pytest.mark.parametrize("text", ["không cần đổi đâu", "không cần hủy", "không biết nữa"])
def test_not_wanting_a_change_is_not_a_refusal_to_attend(text: str) -> None:
    """Chữ "không" thuộc cụm khác: không hỏi "đổi hay hủy" (T-04 §8)."""
    result = extract_agreement(text, CONFIRM)
    assert result.value is Agreement.UNCLEAR and result.found


@pytest.mark.parametrize("text", ["không cần đổi", "không đổi"])
def test_not_changing_is_still_a_refusal_when_choosing_a_slot(text: str) -> None:
    assert extract_agreement(text, SLOT).value is Agreement.REFUSE


@pytest.mark.parametrize("text", ["doi giup toi", "doi luon"])
def test_unaccented_doi_is_not_a_slot_agreement(text: str) -> None:
    """ "doi" = đợi: "đợi giúp tôi" không được mở khóa đổi lịch."""
    assert extract_agreement(text, SLOT).value is not Agreement.AGREE


@pytest.mark.parametrize("text", ["dạ", "Dạ.", "dạ ạ"])
def test_bare_da(text: str) -> None:
    assert is_bare_da(text)


@pytest.mark.parametrize("text", ["dạ vâng", "dạ hôm đó tôi bận", "vâng"])
def test_da_with_more_is_not_bare(text: str) -> None:
    assert not is_bare_da(text)


@pytest.mark.parametrize(
    "text",
    ["thôi không đổi nữa", "giữ lịch cũ", "không, thôi", "thôi", "để nguyên", "không cần đổi"],
)
def test_giving_up_a_slot_change(text: str) -> None:
    assert gives_up_slot_change(text)


@pytest.mark.parametrize("text", ["không", "không được", "không, khung khác"])
def test_bare_refusal_is_not_giving_up(text: str) -> None:
    """Q-4: "không" trần chưa rõ muốn gì — Dialogue hỏi A/B, không đoán là bỏ đổi lịch."""
    assert not gives_up_slot_change(text)
