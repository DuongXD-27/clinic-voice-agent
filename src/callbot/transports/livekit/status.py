"""Báo lỗi không mở / không tiếp tục được cuộc gọi lên trang gọi thử (`/ui/livekit`, `/ui/stt`)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Topic báo lỗi (`{code, message}`) để trang không im lặng khi worker không chạy được.
STATUS_TOPIC = "callbot.status"
# Trang tự rời phòng khi nhận lỗi; chờ tối đa chừng này rồi mới để job dừng.
_WAIT_FOR_PAGE_S = 5.0


async def report_status(room: Any, code: str, message: str) -> None:
    """Gửi lỗi rồi chờ trang rời phòng: job dừng ngay thì kết nối đóng trước khi gói tin tới
    trình duyệt (12/10: lỗi ElevenLabs mất, trang đứng ở "Đang chờ worker vào phòng…"). Gửi
    không được thì chỉ ghi log."""
    try:
        await room.local_participant.publish_data(
            json.dumps({"code": code, "message": message}, ensure_ascii=False),
            reliable=True,
            topic=STATUS_TOPIC,
        )
    except Exception as exc:
        logger.warning("status: không gửi được lỗi %s tới browser (%s)", code, type(exc).__name__)
        return
    await wait_until_alone(room, timeout_s=_WAIT_FOR_PAGE_S)


async def wait_until_alone(room: Any, *, timeout_s: float) -> None:
    """Chờ tới khi không còn ai khác trong phòng, tối đa `timeout_s`."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while getattr(room, "remote_participants", None) and loop.time() < deadline:
        await asyncio.sleep(0.1)
