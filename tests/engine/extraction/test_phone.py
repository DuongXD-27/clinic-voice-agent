"""extract_phone: dãy chữ số người gọi đọc ở ASK_PHONE (inbound không có caller_number).

Chỉ trả nguyên dãy chữ số; đầu số ("0", "+84", "84") do Verifier chuẩn hóa (`verification.phone`).
"""

from datetime import datetime, timezone

import pytest

from callbot.engine.extraction.extractor import InformationExtractor
from callbot.engine.extraction.phone import extract_phone
from callbot.engine.extraction.schema import Intent, Provenance, QuestionId, TurnContext

NOW = datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "transcript, digits",
    [
        ("0912345600", "0912345600"),
        ("0912 345 600", "0912345600"),
        ("091.234.5600", "0912345600"),
        ("+84 912 345 600", "84912345600"),
        # Đầu số "84" trần (không có dấu +), kể cả giữ nguyên số 0 nội địa
        ("84912345600", "84912345600"),
        ("84 912 345 600", "84912345600"),
        ("840912345600", "840912345600"),
        ("số tôi là 0912345600 ạ", "0912345600"),
        ("dạ số tôi là không chín một hai ba bốn năm sáu không không ạ", "0912345600"),
        ("không chín một hai, ba bốn năm, sáu không không", "0912345600"),
        ("tám bốn chín một hai ba bốn năm sáu không không", "84912345600"),
        ("tám tư chín một hai ba bốn năm sáu không không", "84912345600"),
        ("khong chin mot hai ba bon nam sau khong khong", "0912345600"),
        ("tam bon chin mot hai ba bon nam sau khong khong", "84912345600"),
        ("à, không chín một hai ba bốn năm sáu không không", "0912345600"),
        # Đọc theo hàng chục: "năm mươi sáu" = 5, 6; "mười" cuối dãy = 1, 0
        ("không chín một, hai ba bốn, năm mươi sáu, không không", "0912345600"),
        ("không chín một hai ba bốn năm sáu mười", "0912345610"),
        # R-44: lấy dãy số nói sau cùng
        ("0912345601 à không 0912345600", "0912345600"),
        ("0912 345 601, à nhầm, 0912 345 600", "0912345600"),
        (
            "không chín một hai ba bốn năm sáu không một, à không, "
            "không chín một hai ba bốn năm sáu không không",
            "0912345600",
        ),
    ],
)
def test_phone_digits_are_read_as_spoken_or_typed(transcript: str, digits: str) -> None:
    assert extract_phone(transcript).value == digits


@pytest.mark.parametrize(
    "transcript",
    [
        "",
        "Nguyễn Văn A",
        "tôi không nhớ số",
        "tôi muốn đặt lịch khám",
        "sinh ngày 14 tháng 3 năm 1978",
        "0912 345",  # đọc dở
        "091234560",  # 9 chữ số
        "0912345600123",  # 13 chữ số: không phải một số điện thoại
        "ba năm",  # tên có từ số
    ],
)
def test_no_phone_number_is_not_guessed(transcript: str) -> None:
    assert not extract_phone(transcript).found


def test_typed_digits_are_exact_and_spoken_digits_are_normalized() -> None:
    assert extract_phone("0912 345 600").provenance is Provenance.EXACT
    spoken = extract_phone("dạ, không chín một hai ba bốn năm sáu không không")
    assert spoken.provenance is Provenance.NORMALIZED
    assert spoken.span == "dạ không chín một hai ba bốn năm sáu không không"


# --- Qua InformationExtractor: chỉ đọc số ở ASK_PHONE, không hỏi model, không thành nhu cầu ---


def _extract(question: QuestionId, transcript: str):
    return InformationExtractor().extract(
        TurnContext(turn=3, question_id=question, direction="inbound", now=NOW), transcript
    )


def test_extractor_reads_phone_only_at_ask_phone() -> None:
    at_phone = _extract(QuestionId.ASK_PHONE, "không chín một hai ba bốn năm sáu không không")
    assert at_phone.phone.value == "0912345600"
    assert at_phone.intent.value is Intent.NONE and not at_phone.full_name.found
    assert at_phone.model_status is None  # chỉ luật
    at_name = _extract(QuestionId.ASK_NAME, "0912345600")
    assert not at_name.phone.found


@pytest.mark.parametrize(
    "transcript, intent",
    [
        ("Tôi muốn đặt lịch khám", Intent.BOOK),
        ("cho tôi gặp nhân viên", Intent.REQUEST_HUMAN),
        ("Cho hỏi đặt lịch có dùng bảo hiểm y tế được không?", Intent.OUT_OF_SCOPE),
        ("tôi không nhớ số", Intent.CANNOT_PROVIDE),
    ],
)
def test_requests_at_ask_phone_keep_their_label_when_no_number_is_read(
    transcript: str, intent: Intent
) -> None:
    result = _extract(QuestionId.ASK_PHONE, transcript)
    assert not result.phone.found and result.intent.value is intent


def test_phone_is_not_in_trace() -> None:
    trace = _extract(QuestionId.ASK_PHONE, "0912345600").to_trace()
    assert "phone" not in trace and "0912345600" not in str(
        {k: v for k, v in trace.items() if k != "transcript"}
    )
