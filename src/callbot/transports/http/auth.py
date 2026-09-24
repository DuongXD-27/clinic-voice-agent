"""Bearer key cho các route gọi được từ ngoài (/v1/calls, /demo-api).

BOT_API_KEYS rỗng = tắt auth (dev local, test). /health, /ready, /audio và trang /demo
không đi qua dependency này: probe cần mở, harness tải ``audio_url`` không kèm header.
"""

import hmac
from typing import Optional

from fastapi import HTTPException, Request

from callbot.transports.http.config import settings


def _bad_key(message: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={"code": "BAD_KEY", "message": message},
        headers={"WWW-Authenticate": "Bearer"},
    )


def _bearer_token(request: Request) -> Optional[str]:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def require_api_key(request: Request) -> None:
    keys = settings.api_keys()
    if not keys:
        return
    token = _bearer_token(request)
    if token is None:
        raise _bad_key("Missing bearer token.")
    # So từng key bằng compare_digest, không dừng sớm khi khớp để thời gian không lộ vị trí key
    matched = False
    for key in keys:
        matched |= hmac.compare_digest(token.encode(), key.encode())
    if not matched:
        raise _bad_key("Invalid bearer token.")
