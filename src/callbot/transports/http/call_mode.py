"""Trạng thái `mode` của từng cuộc gọi trên đường HTTP (§4.1.2).

`CallModeStore` không nằm trong `CallStart`/`CallContext` của engine vì engine chỉ biết
text — audio là việc của tầng transport + package `speech`.
"""

from redis import Redis


class CallModeStore:
    """Nhớ cuộc gọi nào đang `mode=audio` — Redis riêng, không đụng `RedisSessionStore`.

    Cần Redis (không phải dict trong process) vì `WEB_CONCURRENCY` chạy nhiều worker
    process; lượt `turn` có thể rơi vào worker khác với lượt `start_call`. Nhận thẳng
    `client` (không tự tạo từ URL) để test có thể tiêm `fakeredis` giống `RedisSessionStore`.
    """

    def __init__(self, client: Redis, *, key_prefix: str = "callbot", ttl_s: int = 7200) -> None:
        self._client = client
        self._prefix = key_prefix.rstrip(":")
        self._ttl_s = ttl_s

    def _key(self, call_id: str) -> str:
        return f"{self._prefix}:audio_mode:{call_id}"

    def set_audio(self, call_id: str) -> None:
        self._client.set(self._key(call_id), "1", ex=self._ttl_s)

    def is_audio(self, call_id: str) -> bool:
        return self._client.get(self._key(call_id)) is not None

    def close(self) -> None:
        self._client.close()
