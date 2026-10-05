"""Residual speech must not become a NORMALIZED name or survive failed slot filling."""

from datetime import date

import pytest

from callbot.engine.extraction import (
    Field,
    InformationExtractor,
    Provenance,
    QuestionId,
    SlotFillingResult,
    SlotFillingStatus,
)
from callbot.engine.extraction.full_name import read_full_name
from callbot.engine.extraction.identity import Reason
from tests.engine.extraction.test_extractor import FakeFallback, ctx

SUSPECT_NAMES = [
    "Nguyễn Văn A đúng rồi",
    "Nguyễn Văn A vâng",
    "Nguyễn Văn A chứ",
    "hello em Nguyễn Văn A",
]


@pytest.mark.parametrize("text", SUSPECT_NAMES)
def test_leftover_speech_is_not_a_settled_rule_name(text):
    reading = read_full_name(text)
    assert not reading.field.found
    assert reading.reason is Reason.UNRESOLVED_BOUNDARY
    assert not InformationExtractor().extract(ctx(QuestionId.ASK_NAME), text).full_name.found


@pytest.mark.parametrize("text", SUSPECT_NAMES)
def test_suspect_boundary_routes_to_slot_filling_and_uses_only_the_grounded_name(text):
    fallback = FakeFallback(
        full_name=Field("nguyễn văn a", Provenance.FALLBACK, span="nguyễn văn a")
    )
    result = InformationExtractor(fallback=fallback, name_fallback=True).extract(
        ctx(QuestionId.ASK_NAME), text
    )
    assert fallback.calls == ["full_name"]
    assert result.full_name.value == result.full_name.span == "nguyễn văn a"
    assert result.full_name.provenance is Provenance.FALLBACK


@pytest.mark.parametrize("text", SUSPECT_NAMES)
def test_failed_or_contaminated_fallback_cannot_restore_the_dirty_candidate(text):
    for proposed in (None, Field(text.lower(), Provenance.FALLBACK, span=text)):
        fallback = FakeFallback(full_name=proposed)
        result = InformationExtractor(fallback=fallback, name_fallback=True).extract(
            ctx(QuestionId.ASK_NAME), text
        )
        assert fallback.calls == ["full_name"]
        assert not result.full_name.found


@pytest.mark.parametrize(
    "text",
    ["hú hú", "hú hú em ơi", "em ơi", "tôi nghe đây", "Vinmec à?", "Bên em là bên nào?"],
)
def test_known_contact_signals_never_spend_a_name_request(text):
    fallback = FakeFallback(full_name=Field(text.lower(), Provenance.FALLBACK, span=text))
    result = InformationExtractor(fallback=fallback, name_fallback=True).extract(
        ctx(QuestionId.ASK_NAME), text
    )
    assert not result.full_name.found
    assert fallback.calls == []


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Nguyễn Văn A đây em", "nguyễn văn a"),
        ("Nguyễn Văn A đó em", "nguyễn văn a"),
        ("Nguyễn Văn A ạ em", "nguyễn văn a"),
        ("Nguyễn Văn A nhé em ơi", "nguyễn văn a"),
        ("Nguyễn Văn A cảm ơn em", "nguyễn văn a"),
        ("Nguyễn Văn A nhe em oi", "nguyễn văn a"),
        ("Họ tên của tôi là Nguyễn Văn A", "nguyễn văn a"),
        ("Nguyễn Văn A là tên của tôi", "nguyễn văn a"),
        ("Tên đầy đủ của tôi trên giấy tờ là Nguyễn Văn A", "nguyễn văn a"),
        ("chào em tôi tên Nguyễn Văn A", "nguyễn văn a"),
        ("em ơi tôi là Nguyễn Văn A", "nguyễn văn a"),
        ("hú hú anh tên Nguyễn Văn A", "nguyễn văn a"),
        ("à thì anh tên là Nguyễn Văn A nhé em", "nguyễn văn a"),
        ("Nguyễn Thị Anh", "nguyễn thị anh"),
        ("Nguyễn Văn Em nhé anh", "nguyễn văn em"),
        ("Nguyen Van Chu", "nguyen van chu"),
        ("Nguyễn Văn Hữu", "nguyễn văn hữu"),
        ("Nguyễn Văn An", "nguyễn văn an"),
        ("alo em, tôi là Nguyễn Văn A", "nguyễn văn a"),
        ("hello em, tôi là Nguyễn Văn A", "nguyễn văn a"),
    ],
)
def test_settled_names_do_not_need_a_model(text, expected):
    fallback = FakeFallback()
    result = InformationExtractor(fallback=fallback, name_fallback=True).extract(
        ctx(QuestionId.ASK_NAME), text
    )
    assert result.full_name.value == expected
    assert result.full_name.provenance is Provenance.NORMALIZED
    assert fallback.calls == []


@pytest.mark.parametrize(
    "text", ["alo em, mẹ tôi là Nguyễn Thị Hoa", "hello em, em tôi là Nguyễn Văn A"]
)
def test_removing_a_greeting_clause_does_not_turn_a_relative_into_the_caller(text):
    fallback = FakeFallback()
    result = InformationExtractor(fallback=fallback, name_fallback=True).extract(
        ctx(QuestionId.ASK_NAME), text
    )
    assert not result.full_name.found
    assert fallback.calls == []


def test_provider_exception_reprompts_instead_of_using_the_suspect_name():
    class BrokenFallback(FakeFallback):
        def full_name(self, transcript, **context):
            raise TimeoutError("synthetic provider timeout")

    result = InformationExtractor(fallback=BrokenFallback(), name_fallback=True).extract(
        ctx(QuestionId.ASK_NAME), "Nguyễn Văn A đúng rồi"
    )
    assert not result.full_name.found


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Nguyễn Thị Nha", "nguyễn thị nha"),
        ("Nguyễn Thị Nha nhé em", "nguyễn thị nha"),
        ("Tôi là Nguyễn Thị Nha nhé em", "nguyễn thị nha"),
        ("Lê Nha", "lê nha"),
        ("Nguyễn Văn A em nhé", "nguyễn văn a"),
        ("Nguyễn Văn A em ạ", "nguyễn văn a"),
        ("Nguyễn Văn Em nhé", "nguyễn văn em"),
    ],
)
def test_ambiguous_suffix_must_use_slot_filling_instead_of_a_truncated_rule_name(text, expected):
    reading = read_full_name(text)
    assert reading.reason is Reason.UNRESOLVED_BOUNDARY
    assert not reading.field.found

    fallback = FakeFallback(full_name=Field(expected, Provenance.FALLBACK, span=expected))
    result = InformationExtractor(fallback=fallback, name_fallback=True).extract(
        ctx(QuestionId.ASK_NAME), text
    )
    assert fallback.calls == ["full_name"]
    assert result.full_name.value == expected
    assert result.full_name.provenance is Provenance.FALLBACK


@pytest.mark.parametrize(
    "text",
    [
        "Nguyễn Thị Nha",
        "Nguyễn Thị Nha nhé em",
        "Tôi là Nguyễn Thị Nha nhé em",
        "Lê Nha",
        "Nguyễn Văn A em nhé",
        "Nguyễn Văn Em nhé",
    ],
)
def test_ambiguous_suffix_never_falls_back_to_a_wrong_rule_guess(text):
    result = InformationExtractor().extract(ctx(QuestionId.ASK_NAME), text)
    assert not result.full_name.found


def test_a_model_rejection_keeps_an_ambiguous_suffix_unresolved():
    fallback = FakeFallback(full_name=None)
    result = InformationExtractor(fallback=fallback, name_fallback=True).extract(
        ctx(QuestionId.ASK_NAME), "Nguyễn Thị Nha"
    )
    assert fallback.calls == ["full_name"]
    assert not result.full_name.found


# --- UNANCHORED: câu thiếu dấu hiệu họ tên do slot filling quyết định -------------------------
# Không cấu hình model thì giữ luật. Model lỗi hoặc trả tên không dùng được phải hỏi lại.


def slot(status: SlotFillingStatus, name: str | None = None) -> SlotFillingResult:
    field = Field(name, Provenance.FALLBACK, span=name) if name else Field.nothing()
    return SlotFillingResult(status, field, elapsed_ms=1.0)


def name_with(fallback, text: str):
    return (
        InformationExtractor(fallback=fallback, name_fallback=True)
        .extract(ctx(QuestionId.ASK_NAME), text)
        .full_name
    )


# Tên luật cũ (không xét dấu hiệu họ tên) đọc được ở các câu này
RULE_NAMES = [
    ("Lê Na", "lê na"),
    ("dạ Lê Na ạ", "lê na"),
    ("dạ tôi tên Lê Na ạ", "lê na"),
    ("tôi tên Lê Na", "lê na"),
    ("Hà Hà", "hà hà"),
    ("trần thế gian", "trần thế gian"),
    ("trời hôm nay đẹp quá", "trời hôm nay đẹp quá"),
]


@pytest.mark.parametrize("text, rule_name", RULE_NAMES)
def test_unanchored_answer_is_left_to_the_model(text, rule_name):
    reading = read_full_name(text)
    assert not reading.field.found and reading.reason is Reason.UNANCHORED
    assert read_full_name(text, require_anchor=False).field.value == rule_name


@pytest.mark.parametrize("text, rule_name", RULE_NAMES)
def test_without_a_model_unanchored_answers_keep_the_rule_name(text, rule_name):
    # Kể cả khi mô hình (nếu được hỏi) sẽ nói "không có tên": tắt slot filling thì không hỏi
    disabled = FakeFallback(full_name=slot(SlotFillingStatus.NO_NAME))
    for extractor in (
        InformationExtractor(),
        InformationExtractor(fallback=disabled, name_fallback=False),
    ):
        result = extractor.extract(ctx(QuestionId.ASK_NAME), text).full_name
        assert result.value == rule_name
        assert result.provenance is Provenance.NORMALIZED
    assert disabled.calls == []


@pytest.mark.parametrize("text, rule_name", RULE_NAMES)
def test_model_no_name_overrules_the_unanchored_rule_name(text, rule_name):
    fallback = FakeFallback(full_name=slot(SlotFillingStatus.NO_NAME))
    assert not name_with(fallback, text).found
    assert fallback.calls == ["full_name"]


@pytest.mark.parametrize("text, rule_name", RULE_NAMES)
@pytest.mark.parametrize(
    "outcome",
    [
        slot(SlotFillingStatus.UNAVAILABLE),
        slot(SlotFillingStatus.REJECTED),
        None,  # cài đặt không xử lý trường tên
    ],
)
def test_unusable_model_answer_does_not_restore_the_unanchored_rule_name(text, rule_name, outcome):
    fallback = FakeFallback(full_name=outcome)
    result = name_with(fallback, text)
    assert fallback.calls == ["full_name"]
    assert not result.found


@pytest.mark.parametrize("text, rule_name", RULE_NAMES)
def test_provider_exception_does_not_restore_the_unanchored_rule_name(text, rule_name):
    class BrokenFallback(FakeFallback):
        def full_name(self, transcript, **context):
            raise TimeoutError("synthetic provider timeout")

    assert not name_with(BrokenFallback(), text).found


def test_accepted_name_that_fails_the_extractor_guard_counts_as_rejected():
    # Mô hình báo ACCEPTED nhưng tên không nằm trong câu: không dùng, hỏi lại.
    fallback = FakeFallback(full_name=slot(SlotFillingStatus.ACCEPTED, "nguyễn văn b"))
    assert not name_with(fallback, "dạ Lê Na ạ").found


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Lê Na", "lê na"),
        ("dạ Lê Na ạ", "lê na"),
        ("tôi tên Lê Na", "lê na"),
        ("Hà Hà", "hà hà"),
        ("alo, tôi là Lê Hoa", "lê hoa"),
        ("tôi tên Trịnh Trọng Nam", "trịnh trọng nam"),
        ("tôi là Lê Thanh Toán", "lê thanh toán"),
        ("le minh tuan", "le minh tuan"),
    ],
)
def test_unanchored_real_name_is_taken_from_slot_filling(text, expected):
    fallback = FakeFallback(full_name=slot(SlotFillingStatus.ACCEPTED, expected))
    result = name_with(fallback, text)
    assert fallback.calls == ["full_name"]
    assert result.value == expected
    assert result.provenance is Provenance.FALLBACK


def test_unanchored_name_before_a_dob_comes_from_the_name_zone_only():
    text = "Tôi là Lê Na, 14/03/1978"
    fallback = FakeFallback(full_name=slot(SlotFillingStatus.ACCEPTED, "lê na"))
    result = InformationExtractor(fallback=fallback, name_fallback=True).extract(
        ctx(QuestionId.ASK_NAME), text
    )
    assert fallback.calls == ["full_name"]
    assert result.full_name.value == "lê na"
    assert result.dob.value == date(1978, 3, 14)

    # Chữ lấy từ phần ngày sinh không được thành tên; hỏi lại tên.
    fallback = FakeFallback(full_name=slot(SlotFillingStatus.ACCEPTED, "14/03/1978"))
    assert not name_with(fallback, text).found


@pytest.mark.parametrize(
    "outcome",
    [
        slot(SlotFillingStatus.NO_NAME),
        slot(SlotFillingStatus.REJECTED),
        slot(SlotFillingStatus.UNAVAILABLE),
    ],
)
def test_no_signal_has_no_rule_name_to_fall_back_on(outcome):
    text = "à ừ thì là nguyễn văn a nhé em"
    assert read_full_name(text).reason is Reason.NO_SIGNAL
    fallback = FakeFallback(full_name=outcome)
    assert not name_with(fallback, text).found
    assert fallback.calls == ["full_name"]


def test_a_negated_name_is_settled_by_the_rule():
    fallback = FakeFallback(full_name=slot(SlotFillingStatus.ACCEPTED, "lê na"))
    assert not name_with(fallback, "không phải Lê Na").found
    assert fallback.calls == []
