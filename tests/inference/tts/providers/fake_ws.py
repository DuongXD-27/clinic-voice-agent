"""Fake WebSocket theo chữ ký `websockets.sync.client.connect` — chạy `ElevenLabsTTS` không cần mạng."""

import base64
import json
import time
from typing import Any, Optional

from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosedOK, InvalidStatus
from websockets.frames import Close
from websockets.http11 import Response


def audio_message(pcm: bytes, is_final: Optional[bool] = None) -> dict[str, Any]:
    return {"audio": base64.b64encode(pcm).decode(), "isFinal": is_final, "alignment": None}


def final_message() -> dict[str, Any]:
    return {"audio": None, "isFinal": True}


def error_message(code: str, detail: str = "chi tiết từ server") -> dict[str, Any]:
    return {"error": code, "message": detail, "code": 1008}


def handshake_error(status_code: int) -> InvalidStatus:
    return InvalidStatus(Response(status_code, "x", Headers()))


def closed_ok() -> ConnectionClosedOK:
    return ConnectionClosedOK(Close(1000, ""), None)


class FakeWebSocket:
    """`script`: danh sách message (dict -> JSON gửi về) hoặc Exception (ném khi recv tới lượt đó)."""

    def __init__(self, script: list[Any], recv_delay_s: float = 0.0) -> None:
        self._script = list(script)
        self._recv_delay_s = recv_delay_s
        self.sent: list[dict[str, Any]] = []
        self.closed = False
        self.recv_timeouts: list[Optional[float]] = []

    def __enter__(self) -> "FakeWebSocket":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.closed = True

    def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    def recv(self, timeout: Optional[float] = None, decode: Optional[bool] = None) -> str:
        self.recv_timeouts.append(timeout)
        if self._recv_delay_s:
            time.sleep(self._recv_delay_s)
        if not self._script:
            raise closed_ok()
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return json.dumps(item)


class FakeConnect:
    """Ghi lại url/header của lần connect; trả `FakeWebSocket` hoặc ném lỗi handshake."""

    def __init__(
        self,
        script: list[Any],
        *,
        raise_on_connect: Optional[BaseException] = None,
        recv_delay_s: float = 0.0,
    ) -> None:
        self._script = script
        self._raise = raise_on_connect
        self._recv_delay_s = recv_delay_s
        self.calls: list[dict[str, Any]] = []
        self.sockets: list[FakeWebSocket] = []

    def __call__(self, uri: str, **kwargs: Any) -> FakeWebSocket:
        self.calls.append({"uri": uri, **kwargs})
        if self._raise is not None:
            raise self._raise
        ws = FakeWebSocket(self._script, recv_delay_s=self._recv_delay_s)
        self.sockets.append(ws)
        return ws
