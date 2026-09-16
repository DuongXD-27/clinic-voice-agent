from callbot.engine.extraction.text import (
    clean,
    compile_phrases,
    find_phrase,
    is_negated,
    normalize,
)


def test_normalize_unifies_unicode_and_tone_placement() -> None:
    assert normalize("  HUỶ   lịch ") == "hủy lịch"
    assert normalize("Hoà") == normalize("Hòa")
    assert normalize("hoàng") == "hoàng"  # âm tiết đóng không đổi
    assert normalize("quý") == "quý"
    assert normalize("Nguyễn") == "nguyễn"
    assert clean("Dạ, vâng!") == "dạ vâng"


def test_phrase_matching_respects_word_boundaries_and_negation() -> None:
    phrases = compile_phrases(["hủy"])
    assert find_phrase("hủy lịch", phrases) is not None
    assert find_phrase("khủy tay", phrases) is None
    text = "tôi không muốn hủy"
    match = find_phrase(text, phrases)
    assert match is not None and is_negated(text, match.start())
    assert find_phrase(text, phrases, allow_negated=False) is None
