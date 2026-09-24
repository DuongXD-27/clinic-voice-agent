"""Bearer key cho các route gọi được từ ngoài (/v1/calls, /demo-api).

BOT_API_KEYS rỗng = tắt auth (dev local, test). /health, /ready, /audio và trang /demo
không đi qua dependency này: probe cần mở, harness tải ``audio_url`` không kèm header.
"""

import hmac
from typing import Annotated, Optional

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from callbot.transports.http.config import settings

# Khai báo scheme để Swagger (/docs) có nút Authorize; auto_error=False để lỗi giữ dạng BAD_KEY
# và để route vẫn mở khi BOT_API_KEYS rỗng.
_bearer = HTTPBearer(auto_error=False, scheme_name="BearerAuth")
Credentials = Annotated[Optional[HTTPAuthorizationCredentials], Security(_bearer)]


def _bad_key(message: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={"code": "BAD_KEY", "message": message},
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_api_key(credentials: Credentials) -> None:
    keys = settings.api_keys()
    if not keys:
        return
    # HTTPBearer trả None khi thiếu header hoặc scheme khác Bearer
    token = credentials.credentials.strip() if credentials else ""
    if not token:
        raise _bad_key("Missing bearer token.")
    # So từng key bằng compare_digest, không dừng sớm khi khớp để thời gian không lộ vị trí key
    matched = False
    for key in keys:
        matched |= hmac.compare_digest(token.encode(), key.encode())
    if not matched:
        raise _bad_key("Invalid bearer token.")
