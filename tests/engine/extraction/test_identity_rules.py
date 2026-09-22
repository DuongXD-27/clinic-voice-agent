"""Luật trích xuất danh tính: phủ định, tự sửa, phân vân, câu gộp, và ranh giới với NER.

Mỗi ca ở đây là một câu người gọi thật sự nói được. Kỳ vọng lấy từ hợp đồng sản phẩm:
sai một tên hay một ngày thì Verifier chuyển máy ngay, còn `INVALID` / `None` chỉ tốn một
lượt hỏi lại — nên chỗ nào còn hai cách hiểu thì hỏi lại, không đoán.
"""

from datetime import date, datetime
from typing import Any, Optional, cast

import pytest

from callbot.engine.dialogue.manager import DialogueManager
from callbot.engine.extraction import (
    Field,
    InformationExtractor,
    Intent,
    Provenance,
    QuestionId,
    TurnContext,
)
from callbot.engine.extraction.dob import extract_dob
from callbot.engine.extraction.full_name import extract_full_name
from callbot.engine.extraction.schema import INVALID, VN_TZ
from callbot.engine.extraction.text import clean
from callbot.engine.session.context import CallContext
from callbot.engine.types import CallStart
from callbot.engine.verification.identity import (
    LookupStatus,
    PrepareResult,
    VerificationResult,
    VerificationStatus,
)

TODAY = date(2026, 9, 21)
NOW = datetime(2026, 9, 21, 9, 0, tzinfo=VN_TZ)
DOB = date(1978, 3, 14)
extractor = InformationExtractor()


def ctx(question: QuestionId, direction="inbound") -> TurnContext:
    return TurnContext(turn=1, question_id=question, direction=direction, now=NOW)


def name_of(transcript: str) -> Optional[str]:
    return extractor.extract(ctx(QuestionId.ASK_NAME), transcript).full_name.value


class FakeNER:
    """Tuyến sau cố trả về một tên có thật trong transcript, kèm số lần bị gọi."""

    def __init__(self, name: Optional[str] = None) -> None:
        self._name = name
        self.calls = 0

    def full_name(self, transcript: str) -> Optional[Field[str]]:
        self.calls += 1
        if self._name is None:
            return None
        return Field(self._name, Provenance.FALLBACK, span=self._name)

    def intent(self, transcript: str, allowed) -> None:
        return None

    def agreement(self, transcript: str, question_id: QuestionId) -> None:
        return None


# --- Ngày sinh: phủ định và tự sửa ------------------------------------------------


@pytest.mark.parametrize(
    "transcript", ["hello em", "hi em", "Hello, chị ạ!", "dạ hi anh", "alo em", "chào em"]
)
def test_greeting_is_not_a_name_even_with_ner_enabled(transcript: str) -> None:
    ner = FakeNER(clean(transcript))
    result = InformationExtractor(fallback=ner, name_fallback=True).extract(
        ctx(QuestionId.ASK_NAME), transcript
    )
    assert not result.full_name.found
    assert ner.calls == 0


@pytest.mark.parametrize(
    "transcript",
    [
        "không phải 14 tháng 3 năm 1978",
        "không phải ngày 14/3/1978",
        "đâu phải 14 tháng 3 năm 1978",
        "khong phai 14 thang 3 nam 1978",
        # Phần sửa thiếu ngày / tháng -> không ghép với phần đã bị bác bỏ
        "không phải 14/3/1978 mà là 1979",
        "không phải 14 tháng 3 năm 1978 mà là tháng 4",
    ],
)
def test_negated_dob_is_never_accepted(transcript: str) -> None:
    assert extract_dob(transcript, TODAY).value == INVALID


@pytest.mark.parametrize(
    "transcript, expected",
    [
        ("không phải 14/3/1978 mà là 15/3/1978", date(1978, 3, 15)),
        ("không phải 14 tháng 3 năm 1978 mà là 15 tháng 3 năm 1978", date(1978, 3, 15)),
        ("14/3/1978, à nhầm, 15/3/1978", date(1978, 3, 15)),
        ("14 tháng 3 năm 1978, à nhầm 15 tháng 3 năm 1978", date(1978, 3, 15)),
        ("ngày 14 xin lỗi ngày 15 tháng 3 năm 1978", date(1978, 3, 15)),
    ],
)
def test_self_correction_takes_the_last_complete_date(transcript: str, expected: date) -> None:
    assert extract_dob(transcript, TODAY).value == expected


# --- Ngày sinh: mơ hồ và không chắc chắn ------------------------------------------


@pytest.mark.parametrize(
    "transcript",
    [
        "14 hay 15 tháng 3 năm 1978",
        "ngày 14 hoặc 15 tháng 3 năm 1978",
        "14 tháng 3 năm 1978 hoặc 1979",
        "14 tháng 3 năm 1978 hay là 1979",
        "14/3/1978 hoặc 15/3/1979",
    ],
)
def test_two_competing_dates_without_a_correction_are_not_chosen(transcript: str) -> None:
    assert extract_dob(transcript, TODAY).value == INVALID


@pytest.mark.parametrize(
    "transcript",
    [
        "hình như là 14/3/1978",
        "có lẽ 14 tháng 3 năm 1978",
        "chắc là 14/3/1978",
        "tôi không chắc, 14/3/1978",
        "không nhớ rõ, ngày 14 tháng 3 năm 1978",
        "14/3/1978 thì phải",
        "hinh nhu la 14/3/1978",
    ],
)
def test_uncertain_dob_is_asked_again(transcript: str) -> None:
    assert extract_dob(transcript, TODAY).value == INVALID


def test_uncertainty_alone_is_not_a_date_answer() -> None:
    # Không có ngày nào để hỏi lại: đây là "không cung cấp được", không phải ngày sai
    assert extract_dob("tôi không nhớ rõ ngày sinh", TODAY).found is False
    assert extractor.extract(ctx(QuestionId.ASK_DOB), "tôi không nhớ rõ").intent.value is (
        Intent.CANNOT_PROVIDE
    )


def test_hesitation_filler_is_not_uncertainty() -> None:
    # "à ừ" chỉ là lời đệm kéo dài lượt, không phải người gọi tự nhận là không chắc
    assert extract_dob("à ừ thì ngày 14 tháng 3 năm 1978", TODAY).value == DOB


# --- Dấu pha trộn ------------------------------------------------------------------


@pytest.mark.parametrize(
    "transcript",
    [
        "ngày 14 thang 3 nam 1978",
        "ngay 14 tháng 3 năm 1978",
        "Dạ ngay 14 thang 3 nam 1978 ạ",
        "toi sinh ngay muoi bon thang ba nam 1978",
        "Tôi sinh ngay 14 thang 3 nam 1978",
    ],
)
def test_partly_unaccented_dob_is_restored(transcript: str) -> None:
    result = extract_dob(transcript, TODAY)
    assert result.value == DOB
    assert result.provenance is Provenance.NORMALIZED


def test_partly_unaccented_name_loses_the_prefix_but_keeps_a_single_letter() -> None:
    assert extract_full_name("Dạ toi la Nguyen Van A").value == "nguyen van a"
    assert extract_full_name("Da toi la Nguyen Van A ạ").value == "nguyen van a"


@pytest.mark.parametrize(
    "transcript", ["14/3/1978", "Tôi sinh ngày 14/03/1978", "ngay 14 thang 3 nam 1978"]
)
def test_dob_span_is_a_real_slice_of_the_normalized_transcript(transcript: str) -> None:
    # Không được báo cáo đoạn bộ trích xuất tự dựng ("ngày 14 tháng 3 năm 1978" cho "14/3/1978")
    span = extract_dob(transcript, TODAY).span
    assert span is not None and span in clean(transcript)


# --- Câu nghiệp vụ / lời đệm bị nhầm thành tên ------------------------------------


@pytest.mark.parametrize(
    "transcript, intent",
    [
        ("hủy lịch đi", Intent.CANCEL),
        ("tôi muốn đổi lịch hẹn", Intent.RESCHEDULE),
        ("cho tôi đặt lịch khám", Intent.BOOK),
        ("bảo hiểm y tế có chi trả không", Intent.OUT_OF_SCOPE),
    ],
)
def test_business_utterance_is_not_a_name_and_keeps_its_intent(
    transcript: str, intent: Intent
) -> None:
    result = extractor.extract(ctx(QuestionId.ASK_NAME), transcript)
    assert result.full_name.found is False
    assert result.intent.value is intent


@pytest.mark.parametrize("transcript", ["ờ để xem", "ừ để tôi xem", "chờ chút nhé"])
def test_filler_utterance_is_not_a_name(transcript: str) -> None:
    assert name_of(transcript) is None


@pytest.mark.parametrize(
    "transcript, expected",
    [
        # Một từ trùng từ khoá không đủ để loại cả câu
        ("nguyen thanh toan", "nguyen thanh toan"),
        ("Nguyễn Thanh Toàn", "nguyễn thanh toàn"),
        ("Trần Văn Lịch", "trần văn lịch"),
        ("Lê Bảo Hiền", "lê bảo hiền"),
    ],
)
def test_a_name_sharing_a_keyword_is_still_a_name(transcript: str, expected: str) -> None:
    assert name_of(transcript) == expected


# --- Tên dễ bị cắt hoặc loại nhầm --------------------------------------------------


@pytest.mark.parametrize(
    "transcript, expected",
    [
        ("Nguyễn Văn Cần", "nguyễn văn cần"),
        ("Nguyễn Thị Ái", "nguyễn thị ái"),
        ("Nguyễn Thị Anh", "nguyễn thị anh"),
        ("Lê Văn Thôi", "lê văn thôi"),
        ("Trần Văn Được", "trần văn được"),
        ("Nguyễn Văn Sinh", "nguyễn văn sinh"),
        ("Trần Văn Năm", "trần văn năm"),
        ("Nguyễn Văn Tám", "nguyễn văn tám"),
        ("Nguyễn Văn A", "nguyễn văn a"),
        ("nguyen thi ai", "nguyen thi ai"),
    ],
)
def test_names_that_look_like_keywords_are_protected(transcript: str, expected: str) -> None:
    assert name_of(transcript) == expected


@pytest.mark.parametrize(
    "transcript, expected",
    [
        ("Nguyễn Văn A, à nhầm, Nguyễn Văn B", "nguyễn văn b"),
        ("Tôi là Nguyễn Văn A, à không tôi là Nguyễn Văn B", "nguyễn văn b"),
        ("không phải Nguyễn Văn A mà là Nguyễn Văn B", "nguyễn văn b"),
    ],
)
def test_name_self_correction_takes_the_last_claim(transcript: str, expected: str) -> None:
    assert name_of(transcript) == expected


@pytest.mark.parametrize(
    "transcript",
    [
        "không phải Nguyễn Văn A",
        "tôi không phải Nguyễn Văn A",
        "Nguyễn Văn A hay Nguyễn Văn B",
        "Tôi là Nguyễn Văn A hoặc Nguyễn Văn B",
        "chắc là Nguyễn Văn A",
        "hình như tôi là Nguyễn Văn A",
        "mẹ tôi là Nguyễn Thị Hoa",
        "tôi gọi hộ Nguyễn Thị Hoa",
    ],
)
def test_denied_uncertain_or_borrowed_names_are_not_claimed(transcript: str) -> None:
    assert name_of(transcript) is None


@pytest.mark.parametrize(
    "transcript",
    [
        "Nguyễn Văn A, tôi không nhớ rõ ngày sinh",
        "Nguyễn Văn A, ngày sinh thì tôi không chắc",
        "Tôi là Nguyễn Văn A, hình như sinh năm 1978",
    ],
)
def test_uncertainty_about_the_dob_does_not_lose_a_clear_name(transcript: str) -> None:
    # Phạm vi gắn với đúng trường: người gọi phân vân về ngày sinh, không phải về tên
    result = extractor.extract(ctx(QuestionId.ASK_NAME), transcript)
    assert result.full_name.value == "nguyễn văn a"
    assert not isinstance(result.dob.value, date)


@pytest.mark.parametrize(
    "transcript, expected",
    [
        # "Hay" là âm trong tên, không phải từ nối giữa hai tên đang phân vân
        ("Nguyễn Thị Hay", "nguyễn thị hay"),
        ("Nguyễn Hay Anh", "nguyễn hay anh"),
    ],
)
def test_a_name_ending_in_an_alternation_word_is_still_a_name(
    transcript: str, expected: str
) -> None:
    assert name_of(transcript) == expected


@pytest.mark.parametrize(
    "transcript",
    [
        # Dạng "X tên ..." không có chữ "là" — trước đây vừa bỏ sót, vừa để nguyên cả cụm
        # tự giới thiệu đi vào Verifier ("em tên nguyễn văn a")
        "Tôi tên Nguyễn Văn A",
        "Tôi tên là Nguyễn Văn A",
        "Tên tôi Nguyễn Văn A",
        "Tên tôi là Nguyễn Văn A",
        "Em tên Nguyễn Văn A",
        "Cháu tên Nguyễn Văn A",
        "Con tên Nguyễn Văn A",
        "Mình tên Nguyễn Văn A",
        "Anh tên Nguyễn Văn A",
        "Dạ tôi tên Nguyễn Văn A ạ",
        "Họ tên tôi là Nguyễn Văn A",
    ],
)
def test_every_self_introduction_form_is_stripped(transcript: str) -> None:
    assert name_of(transcript) == "nguyễn văn a"


def test_unaccented_self_introduction_without_la_is_stripped() -> None:
    assert name_of("toi ten nguyen van a") == "nguyen van a"


def test_self_introduction_wins_over_a_later_relative_clause() -> None:
    # "tôi là" nằm bên trong "em tôi là" ở cuối câu không được che lời tự giới thiệu ở đầu
    assert name_of("Tôi tên Nguyễn Văn A, còn em tôi là Nguyễn Văn B") == "nguyễn văn a"


@pytest.mark.parametrize(
    "transcript",
    [
        "Em tôi là Nguyễn Văn A, còn chị tôi là Nguyễn Thị B",
        "mẹ tôi là Nguyễn Thị Hoa",
        "bà tôi là Nguyễn Thị Hoa",
        "ba tôi là Nguyễn Văn A",
    ],
)
def test_a_relative_only_claim_is_still_refused(transcript: str) -> None:
    assert name_of(transcript) is None


# --- Câu gộp tên + ngày sinh -------------------------------------------------------


@pytest.mark.parametrize(
    "transcript, expected_name, expected_dob",
    [
        ("Nguyễn Văn A, sinh ngày 14/3/1978", "nguyễn văn a", DOB),
        ("Tôi là Nguyễn Văn A sinh ngày 14/3/1978", "nguyễn văn a", DOB),
        ("14/3/1978, tôi là Nguyễn Văn A", "nguyễn văn a", DOB),
        ("Tôi tên là Nguyễn Văn A, ngày sinh 14 tháng 3 năm 1978", "nguyễn văn a", DOB),
        # Phạm vi phủ định gắn với ngày sinh, không làm mất tên
        (
            "Tôi là Nguyễn Văn A, không phải 14/3/1978 mà là 15/3/1978",
            "nguyễn văn a",
            date(1978, 3, 15),
        ),
        # Phạm vi tự sửa gắn với tên, không làm mất ngày sinh
        ("Nguyễn Văn A, à nhầm Nguyễn Văn B, sinh ngày 14/3/1978", "nguyễn văn b", DOB),
    ],
)
def test_combined_answer_keeps_both_fields(
    transcript: str, expected_name: str, expected_dob: date
) -> None:
    result = extractor.extract(ctx(QuestionId.ASK_NAME), transcript)
    assert result.full_name.value == expected_name
    assert result.dob.value == expected_dob


@pytest.mark.parametrize(
    "transcript",
    [
        "Tôi là Nguyễn Văn Sinh ngày 14/3/1978",
        "Nguyễn Văn Sinh ngày 14/3/1978",
        "Nguyễn Văn Sinh 14/3/1978",
        "Lê Na sinh ngày 14/3/1978",
        "Nguyễn Văn Tám mười bốn tháng ba năm 1978",
    ],
)
def test_uncertain_name_boundary_asks_again_and_never_truncates(transcript: str) -> None:
    result = extractor.extract(ctx(QuestionId.ASK_NAME), transcript)
    assert result.full_name.found is False
    assert result.full_name.value != "nguyễn văn"
    assert result.dob.found  # phần chắc chắn vẫn được giữ


def test_combined_answer_keeps_the_certain_half_when_the_date_is_unusable() -> None:
    result = extractor.extract(
        ctx(QuestionId.ASK_NAME), "Tôi là Nguyễn Văn A, sinh ngày 31/02/1978"
    )
    assert result.full_name.value == "nguyễn văn a"
    assert result.dob.value == INVALID


def test_a_stray_digit_is_not_a_name_boundary() -> None:
    result = extractor.extract(ctx(QuestionId.ASK_NAME), "bảo hiểm có chi trả 80% không")
    assert result.full_name.found is False
    assert result.intent.value is Intent.OUT_OF_SCOPE


def test_two_people_in_one_answer_are_not_mixed() -> None:
    # Ngày sinh nói kèm tên người khác vẫn thuộc về người gọi đang tự giới thiệu ở vế đầu
    result = extractor.extract(
        ctx(QuestionId.ASK_NAME), "Tôi là Nguyễn Văn A, còn em tôi là Nguyễn Văn B sinh 14/3/1978"
    )
    assert result.full_name.value == "nguyễn văn a"


# --- Tuyến sau NER -----------------------------------------------------------------


@pytest.mark.parametrize(
    "transcript, name",
    [
        ("không phải Nguyễn Văn A", "nguyễn văn a"),
        ("Nguyễn Văn A hay Nguyễn Văn B", "nguyễn văn a"),
        ("chắc là Nguyễn Văn A", "nguyễn văn a"),
        ("hủy lịch đi", "hủy lịch"),
        ("mẹ tôi là Nguyễn Thị Hoa", "nguyễn thị hoa"),
    ],
)
def test_ner_cannot_overturn_a_decided_rejection(transcript: str, name: str) -> None:
    ner = FakeNER(name)
    result = InformationExtractor(fallback=ner, name_fallback=True).extract(
        ctx(QuestionId.ASK_NAME), transcript
    )
    assert result.full_name.found is False
    assert ner.calls == 0, "luật đã quyết định, không được hỏi mô hình"


def test_ner_is_asked_only_when_the_rules_do_not_understand() -> None:
    ner = FakeNER("nguyễn văn a")
    result = InformationExtractor(fallback=ner, name_fallback=True).extract(
        ctx(QuestionId.ASK_NAME), "à ừ thì là nguyễn văn a nhé em"
    )
    assert result.full_name.value == "nguyễn văn a"
    assert result.full_name.provenance is Provenance.FALLBACK
    assert ner.calls == 1


def test_ner_name_must_lie_inside_the_allowed_name_zone() -> None:
    # Câu gộp: vùng tên chỉ là phần trước ngày sinh — mô hình không được lấy chữ từ phần ngày
    ner = FakeNER("mười bốn tháng ba")
    result = InformationExtractor(fallback=ner, name_fallback=True).extract(
        ctx(QuestionId.ASK_NAME), "à ừ thì là em nhé, sinh ngày mười bốn tháng ba năm 1978"
    )
    assert result.full_name.found is False


def test_ner_failure_still_asks_again() -> None:
    ner = FakeNER(None)  # lỗi / timeout / không có tên
    result = InformationExtractor(fallback=ner, name_fallback=True).extract(
        ctx(QuestionId.ASK_NAME), "à ừ thì là nguyễn văn a nhé em"
    )
    assert result.full_name.found is False
    assert ner.calls == 1


# --- Tích hợp: ranh giới với Verifier ----------------------------------------------


class _NoopGateway:
    def transfer(self, context: CallContext, reason: str) -> None:
        return None


class _RecordingVerifier:
    """Ghi lại đúng cặp tên + ngày sinh mà Dialogue đưa sang xác minh."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, date]] = []

    def prepare(self, context: CallContext) -> PrepareResult:
        return PrepareResult(LookupStatus.LOADED)

    def verify(self, context: CallContext) -> VerificationResult:
        assert context.claimed_name is not None and context.claimed_dob is not None
        self.calls.append((context.claimed_name, context.claimed_dob))
        return VerificationResult(VerificationStatus.MISMATCH)


def _identity_turns(*transcripts: str) -> tuple[CallContext, _RecordingVerifier]:
    context = CallContext(
        call=CallStart(
            call_id=f"rules-{transcripts}", direction="inbound", caller_number="0900000000"
        ),
        opened_at=NOW,
    )
    verifier = _RecordingVerifier()
    manager = DialogueManager(cast(Any, _NoopGateway()), cast(Any, verifier))
    manager.opening(context)
    for transcript in transcripts:
        question = QuestionId(context.identity_step)
        manager.respond(context, extractor.extract(ctx(question), transcript), NOW)
    return context, verifier


@pytest.mark.parametrize(
    "name_turn, dob_turn",
    [
        ("Nguyễn Văn A", "hình như là 14/03/1978"),
        ("Nguyễn Văn A", "14 hay 15 tháng 3 năm 1978"),
        ("Nguyễn Văn A", "không phải 14/03/1978"),
        ("không phải Nguyễn Văn A", "14/03/1978"),
        ("Nguyễn Văn A hay Nguyễn Văn B", "14/03/1978"),
    ],
)
def test_uncertain_or_denied_identity_never_reaches_the_verifier(
    name_turn: str, dob_turn: str
) -> None:
    context, verifier = _identity_turns(name_turn, dob_turn)
    assert verifier.calls == []
    assert context.identity_step != "VERIFIED"


def test_a_certain_pair_reaches_the_verifier_exactly_once() -> None:
    _, verifier = _identity_turns("Dạ tôi là Nguyễn Văn A ạ", "14/03/1978")
    assert verifier.calls == [("nguyễn văn a", DOB)]


def test_a_combined_answer_reaches_the_verifier_in_one_turn() -> None:
    _, verifier = _identity_turns("Tôi là Nguyễn Văn A, sinh ngày 14/3/1978")
    assert verifier.calls == [("nguyễn văn a", DOB)]


def test_a_corrected_combined_answer_hands_over_the_corrected_halves() -> None:
    _, verifier = _identity_turns("Nguyễn Văn A, à nhầm Nguyễn Văn B, sinh ngày 14/3/1978")
    assert verifier.calls == [("nguyễn văn b", DOB)]
