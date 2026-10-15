"""Hotword cho câu trả lời kế tiếp của người gọi, đổi theo từng lượt bot hỏi.

Transport (call_bridge) đặt sau mỗi lượt engine; provider hỗ trợ (`supports_hotwords`) đọc lúc decode
final. Một hộp cho một cuộc gọi (STTPipeline là per-call). Có tên khách (PII): không log nội dung.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Hotwords:
    phrases: tuple[str, ...] = ()
    # Lượt tên: luôn nhận bản decode có hotword, nâng confidence để qua cổng tên.
    name_turn: bool = False

    def __bool__(self) -> bool:
        return bool(self.phrases)


NO_HOTWORDS = Hotwords()


class HotwordBox:
    def __init__(self) -> None:
        self.current: Hotwords = NO_HOTWORDS

    def set(self, hotwords: Hotwords) -> None:
        self.current = hotwords


def word_distance(a: str, b: str) -> int:
    """Khoảng cách chỉnh sửa theo từ (thêm / bớt / thay một từ = 1)."""
    left, right = a.split(), b.split()
    previous = list(range(len(right) + 1))
    for i, word in enumerate(left, 1):
        current = [i]
        for j, other in enumerate(right, 1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (word != other))
            )
        previous = current
    return previous[-1]
