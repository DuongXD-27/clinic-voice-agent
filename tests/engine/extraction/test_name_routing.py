"""Residual speech must not become a NORMALIZED name or survive failed NER."""

import pytest

from callbot.engine.extraction import Field, InformationExtractor, Provenance, QuestionId
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
def test_suspect_boundary_routes_to_ner_and_uses_only_the_grounded_name(text):
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
        ("Hà Hà", "hà hà"),
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
        def full_name(self, transcript):
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
def test_ambiguous_suffix_must_use_ner_instead_of_a_truncated_rule_name(text, expected):
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
