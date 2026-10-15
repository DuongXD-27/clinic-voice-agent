"""Top N phương án ASR của từng final — để hiện trên trang demo, không ảnh hưởng lượt.

Provider hỗ trợ (`supports_nbest`) tính top N trong nền sau mỗi final có chữ và bỏ task vào
hộp; transport lấy hết khi gửi lời người gọi, chờ xong rồi gửi riêng. Một hộp cho một cuộc gọi
(STTPipeline là per-call). Có tên khách (PII): không log nội dung.
"""

import asyncio


class NBestBox:
    def __init__(self) -> None:
        self._pending: list[asyncio.Future] = []

    def add(self, task: asyncio.Future) -> None:
        self._pending.append(task)

    def take(self) -> list[asyncio.Future]:
        """Mọi task từ lần lấy trước (các final gộp thành lượt vừa xong), theo thứ tự."""
        pending, self._pending = self._pending, []
        return pending
