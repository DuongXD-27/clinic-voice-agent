"""normalize_name (khóa so khớp tên) và match_record (đối chiếu một hồ sơ chuẩn)."""

import unicodedata
from datetime import date

import pytest

from callbot.engine.verification import MatchDetail, match_record, matches
from callbot.engine.verification.names import normalize_name

DOB = date(1978, 3, 14)
REF = {
    "patient_id": "pt_3391",
    "full_name": "Nguyễn Văn A",
    "dob": "1978-03-14",
    "verifiable": True,
}


@pytest.mark.parametrize(
    "a, b",
    [
        ("Nguyễn Văn A", "nguyễn văn a"),
        ("NGUYỄN VĂN A", "Nguyễn Văn A"),
        ("Nguyễn   Văn\tA", "Nguyễn Văn A"),
        ("  Nguyễn Văn A  ", "Nguyễn Văn A"),
        (unicodedata.normalize("NFD", "Nguyễn Văn A"), "Nguyễn Văn A"),  # NFD từ ASR
        ("Đặng Thị Hà", "đặng thị hà"),  # đ/Đ không tách được bằng NFD
    ],
)
def test_normalize_name_preserves_diacritics_but_ignores_case_and_space(a: str, b: str) -> None:
    assert normalize_name(a) == normalize_name(b)


def test_normalize_name_tradeoff_ha_equals_ha() -> None:
    # R-22: lệch dấu thanh không được tự chấp nhận khi N chưa chốt.
    assert normalize_name("Hà") != normalize_name("Hạ")


def test_normalize_name_does_not_drop_or_reorder_tokens() -> None:
    assert normalize_name("Văn A") != normalize_name("Nguyễn Văn A")
    assert normalize_name("A Văn Nguyễn") != normalize_name("Nguyễn Văn A")


@pytest.mark.parametrize(
    "name, dob, expected",
    [
        ("nguyễn văn a", DOB, MatchDetail.NAME_AND_DOB_MATCH),
        ("Nguyen Van A", DOB, MatchDetail.NAME_MISMATCH),
        ("Nguyễn Văn A", date(1979, 3, 14), MatchDetail.DOB_MISMATCH),
        ("Trần Văn B", DOB, MatchDetail.NAME_MISMATCH),
        ("Trần Văn B", date(1979, 3, 14), MatchDetail.BOTH_MISMATCH),
        ("Văn A", DOB, MatchDetail.NAME_MISMATCH),  # thiếu họ: không fuzzy
    ],
)
def test_match_record_outcomes(name: str, dob: date, expected: MatchDetail) -> None:
    assert match_record(name, dob, REF) is expected


@pytest.mark.parametrize(
    "ref",
    [
        {**REF, "verifiable": False},
        {**REF, "full_name": None, "dob": None, "verifiable": False},
        {**REF, "dob": "14/03/1978"},  # dob sai định dạng dù verifiable bị đặt True
        {**REF, "full_name": ""},
        {"patient_id": "pt_x"},
    ],
)
def test_unverifiable_record_never_matches(ref: dict) -> None:
    assert match_record("Nguyễn Văn A", DOB, ref) is MatchDetail.RECORD_UNVERIFIABLE


def test_matches_wrapper_keeps_bool_contract_on_mock_verify_block() -> None:
    verify = {"full_name": "Nguyễn Văn A", "dob": "1978-03-14"}
    assert matches("nguyễn văn a", DOB, verify)
    assert not matches("nguyễn văn b", DOB, verify)
    assert not matches("nguyễn văn a", date(1978, 3, 15), verify)
    assert not matches("nguyễn văn a", DOB, {})
    assert not matches("nguyễn văn a", DOB, {"full_name": "Nguyễn Văn A", "dob": "14/03/1978"})


@pytest.mark.parametrize("claimed", ["ông nguyễn văn a", "chú Nguyễn Văn A", "ong nguyễn văn a"])
def test_an_honorific_before_the_name_still_matches(claimed: str) -> None:
    assert match_record(claimed, DOB, REF) is MatchDetail.NAME_AND_DOB_MATCH


def test_an_honorific_does_not_rescue_a_wrong_name_or_dob() -> None:
    assert match_record("ông nguyễn văn b", DOB, REF) is MatchDetail.NAME_MISMATCH
    assert match_record("ông nguyễn văn a", date(1978, 3, 15), REF) is MatchDetail.DOB_MISMATCH


@pytest.mark.parametrize("record", ["Ông Văn Tùng", "Chu Văn An"])
def test_a_surname_that_looks_like_an_honorific_still_matches_verbatim(record: str) -> None:
    ref = {**REF, "full_name": record}
    assert match_record(record.lower(), DOB, ref) is MatchDetail.NAME_AND_DOB_MATCH
