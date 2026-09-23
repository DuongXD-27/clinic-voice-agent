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
        "AI đấy?",
        "Ai vậy?",
        "ai đó",
        "ai thế",
        "ai ạ",
        "Ai gọi vậy?",
        "ai đang gọi đấy",
        "ai day",
        "ai the",
        "ai goi vay",
        "Dạ, cho hỏi ai đấy ạ?",
        "Cho tôi hỏi ai vậy?",
        "Em là ai?",
        "Bạn là ai vậy?",
        "Bên nào gọi đấy?",
        "hú hú",
        "Hú hú em ơi!",
        "hu hu",
        "alo hú hú",
        "em ơi",
        "chị ơi",
        "tôi nghe đây",
        "vâng tôi nghe",
        "ừ nghe đây",
        "ừ tôi nghe",
        "anh đang nghe đây",
        "Em gọi từ đâu?",
        "Bên em là bên nào?",
        "Bệnh viện nào vậy?",
        "Vinmec à?",
        "Đầu dây bên kia là ai?",
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
        "Nguyễn Thị Ái",
        "Ai đấy, tôi là Nguyễn Văn A",
        "Ai đấy, tôi muốn hủy lịch",
        "ai gọi vậy, tôi đang khó thở",
        "hú hú tôi tên Nguyễn Văn A",
        "hú hú tôi muốn hủy lịch",
        "em ơi tôi đang khó thở",
        "Nguyễn Văn Hữu",
        "Hà Hà",
        "hụ hụ",
        "hư hư",
    ],
)
def test_not_greeting(text: str) -> None:
    assert not is_greeting(text)
