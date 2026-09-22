"""Câu chào xã giao: cả câu chỉ là "alo" / "xin chào" (kèm từ đệm)."""

import pytest

from callbot.engine.extraction.greeting import is_greeting


@pytest.mark.parametrize(
    "text",
    [
        "alo",
        "Alo.",
        "a lô",
        "alô alô",
        "dạ alo",
        "vâng, alo ạ",
        "alo ai đấy",
        "Alo, ai gọi vậy?",
        "xin chào",
        "chào em",
        "alo em",
        "a lo",
        "hello em",
        "hi em",
        "Hello, chị ạ!",
        "dạ hi anh",
        "hello bạn",
        "hi cô",
    ],
)
def test_greeting(text: str) -> None:
    assert is_greeting(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "vâng",
        "alo, tôi là Lê Hoa",
        "alo tôi muốn hủy lịch",
        "Nguyễn Văn A",
        "chào em, tôi tên Hoa",
        "gì cơ",
        "hello em, tôi tên Nguyễn Văn A",
        "hi em tôi muốn hủy lịch",
        "Nguyễn Văn Hi",
    ],
)
def test_not_greeting(text: str) -> None:
    assert not is_greeting(text)
