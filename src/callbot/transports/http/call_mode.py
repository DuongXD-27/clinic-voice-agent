"""Trạng thái `mode` của từng cuộc gọi trên đường HTTP (§4.1.2).

`CallModeStore` không nằm trong `CallStart`/`CallContext` của engine vì engine chỉ biết
text — audio là việc của tầng transport + package `speech`.
"""

import hashlib
import json
from typing import Any, Optional

from redis import Redis
from redis.exceptions import RedisError

from callbot.engine.errors import CallConflict, SessionStoreUnavailable
from callbot.engine.session.redis_store import RedisSessionStore

OUTPUT_RETRY_TTL_S = 120


class CallModeStore:
    """Giữ mode HTTP và biên nhận output tạm, tách khỏi dữ liệu session nghiệp vụ.

    Cần Redis (không phải dict trong process) vì `WEB_CONCURRENCY` chạy nhiều worker
    process; lượt `turn` có thể rơi vào worker khác với lượt `start_call`. Nhận thẳng
    `client` (không tự tạo từ URL) để test có thể tiêm `fakeredis` giống `RedisSessionStore`.
    """

    def __init__(self, client: Redis, *, key_prefix: str = "callbot", ttl_s: int = 7200) -> None:
        self._client = client
        self._prefix = key_prefix.rstrip(":")
        self._ttl_s = ttl_s
        self._locks = RedisSessionStore(
            client, key_prefix=f"{self._prefix}:http_audio", close_client=False
        )

    def _key(self, call_id: str) -> str:
        return f"{self._prefix}:audio_mode:{call_id}"

    def set_audio(self, call_id: str) -> None:
        self.set_mode(call_id, "audio")

    def request_lock(self, call_id: str):
        """Khóa transport riêng: bao trọn Core và xuất audio, không lồng khóa session."""
        return self._locks.call_lock(call_id, 1.0)

    def mode(self, call_id: str) -> Optional[str]:
        try:
            value = self._client.get(self._key(call_id))
        except RedisError as exc:
            raise SessionStoreUnavailable("Không đọc được mode HTTP") from exc
        return "audio" if value == "1" else value

    def check_mode(self, call_id: str, mode: str) -> None:
        existing = self.mode(call_id)
        if existing is not None and existing != mode:
            raise CallConflict(call_id)

    def set_mode(self, call_id: str, mode: str) -> None:
        self.check_mode(call_id, mode)
        try:
            self._client.set(self._key(call_id), mode, ex=self._ttl_s, nx=True)
        except RedisError as exc:
            raise SessionStoreUnavailable("Không lưu được mode HTTP") from exc
        self.check_mode(call_id, mode)

    def is_audio(self, call_id: str) -> bool:
        return self.mode(call_id) == "audio"

    @staticmethod
    def request_digest(value: dict[str, Any]) -> str:
        raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _output_key(self, call_id: str, turn: int) -> str:
        return f"{self._prefix}:pending_audio:{call_id}:{turn}"

    def pending_output(self, call_id: str, turn: int) -> Optional[dict[str, Any]]:
        try:
            value = self._client.get(self._output_key(call_id, turn))
            return json.loads(value) if value is not None else None
        except RedisError as exc:
            raise SessionStoreUnavailable("Không đọc được biên nhận audio") from exc

    def save_pending_output(
        self, call_id: str, turn: int, request_digest: str, action: dict[str, Any]
    ) -> None:
        # Chỉ phục hồi phát âm sau commit, không lưu transcript/extraction/hồ sơ Clinic.
        value = json.dumps({"request_digest": request_digest, "action": action}, ensure_ascii=False)
        if len(value.encode("utf-8")) > 32768:
            raise SessionStoreUnavailable("Biên nhận audio vượt giới hạn")
        try:
            self._client.set(self._output_key(call_id, turn), value, ex=OUTPUT_RETRY_TTL_S, nx=True)
        except RedisError as exc:
            raise SessionStoreUnavailable("Không lưu được biên nhận audio") from exc

    def clear_pending_output(self, call_id: str, turn: int) -> None:
        try:
            self._client.delete(self._output_key(call_id, turn))
        except RedisError as exc:
            raise SessionStoreUnavailable("Không xóa được biên nhận audio") from exc

    def close(self) -> None:
        self._client.close()
