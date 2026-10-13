"""IdentityVerifier hai pha trên FakeClinicAPI: prepare() ở lượt 0 là điểm chạm Gateway duy nhất,
verify() chỉ đọc ctx.identity_reference. Mọi case: không ghi Mock, không tạo patient."""

from datetime import date, datetime, timezone
from typing import Optional

import pytest

from callbot.engine.session.context import CallContext
from callbot.engine.tools.clinic_gateway import ClinicGateway
from callbot.engine.types import CallStart
from callbot.engine.verification import (
    IdentityVerifier,
    LookupStatus,
    MatchDetail,
    VerificationStatus,
)
from clinic_mock_sim import FakeClinicAPI, clinic_error

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
NAME, DOB = "Nguyễn Văn A", date(1978, 3, 14)


def _outbound(appointment_id: str = "apt_00417") -> CallContext:
    call = CallStart(call_id="c_out", direction="outbound", appointment_id=appointment_id)
    return CallContext(call=call, opened_at=NOW)


def _inbound(phone: Optional[str]) -> CallContext:
    call = CallStart(call_id="c_in", direction="inbound", caller_number=phone)
    return CallContext(call=call, opened_at=NOW)


def _verifier(fake: FakeClinicAPI) -> IdentityVerifier:
    return IdentityVerifier(ClinicGateway(fake, clinic_id="cl_vinmec"))


def _claim(ctx: CallContext, name: str = NAME, dob: date = DOB) -> CallContext:
    ctx.claimed_name, ctx.claimed_dob = name, dob
    return ctx


def _assert_read_only(fake: FakeClinicAPI) -> None:
    assert fake.writes == [] and fake.requests == []
    assert all(record.method == "GET" for record in fake.calls)


# --- prepare(): inbound ---------------------------------------------------------------------


@pytest.mark.parametrize("phone", [None, "", "+15551234567", "0112345678", "abc"])
def test_prepare_inbound_without_usable_phone_does_not_call_mock(phone) -> None:
    fake = FakeClinicAPI()
    ctx = _inbound(phone)
    result = _verifier(fake).prepare(ctx)

    assert result.status is LookupStatus.NO_PHONE
    assert result.transfer_reason == "PATIENT_NOT_FOUND"
    assert (ctx.identity_lookup, ctx.identity_reference) == ("NO_PHONE", [])
    assert fake.patient_lookups == [] and fake.calls == []


@pytest.mark.parametrize(
    "caller_number",
    ["+84 912 345 600", "84912345600", "84 912 345 600", "840912345600", "0084912345600"],
)
def test_prepare_inbound_normalizes_country_code_before_lookup(caller_number: str) -> None:
    """Harness gửi "+84…", "84…" trần hay "840…": tra cứu cùng một số nội địa 0xxxxxxxxx."""
    fake = FakeClinicAPI()
    ctx = _inbound(caller_number)
    result = _verifier(fake).prepare(ctx)

    assert fake.patient_lookups == ["0912345600"]
    assert result.status is LookupStatus.LOADED and result.candidates == 1
    assert ctx.identity_lookup == "LOADED"
    assert ctx.identity_reference == [
        {
            "patient_id": "pt_3391",
            "full_name": "Nguyễn Văn A",
            "dob": "1978-03-14",
            "verifiable": True,
        }
    ]
    _assert_read_only(fake)


def test_prepare_inbound_no_candidates_including_unregistered_caller() -> None:
    fake = FakeClinicAPI()
    ctx = _inbound("0999999999")
    result = _verifier(fake).prepare(ctx)

    assert result.status is LookupStatus.NO_CANDIDATES
    assert result.transfer_reason == "PATIENT_NOT_FOUND"
    assert (ctx.identity_lookup, ctx.identity_reference) == ("NO_CANDIDATES", [])
    assert fake.patient_lookups == ["0999999999"]
    _assert_read_only(fake)


def test_prepare_inbound_keeps_every_candidate_across_pages() -> None:
    fake = FakeClinicAPI()
    for i in range(130):  # > 1 trang (PAGE_LIMIT 100)
        fake.seed_patient(
            {
                "patient_id": f"pt_dup_{i}",
                "phone": "0777777777",
                "verify": {"full_name": f"Người {i}", "dob": "1990-01-01"},
            }
        )
    ctx = _inbound("0777777777")
    result = _verifier(fake).prepare(ctx)

    assert result.status is LookupStatus.LOADED and result.candidates == 130
    assert len(ctx.identity_reference) == 130
    assert all(
        set(ref) == {"patient_id", "full_name", "dob", "verifiable"}
        for ref in ctx.identity_reference
    )
    assert fake.patient_lookups == ["0777777777", "0777777777"]  # 2 trang, 1 lần prepare


def test_prepare_inbound_mock_failure_is_unavailable_with_code() -> None:
    fake = FakeClinicAPI()
    fake.fail_next("find_patient_by_phone")  # 503 UPSTREAM
    ctx = _inbound("0912345600")
    result = _verifier(fake).prepare(ctx)

    assert result.status is LookupStatus.UNAVAILABLE and result.error_code == "UPSTREAM"
    assert result.transfer_reason == "SYSTEM_ERROR"
    assert (ctx.identity_lookup, ctx.identity_reference) == ("UNAVAILABLE", [])


# --- prepare(): outbound ---------------------------------------------------------------------


def test_prepare_outbound_reads_appointment_once_and_keeps_canonical_reference() -> None:
    fake = FakeClinicAPI()
    ctx = _outbound()
    result = _verifier(fake).prepare(ctx)

    assert result.status is LookupStatus.LOADED and result.candidates == 1
    assert ctx.identity_reference == [
        {
            "patient_id": "pt_3391",
            "full_name": "Nguyễn Văn A",
            "dob": "1978-03-14",
            "verifiable": True,
        }
    ]
    assert [(c.method, c.path) for c in fake.calls] == [("GET", "/appointments/apt_00417")]
    _assert_read_only(fake)


def test_prepare_outbound_unknown_appointment_is_unavailable() -> None:
    fake = FakeClinicAPI()
    ctx = _outbound("apt_missing")
    result = _verifier(fake).prepare(ctx)

    assert result.status is LookupStatus.UNAVAILABLE and result.error_code == "NOT_FOUND"
    assert ctx.identity_lookup == "UNAVAILABLE"


def test_prepare_outbound_verify_null_is_unverifiable_reference() -> None:
    fake = FakeClinicAPI()
    fake.appointments["apt_00417"]["patient"]["verify"] = None
    ctx = _outbound()
    result = _verifier(fake).prepare(ctx)

    assert result.status is LookupStatus.LOADED
    assert ctx.identity_reference == [
        {"patient_id": "pt_3391", "full_name": None, "dob": None, "verifiable": False}
    ]


# --- verify(): không I/O ------------------------------------------------------------------------


def _prepared(fake: FakeClinicAPI, ctx: CallContext) -> tuple[IdentityVerifier, int]:
    verifier = _verifier(fake)
    verifier.prepare(ctx)
    return verifier, len(fake.calls)


@pytest.mark.parametrize(
    "name, dob, status, detail",
    [
        (NAME, DOB, VerificationStatus.VERIFIED, MatchDetail.NAME_AND_DOB_MATCH),
        ("nguyen van a", DOB, VerificationStatus.VERIFIED, MatchDetail.NAME_AND_DOB_MATCH),
        ("nguyen van a", date(1979, 3, 14), VerificationStatus.MISMATCH, MatchDetail.DOB_MISMATCH),
        ("tran van b", DOB, VerificationStatus.MISMATCH, MatchDetail.NAME_MISMATCH),
        ("Trần Văn B", DOB, VerificationStatus.MISMATCH, MatchDetail.NAME_MISMATCH),
        (NAME, date(1979, 3, 14), VerificationStatus.MISMATCH, MatchDetail.DOB_MISMATCH),
        ("Trần Văn B", date(1979, 3, 14), VerificationStatus.MISMATCH, MatchDetail.BOTH_MISMATCH),
    ],
)
def test_verify_outbound_against_held_reference(name, dob, status, detail) -> None:
    fake = FakeClinicAPI()
    ctx = _outbound()
    verifier, calls_after_prepare = _prepared(fake, ctx)

    result = verifier.verify(_claim(ctx, name, dob))

    assert (result.status, result.detail) == (status, detail)
    assert result.patient_id == ("pt_3391" if status is VerificationStatus.VERIFIED else None)
    assert result.transfer_reason == (
        None if status is VerificationStatus.VERIFIED else "IDENTITY_FAILED"
    )
    assert len(fake.calls) == calls_after_prepare  # verify không gọi mock
    _assert_read_only(fake)


def test_verify_outbound_unverifiable_record_fails_closed() -> None:
    fake = FakeClinicAPI()
    fake.appointments["apt_00417"]["patient"]["verify"] = None
    ctx = _outbound()
    verifier, _ = _prepared(fake, ctx)

    result = verifier.verify(_claim(ctx))

    assert result.status is VerificationStatus.MISMATCH
    assert result.detail is MatchDetail.RECORD_UNVERIFIABLE
    assert result.transfer_reason == "IDENTITY_FAILED"


def test_verify_unavailable_lookup_is_system_error_not_identity_failed() -> None:
    fake = FakeClinicAPI()
    ctx = _outbound("apt_missing")
    verifier, _ = _prepared(fake, ctx)

    result = verifier.verify(_claim(ctx))

    assert result.status is VerificationStatus.UNAVAILABLE
    assert result.transfer_reason == "SYSTEM_ERROR"


def test_verify_inbound_single_match_is_verified() -> None:
    fake = FakeClinicAPI()
    ctx = _inbound("0912345600")
    verifier, calls_after_prepare = _prepared(fake, ctx)

    result = verifier.verify(_claim(ctx))

    assert result.status is VerificationStatus.VERIFIED and result.patient_id == "pt_3391"
    assert result.candidates == 1
    assert len(fake.calls) == calls_after_prepare
    assert fake.patient_lookups == ["0912345600"]
    _assert_read_only(fake)


@pytest.mark.parametrize(
    "name, dob, detail",
    [
        ("Trần Văn B", DOB, MatchDetail.NAME_MISMATCH),
        (NAME, date(1979, 3, 14), MatchDetail.DOB_MISMATCH),
        ("Trần Văn B", date(1979, 3, 14), MatchDetail.BOTH_MISMATCH),
    ],
)
def test_verify_inbound_zero_match_is_patient_not_found(name, dob, detail) -> None:
    fake = FakeClinicAPI()
    ctx = _inbound("0912345600")
    verifier, _ = _prepared(fake, ctx)

    result = verifier.verify(_claim(ctx, name, dob))

    assert result.status is VerificationStatus.PATIENT_NOT_FOUND and result.detail is detail
    assert result.transfer_reason == "PATIENT_NOT_FOUND" and result.patient_id is None


def test_verify_inbound_two_candidates_one_match_picks_the_matching_one_not_the_first() -> None:
    fake = FakeClinicAPI()
    # Cùng số điện thoại với pt_3391 (đã seed), seed thêm người khớp tên/DOB khác, đứng TRƯỚC
    fake.patients.clear()
    fake.seed_patient(
        {
            "patient_id": "pt_first",
            "phone": "0912345600",
            "verify": {"full_name": "Trần Văn B", "dob": "1980-01-01"},
        }
    )
    fake.seed_patient(
        {
            "patient_id": "pt_second",
            "phone": "0912345600",
            "verify": {"full_name": "Nguyễn Văn A", "dob": "1978-03-14"},
        }
    )
    ctx = _inbound("0912345600")
    verifier, _ = _prepared(fake, ctx)
    assert [ref["patient_id"] for ref in ctx.identity_reference] == ["pt_first", "pt_second"]

    result = verifier.verify(_claim(ctx))

    assert result.status is VerificationStatus.VERIFIED and result.patient_id == "pt_second"
    assert result.candidates == 2


def test_verify_inbound_two_full_matches_is_ambiguous_never_auto_picks() -> None:
    fake = FakeClinicAPI()
    fake.seed_patient(
        {
            "patient_id": "pt_twin",
            "phone": "0912345600",
            "verify": {"full_name": "Nguyễn Văn A", "dob": "1978-03-14"},
        }
    )
    ctx = _inbound("0912345600")
    verifier, _ = _prepared(fake, ctx)

    result = verifier.verify(_claim(ctx))

    assert result.status is VerificationStatus.PATIENT_NOT_FOUND
    assert result.detail is MatchDetail.AMBIGUOUS and result.patient_id is None
    assert result.candidates == 2
    assert result.transfer_reason == "PATIENT_NOT_FOUND"


def test_verify_inbound_unverifiable_candidate_is_skipped() -> None:
    fake = FakeClinicAPI()
    fake.seed_patient({"patient_id": "pt_null", "phone": "0912345600", "verify": None})
    ctx = _inbound("0912345600")
    verifier, _ = _prepared(fake, ctx)

    result = verifier.verify(_claim(ctx))

    assert result.status is VerificationStatus.VERIFIED and result.patient_id == "pt_3391"


def test_verify_inbound_without_candidates_is_patient_not_found() -> None:
    fake = FakeClinicAPI()
    ctx = _inbound("0999999999")
    verifier, calls_after_prepare = _prepared(fake, ctx)

    result = verifier.verify(_claim(ctx))

    assert result.status is VerificationStatus.PATIENT_NOT_FOUND
    assert result.detail is MatchDetail.NO_REFERENCE
    assert len(fake.calls) == calls_after_prepare


def test_verify_requires_prepare_and_both_claims() -> None:
    fake = FakeClinicAPI()
    verifier = _verifier(fake)
    with pytest.raises(ValueError):
        verifier.verify(_claim(_outbound()))  # identity_lookup PENDING
    ctx = _outbound()
    verifier.prepare(ctx)
    ctx.claimed_name = NAME
    with pytest.raises(ValueError):
        verifier.verify(ctx)  # thiếu DOB


def test_verify_works_after_context_roundtrip() -> None:
    """Pha 2 chạy trên worker khác / sau restart: chỉ cần ctx đã lưu, không cần mock."""
    fake = FakeClinicAPI()
    ctx = _outbound()
    _verifier(fake).prepare(ctx)
    restored = CallContext.from_dict(ctx.to_dict())
    assert (
        restored.identity_lookup == "LOADED"
        and restored.identity_reference == ctx.identity_reference
    )

    unavailable = FakeClinicAPI()
    unavailable.fail_next("get_appointment", clinic_error(503, "UPSTREAM"))
    result = _verifier(unavailable).verify(_claim(restored))

    assert result.status is VerificationStatus.VERIFIED
    assert unavailable.calls == []


def test_verify_inbound_unaccented_name_matching_two_records_is_ambiguous() -> None:
    # Tên không dấu khớp cả "Lê Văn Hà" lẫn "Lê Văn Hạ" cùng ngày sinh: không tự chọn hồ sơ
    fake = FakeClinicAPI()
    for patient_id, full_name in (("pt_ha", "Lê Văn Hà"), ("pt_ha_nang", "Lê Văn Hạ")):
        fake.seed_patient(
            {
                "patient_id": patient_id,
                "phone": "0912345611",
                "verify": {"full_name": full_name, "dob": "1978-03-14"},
            }
        )
    ctx = _inbound("0912345611")
    verifier, _ = _prepared(fake, ctx)

    assert verifier.verify(_claim(ctx, "le van ha")).detail is MatchDetail.AMBIGUOUS
    # Có dấu thì vẫn phân biệt được hai hồ sơ
    assert verifier.verify(_claim(ctx, "Lê Văn Hạ")).patient_id == "pt_ha_nang"
