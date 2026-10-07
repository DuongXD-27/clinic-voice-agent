from callbot.engine.extraction.text import (
    clean,
    compile_phrases,
    drop_leading_words,
    find_phrase,
    is_negated,
    keep_leading_words,
    normalize,
    remove_words,
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


# --- Cắt trên bản còn dấu câu (review PR 06/10, evidence §10): "20/10", "15:30" không bị tách số ----------


def test_remove_words_keeps_the_punctuation_of_what_is_left() -> None:
    text = "Tôi là Nguyễn Văn A, sinh 14/3/78, muốn đổi sang 15:30 ngày 20/10"
    assert (
        remove_words(text, ["14 3 78", "nguyễn văn a"])
        == "tôi là sinh muốn đổi sang 15:30 ngày 20/10"
    )


def test_remove_words_skips_missing_spans_and_keeps_partly_covered_tokens() -> None:
    assert remove_words("đổi sang 20/10", [None, "", "không có"]) == "đổi sang 20/10"
    # "20" nằm trong đoạn nhưng "20/10" còn "10" ngoài đoạn -> giữ cả từ
    assert remove_words("ngày 20/10", ["ngày 20"]) == "20/10"


def test_drop_leading_words_counts_clean_words() -> None:
    assert drop_leading_words("Không có 5 giờ thì, 9:00 ngày 16", 5) == "9:00 ngày 16"
    assert drop_leading_words("thì thôi,khung 2", 2) == "thôi,khung 2"


def test_keep_leading_words_keeps_punctuation() -> None:
    assert keep_leading_words("15/10 chứ không phải 14/10", 2) == "15/10"
    assert keep_leading_words("khung 2, chứ không phải khung 1", 2) == "khung 2,"
    # "15:30" là hai từ `clean`: không vắt qua ranh giới
    assert keep_leading_words("lúc 15:30 nhé", 2) == "lúc"
