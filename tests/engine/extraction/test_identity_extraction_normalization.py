"""Specification audit for identity extraction, normalization, and verifier hand-off.

The cases in this module intentionally mirror TC_IEN_01..TC_IEN_58.  Assertions come
from the audit specification and the documented product contract, not from observed
implementation output.
"""

from datetime import date, datetime
from typing import Any, cast

import pytest

from callbot.engine.dialogue.manager import DialogueManager
from callbot.engine.extraction import InformationExtractor, QuestionId, TurnContext
from callbot.engine.extraction.schema import INVALID, VN_TZ
from callbot.engine.session.context import CallContext
from callbot.engine.types import CallStart
from callbot.engine.verification.identity import (
    LookupStatus,
    PrepareResult,
    VerificationResult,
    VerificationStatus,
    matches,
)
from callbot.engine.verification.names import normalize_name

NOW = datetime(2026, 9, 18, 9, 0, tzinfo=VN_TZ)
CANONICAL_NAME = "Nguyễn Văn A"
CANONICAL_DOB = date(1978, 3, 14)
VERIFY_RECORD = {"full_name": CANONICAL_NAME, "dob": CANONICAL_DOB.isoformat()}


def _turn(question: QuestionId) -> TurnContext:
    return TurnContext(
        turn=1,
        question_id=question,
        direction="inbound",
        now=NOW,
    )


def _extract_name(transcript: str) -> str | None:
    return InformationExtractor().extract(_turn(QuestionId.ASK_NAME), transcript).full_name.value


def _extract_dob(transcript: str) -> date | str | None:
    return InformationExtractor().extract(_turn(QuestionId.ASK_DOB), transcript).dob.value


@pytest.mark.parametrize(
    "transcript, expected",
    [
        ("Nguyễn Văn A", "nguyễn văn a"),
        ("Tôi là Nguyễn Văn A", "nguyễn văn a"),
        ("Tên tôi là Nguyễn Văn A", "nguyễn văn a"),
        ("Dạ, tôi là Nguyễn Văn A", "nguyễn văn a"),
        ("Nguyễn Văn A ạ", "nguyễn văn a"),
        ("Dạ tên tôi là Nguyễn Văn A ạ", "nguyễn văn a"),
        ("Tôi không nhớ", None),
        ("Tôi không muốn nói tên", None),
    ],
    ids=[f"TC_IEN_{number:02d}" for number in range(1, 9)],
)
def test_name_extraction(transcript: str, expected: str | None) -> None:
    assert _extract_name(transcript) == expected


@pytest.mark.parametrize(
    "transcript, should_match",
    [
        ("nguyễn văn a", True),
        ("NGUYỄN VĂN A", True),
        ("  Nguyễn Văn A  ", True),
        ("Nguyễn   Văn    A", True),
        ("Nguyễn Văn A.", True),
        ("Nguyen Van A", False),
        ("NGUYEN van a", False),
        ("Nguyễn Văn B", False),
    ],
    ids=[f"TC_IEN_{number:02d}" for number in range(9, 17)],
)
def test_name_normalization(transcript: str, should_match: bool) -> None:
    claimed_name = _extract_name(transcript)
    assert claimed_name is not None
    assert matches(claimed_name, CANONICAL_DOB, VERIFY_RECORD) is should_match


@pytest.mark.parametrize(
    "transcript",
    [
        "14 tháng 3 năm 1978",
        "Tôi sinh ngày 14 tháng 3 năm 1978",
        "Ngày sinh của tôi là 14 tháng 3 năm 1978",
        "Dạ, ngày 14 tháng 3 năm 1978 ạ",
        "14/03/1978",
        "Tôi sinh ngày 14/03/1978",
    ],
    ids=[f"TC_IEN_{number:02d}" for number in range(17, 23)],
)
def test_dob_extraction(transcript: str) -> None:
    assert _extract_dob(transcript) == CANONICAL_DOB


@pytest.mark.parametrize(
    "transcript",
    [
        "14/03/1978",
        "14-03-1978",
        "14/3/1978",
        "14 tháng 3 năm 1978",
        "ngày mười bốn tháng ba năm 1978",
        "ngày mười bốn tháng ba năm một nghìn chín trăm bảy mươi tám",
    ],
    ids=[f"TC_IEN_{number:02d}" for number in range(23, 29)],
)
def test_dob_normalization(transcript: str) -> None:
    assert _extract_dob(transcript) == CANONICAL_DOB


@pytest.mark.parametrize(
    "transcript, expected",
    [
        ("31/02/1978", None),
        ("32/03/1978", None),
        ("00/03/1978", None),
        ("14/13/1978", None),
        ("14/00/1978", None),
        ("ngày 31 tháng 2 năm 1978", None),
        ("29/02/1980", date(1980, 2, 29)),
        ("29/02/1979", None),
    ],
    ids=[f"TC_IEN_{number:02d}" for number in range(29, 37)],
)
def test_dob_validation(transcript: str, expected: date | None) -> None:
    actual = _extract_dob(transcript)
    if expected is None:
        assert not isinstance(actual, date), f"invalid input produced matchable DOB {actual!r}"
    else:
        assert actual == expected


@pytest.mark.parametrize(
    "transcript",
    [
        "Tôi sinh năm 1978",
        "Ngày 14 tháng 3",
        "Tháng 3 năm 1978",
        "Tôi không nhớ ngày sinh",
        "Tôi không rõ",
        "",
    ],
    ids=[f"TC_IEN_{number:02d}" for number in range(37, 43)],
)
def test_missing_or_incomplete_dob(transcript: str) -> None:
    assert not isinstance(_extract_dob(transcript), date)


def test_TC_IEN_43_ambiguous_numeric_dob_uses_product_day_month_order() -> None:
    # The product design documents numeric DOB examples as day/month/year.
    assert _extract_dob("03/04/1978") == date(1978, 4, 3)


def test_TC_IEN_44_explicit_self_correction_uses_final_dob() -> None:
    assert _extract_dob("14 tháng 3... à không, 15 tháng 3 năm 1978") == date(1978, 3, 15)


def test_TC_IEN_45_two_dobs_without_correction_are_not_selected() -> None:
    actual = _extract_dob("14 tháng 3 năm 1978 hoặc 15 tháng 3 năm 1978")
    assert not isinstance(actual, date)


@pytest.mark.parametrize(
    "transcript",
    [
        "Hình như là 14/03/1978",
        "Chắc là ngày 14 tháng 3 năm 1978",
        "14/03/1978 thì phải",
        "Tôi không nhớ rõ, 14 tháng 3 năm 1978",
    ],
)
def test_TC_IEN_46_uncertain_dob_is_asked_again_not_verified(transcript: str) -> None:
    # Chính sách đã chốt: người gọi tự báo là không chắc thì hỏi lại, không đưa vào Verifier.
    # Không có ngưỡng tin cậy nào ở đây — cụm phân vân là tín hiệu duy nhất, và nó không đủ.
    assert _extract_dob(transcript) == INVALID


def test_TC_IEN_47_extracts_the_callers_self_identified_name() -> None:
    assert _extract_name("Tôi là Nguyễn Văn A, còn em tôi là Nguyễn Văn B") == "nguyễn văn a"


def test_TC_IEN_48_does_not_choose_between_uncertain_names() -> None:
    transcript = "Nguyễn Văn A hay Nguyễn Văn B thì tôi không nhớ hồ sơ ghi tên nào"
    assert _extract_name(transcript) is None


@pytest.mark.parametrize(
    "question, transcript, field",
    [
        (QuestionId.ASK_NAME, "14/03/1978", "full_name"),
        (QuestionId.ASK_DOB, "Nguyễn Văn A", "dob"),
        (QuestionId.ASK_NAME, "Tôi muốn hủy lịch", "full_name"),
        (QuestionId.ASK_DOB, "Tôi không đến khám được", "dob"),
    ],
    ids=[f"TC_IEN_{number:02d}" for number in range(49, 53)],
)
def test_context_sensitive_identity_extraction(
    question: QuestionId, transcript: str, field: str
) -> None:
    result = InformationExtractor().extract(_turn(question), transcript)
    assert getattr(result, field).found is False


class _NoopGateway:
    def transfer(self, ctx: CallContext, reason: str) -> None:
        return None


class _RecordingVerifier:
    def __init__(self) -> None:
        self.calls: list[tuple[str, date]] = []

    def prepare(self, ctx: CallContext) -> PrepareResult:
        return PrepareResult(LookupStatus.LOADED)

    def compare_name(self, ctx, value):
        # Boundary spy accepts a PRESENT name; real matching is tested separately.
        from callbot.engine.verification.names import NameMatch

        return NameMatch.MATCH

    def compare_dob(self, ctx, value):
        return True

    def verify(self, ctx: CallContext) -> VerificationResult:
        assert ctx.claimed_name is not None and ctx.claimed_dob is not None
        self.calls.append((ctx.claimed_name, ctx.claimed_dob))
        # A mismatch ends the inbound test flow without requiring a clinic gateway.
        return VerificationResult(VerificationStatus.MISMATCH)


def _verification_boundary(
    name_transcript: str | None, dob_transcript: str | None
) -> tuple[CallContext, _RecordingVerifier]:
    context = CallContext(
        call=CallStart(
            call_id=f"audit-{name_transcript!r}-{dob_transcript!r}",
            direction="inbound",
            caller_number="0900000000",
        ),
        opened_at=NOW,
    )
    verifier = _RecordingVerifier()
    manager = DialogueManager(cast(Any, _NoopGateway()), cast(Any, verifier))
    extractor = InformationExtractor()
    manager.opening(context)

    if name_transcript is not None:
        name_result = extractor.extract(_turn(QuestionId.ASK_NAME), name_transcript)
        manager.respond(context, name_result, NOW)
    if dob_transcript is not None and context.identity_step == "ASK_DOB":
        dob_result = extractor.extract(_turn(QuestionId.ASK_DOB), dob_transcript)
        manager.respond(context, dob_result, NOW)
    return context, verifier


def test_TC_IEN_53_verifier_receives_extracted_name_not_utterance() -> None:
    _, verifier = _verification_boundary("Dạ, tôi tên là Nguyễn Văn A ạ", "14/03/1978")
    assert verifier.calls == [("nguyễn văn a", CANONICAL_DOB)]


def test_TC_IEN_54_verifier_receives_canonical_dob() -> None:
    _, verifier = _verification_boundary(CANONICAL_NAME, "Tôi sinh ngày 14 tháng 3 năm 1978")
    assert verifier.calls == [("nguyễn văn a", CANONICAL_DOB)]


def test_TC_IEN_55_invalid_dob_does_not_reach_verifier_as_valid() -> None:
    context, verifier = _verification_boundary(CANONICAL_NAME, "31 tháng 2 năm 1978")
    assert verifier.calls == []
    assert context.claimed_dob is None


def test_TC_IEN_56_incomplete_dob_does_not_reach_verifier() -> None:
    context, verifier = _verification_boundary(CANONICAL_NAME, "Tôi sinh năm 1978")
    assert verifier.calls == []
    assert context.claimed_dob is None


def test_TC_IEN_57_missing_name_does_not_reach_verifier() -> None:
    context, verifier = _verification_boundary("Tôi không nhớ tên hồ sơ", "14/03/1978")
    assert verifier.calls == []
    assert context.claimed_name is None


def test_TC_IEN_58_different_name_stays_semantically_distinct_for_verifier() -> None:
    _, verifier = _verification_boundary("Nguyễn Văn B", "14/03/1978")
    assert verifier.calls == [("nguyễn văn b", CANONICAL_DOB)]
    assert normalize_name(verifier.calls[0][0]) != normalize_name(CANONICAL_NAME)
