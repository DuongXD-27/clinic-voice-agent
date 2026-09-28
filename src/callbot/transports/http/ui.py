"""Phục vụ bản build UI (Vite + React, thư mục ``ui/``) tại ``/ui``.

UI là app một trang: router chạy trên trình duyệt, nên mọi đường dẫn không phải file (vd.
``/ui/call`` khi F5) đều trả ``index.html``. Chỉ transport, không có logic nghiệp vụ; UI gọi
lại chính các endpoint ``/v1``, ``/demo-api``, ``/livekit`` như mọi client khác.
"""

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

logger = logging.getLogger(__name__)

UI_MOUNT_PATH = "/ui"
# Vite gắn hash nội dung vào tên file trong assets/: nội dung đổi thì tên đổi, cache vĩnh viễn được.
_IMMUTABLE = "public, max-age=31536000, immutable"
# index.html (và file public không hash) phải hỏi lại server để nhận tên asset mới sau deploy.
_REVALIDATE = "no-cache"


class SpaStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        # `path` theo phân cách của hệ điều hành (StaticFiles dùng os.path), nên so bằng Path.
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            # Có đuôi file (asset thiếu, favicon.ico) là 404 thật; không có là route của UI.
            if exc.status_code != 404 or "." in Path(path).name:
                raise
            response = await super().get_response("index.html", scope)
            path = "index.html"
        hashed = Path(path).parts[:1] == ("assets",)
        response.headers["Cache-Control"] = _IMMUTABLE if hashed else _REVALIDATE
        return response


# Trang cũ (HTML tĩnh) đã chuyển vào UI mới: link đã chia sẻ cho mentor/team và trong tài liệu
# vẫn mở được. 307 (tạm thời) để trình duyệt không cache vĩnh viễn nếu sau này đổi đích.
LEGACY_REDIRECTS = {
    "/": "/ui/",
    "/demo": "/ui/call",
    "/demo/": "/ui/call",
    "/demo/index.html": "/ui/call",
    "/demo/livekit-demo.html": "/ui/livekit",
    "/observability": "/ui/observability",
    "/observability/": "/ui/observability",
}


def add_legacy_redirects(app: FastAPI) -> None:
    for path, target in LEGACY_REDIRECTS.items():
        app.add_api_route(path, _redirect_to(target), methods=["GET"], include_in_schema=False)


def _redirect_to(target: str):
    def redirect(request: Request) -> RedirectResponse:
        query = request.url.query
        return RedirectResponse(f"{target}?{query}" if query else target, status_code=307)

    return redirect


def mount_ui(app: FastAPI, directory: str) -> bool:
    """Mount UI nếu đã cấu hình và đã build; trả về ``True`` khi đã mount."""
    if not directory.strip():
        return False
    root = Path(directory)
    if not (root / "index.html").is_file():
        # Cấu hình trỏ tới thư mục chưa build: bot vẫn chạy, chỉ thiếu UI.
        logger.warning("UI_DIST_MISSING: %s", root)
        return False
    app.mount(UI_MOUNT_PATH, SpaStaticFiles(directory=root, html=True), name="ui")
    return True
