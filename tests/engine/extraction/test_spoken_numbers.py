import pytest

from callbot.engine.extraction.spoken_numbers import parse_number, spoken_digits


@pytest.mark.parametrize(
    "words, expected",
    [
        ("mười", 10),
        ("mười bốn", 14),
        ("mười lăm", 15),
        ("hai mươi", 20),
        ("hai mươi mốt", 21),
        ("hai mốt", 21),
        ("ba lăm", 35),
        ("bảy tám", 78),
        ("tư", 4),
        ("một nghìn chín trăm bảy mươi tám", 1978),
        ("một chín bảy tám", 1978),
        ("hai nghìn không trăm linh năm", 2005),
        ("hai nghìn linh năm", 2005),
        ("hai ngàn lẻ tư", 2004),
        ("hai nghìn mười", 2010),
        ("1978", 1978),
    ],
)
def test_parse_number(words: str, expected: int) -> None:
    assert parse_number(words.split()) == expected


@pytest.mark.parametrize(
    "words", ["mươi", "mười mốt", "một mươi", "lăm hai", "trăm", "hai 5", "mốt ba"]
)
def test_parse_number_rejects_malformed(words: str) -> None:
    assert parse_number(words.split()) is None


def test_spoken_digits_keeps_leading_zero() -> None:
    assert spoken_digits("không ba".split()) == "03"
