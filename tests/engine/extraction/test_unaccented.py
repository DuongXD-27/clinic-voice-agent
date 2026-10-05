"""Transcript ASR mất dấu (audio mode, hợp đồng §4.1).

Hai loại kiểm tra:
- khớp được: từ khoá an toàn / nghiệp vụ vẫn nhận ra khi không có dấu;
- không nhầm: các cặp trùng khi bỏ dấu ("đã"/"dạ", "đúng"/"đừng", "từ từ"/"tự tử") không mở khóa hành động.
"""

from datetime import date, datetime

import pytest

from callbot.engine.extraction.agreement import extract_agreement
from callbot.engine.extraction.cancel_reason import extract_cancel_reason
from callbot.engine.extraction.clinical import extract_clinical
from callbot.engine.extraction.dob import extract_dob
from callbot.engine.extraction.full_name import extract_full_name
from callbot.engine.extraction.intent import extract_intent
from callbot.engine.extraction.line_signal import extract_line_signal
from callbot.engine.extraction.schema import (
    INVALID,
    VN_TZ,
    Agreement,
    ClinicalLevel,
    Intent,
    LineSignal,
    Provenance,
    QuestionId,
)
from callbot.engine.extraction.slot_choice import extract_slot_choice
from callbot.engine.extraction.text import is_unaccented


def test_detection() -> None:
    assert is_unaccented("huy lich giup toi")
    assert not is_unaccented("huy lịch giúp tôi")  # có dấu một phần -> so có dấu
    assert not is_unaccented("14/3/1978")


# --- Intent -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("huy lich giup toi", Intent.CANCEL),
        ("toi khong di duoc nua", Intent.CANCEL),
        ("doi sang buoi chieu duoc khong", Intent.RESCHEDULE),
        ("cho toi gap nhan vien", Intent.REQUEST_HUMAN),
        ("bao hiem co chi tra khong", Intent.OUT_OF_SCOPE),
        ("toi la vo anh ay", Intent.NOT_PATIENT),
        ("em noi lai giup chi", Intent.REPEAT_REQUEST),
        ("toi se den", Intent.CONFIRM),
    ],
)
def test_intent_matches_unaccented(text: str, expected: Intent) -> None:
    result = extract_intent(text, "outbound")
    assert result.value is expected
    assert result.provenance is Provenance.NORMALIZED


@pytest.mark.parametrize(
    "text, not_expected",
    [
        ("khong huy", Intent.CANCEL),
        ("doi toi mot chut", Intent.RESCHEDULE),  # đợi, không phải dời
        ("toi den muon mot chut", Intent.CONFIRM),  # "tôi đến" bị loại vì trùng "tối đến"
    ],
)
def test_intent_unaccented_collisions(text: str, not_expected: Intent) -> None:
    assert extract_intent(text, "outbound").value is not not_expected


# --- Clinical ---------------------------------------------------------------------


@pytest.mark.parametrize("text", ["bo toi dang kho tho", "toi bi dau nguc", "con toi bi co giat"])
def test_emergency_unaccented(text: str) -> None:
    assert extract_clinical(text).value is ClinicalLevel.EMERGENCY


@pytest.mark.parametrize(
    "text", ["dau bung co sao khong", "toi nen uong thuoc gi", "co can di kham gap khong"]
)
def test_advice_unaccented(text: str) -> None:
    assert extract_clinical(text).value is ClinicalLevel.ADVICE_REQUEST


@pytest.mark.parametrize(
    "text",
    [
        "tu tu da em",  # từ từ, không phải tự tử
        "lieu co kip khong em",  # liệu, không phải liều
        "benh vien o dau vay",  # "dau" = đâu
        "ho hen toi mai",  # "ho" = họ
        "co lay khong em",
        "vo oi ra mau len",
    ],
)
def test_clinical_unaccented_collisions_do_not_transfer(text: str) -> None:
    assert extract_clinical(text).value not in (
        ClinicalLevel.EMERGENCY,
        ClinicalLevel.ADVICE_REQUEST,
    )


# --- Agreement (SF-05) ------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "da",
        "vang",
        "co",
        "dung",
        "dung huy",
        "dung, huy",
        "khong sao",
        "toi da doi y",
        "thoi huy di",
        "huy a",
    ],
)
def test_cancel_reconfirm_unaccented_never_agrees_without_clear_cancel(text: str) -> None:
    assert extract_agreement(text, QuestionId.CANCEL_RECONFIRM).value is not Agreement.AGREE


@pytest.mark.parametrize("text", ["huy di", "huy giup toi", "dung roi huy di"])
def test_cancel_reconfirm_unaccented_agrees(text: str) -> None:
    assert extract_agreement(text, QuestionId.CANCEL_RECONFIRM).value is Agreement.AGREE


@pytest.mark.parametrize(
    "question, text, expected",
    [
        (QuestionId.CONFIRM_READBACK, "vang", Agreement.AGREE),
        (QuestionId.CONFIRM_READBACK, "dung roi", Agreement.AGREE),
        (QuestionId.CONFIRM_READBACK, "khong van de gi", Agreement.AGREE),
        (QuestionId.CONFIRM_READBACK, "toi da doi y", Agreement.UNCLEAR),  # "da" = đã
        (QuestionId.CONFIRM_READBACK, "giu lich", Agreement.AGREE),
        (QuestionId.CONFIRM_READBACK, "khong huy", Agreement.UNCLEAR),
        (QuestionId.CONFIRM_READBACK, "chac la duoc", Agreement.UNCLEAR),
        (QuestionId.CONFIRM_READBACK, "de xem", Agreement.UNCLEAR),
        (QuestionId.CONFIRM_READBACK, "chac duoc", Agreement.UNCLEAR),  # T-04 §8: đoán
        (QuestionId.CONFIRM_READBACK, "vang toi dang lai xe", Agreement.UNCLEAR),  # T-04 §8
        (QuestionId.CONFIRM_READBACK, "vang cam on em", Agreement.AGREE),
        (QuestionId.SLOT_READBACK, "toi phai di lam hom do", Agreement.UNCLEAR),  # T-04 §8
        (QuestionId.CANCEL_RECONFIRM, "giu lich", Agreement.REFUSE),
        (QuestionId.SLOT_READBACK, "duoc", Agreement.AGREE),
        (QuestionId.SLOT_READBACK, "duoc khong", Agreement.UNCLEAR),
        (QuestionId.SLOT_READBACK, "doi di", Agreement.UNCLEAR),  # đợi đi
        (QuestionId.SLOT_READBACK, "khong", Agreement.REFUSE),
    ],
)
def test_readback_unaccented(question: QuestionId, text: str, expected: Agreement) -> None:
    assert extract_agreement(text, question).value is expected


# --- Tên, ngày sinh, lý do hủy, tín hiệu đường dây ---------------------------------


def test_full_name_unaccented_keeps_single_letter_given_name() -> None:
    assert extract_full_name("da toi la nguyen van a").value == "nguyen van a"
    assert (
        extract_full_name("nguyen thi ai").value == "nguyen thi ai"
    )  # "ai" trùng từ nghi vấn khi mất dấu
    assert extract_full_name("anh can gi").found is False


@pytest.mark.parametrize(
    "text, expected",
    [
        ("ngay muoi bon thang ba nam bay tam", date(1978, 3, 14)),
        ("hai muoi mot thang tu nam hai nghin khong tram linh nam", date(2005, 4, 21)),
        ("mot bon khong ba mot chin bay tam", date(1978, 3, 14)),
        ("ngay 14 thang 3 nam 1978", date(1978, 3, 14)),
        ("ngay 14 a khong 15 thang 3 nam 1978", date(1978, 3, 15)),
        ("14 thang 3 am lich", INVALID),
        ("toi 48 tuoi", INVALID),
    ],
)
def test_dob_unaccented(text: str, expected) -> None:
    result = extract_dob(text, date(2026, 9, 15))
    assert result.value == expected
    assert result.provenance is Provenance.NORMALIZED
    assert result.span == text  # span vẫn là chuỗi con của transcript gốc


@pytest.mark.parametrize(
    "text, expected",
    [
        ("toi di cong tac", "PATIENT_UNAVAILABLE"),
        ("khong can kham nua", "NO_LONGER_NEEDED"),
        ("ban toi bao the", "UNSPECIFIED"),  # "ban" = bạn
        ("dat lich roi ma", "UNSPECIFIED"),  # "dat" = đặt
    ],
)
def test_cancel_reason_unaccented(text: str, expected: str) -> None:
    assert extract_cancel_reason(text).value == expected


def test_line_signal_unaccented() -> None:
    assert (
        extract_line_signal("vui long de lai loi nhan sau tieng bip").value is LineSignal.VOICEMAIL
    )
    assert (
        extract_line_signal("thue bao quy khach vua goi tam thoi khong lien lac duoc").value
        is LineSignal.NONE
    )
    assert extract_line_signal("so may quy khach vua goi hien dang ban").value is LineSignal.NONE
    assert (
        extract_line_signal("toi dang ban").value is LineSignal.NONE
    )  # người thật; "ban" không có tổng đài


# --- Slot -------------------------------------------------------------------------

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=VN_TZ)  # thứ hai
SLOTS = [
    {"slot_id": "wed_1000", "starts_at": "2026-10-14T10:00:00+07:00"},
    {"slot_id": "wed_1430", "starts_at": "2026-10-14T14:30:00+07:00"},
    {"slot_id": "thu_1430", "starts_at": "2026-10-15T14:30:00+07:00"},
    {"slot_id": "thu_1800", "starts_at": "2026-10-15T18:00:00+07:00"},
]
PRESENTED = ("wed_1000", "wed_1430", "thu_1430")


@pytest.mark.parametrize(
    "text, slot_id",
    [
        ("khung thu hai", "wed_1430"),
        ("muoi gio sang", "wed_1000"),
        ("thu tu hai gio ruoi", "wed_1430"),
        ("sau gio chieu thu nam", "thu_1800"),
        ("thu 5 luc 14h30", "thu_1430"),
    ],
)
def test_slot_choice_unaccented(text: str, slot_id: str) -> None:
    choice = extract_slot_choice(text, SLOTS, PRESENTED, NOW).value
    assert choice.kind == "MATCH", choice
    assert choice.slot_id == slot_id


def test_slot_choice_unaccented_does_not_misread_sang_toi() -> None:
    # "đổi sang chiều": "sang" không phải "sáng"; "tôi muốn": "toi" không phải "tối"
    choice = extract_slot_choice("toi muon doi sang chieu", SLOTS, PRESENTED, NOW).value
    assert choice.criteria.period == "AFTERNOON"
    assert choice.kind == "AMBIGUOUS"
