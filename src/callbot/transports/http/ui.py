"""Phục vụ bản build UI (Vite + React, thư mục ``ui/``) ở gốc domain: ``/``, ``/login``, ``/call``…

UI là app một trang: router chạy trên trình duyệt, nên mọi đường dẫn không phải file (vd.
``/call`` khi F5) đều trả ``index.html``. Mount ở ``/`` và phải là route đăng ký **cuối cùng**:
route API, probe, Swagger và ``/audio`` được khớp trước. Chỉ transport, không có logic nghiệp vụ;
UI gọi lại chính các endpoint ``/v1``, ``/demo-api``, ``/livekit`` như mọi client khác.
"""

import logging
from pathlib import Path, PurePath

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

logger = logging.getLogger(__name__)

UI_MOUNT_PATH = "/"
# Đường dẫn cũ của UI (trước 15-10-2026), chuyển hướng sang đường dẫn ở gốc.
OLD_UI_PREFIX = "/ui"
# Tiền tố của API: GET sai đường dẫn ở đây là 404 thật, không trả trang UI. `/livekit` vừa là
# trang UI vừa là tiền tố của `POST /livekit/token` nên chỉ chặn đường dẫn con.
_API_NAMESPACES = frozenset({"v1", "demo-api", "internal", "audio", "audio-static", "docs"})
_API_PARENTS = frozenset({"livekit"})
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
            if exc.status_code != 404 or not _is_ui_route(path):
                raise
            response = await super().get_response("index.html", scope)
            path = "index.html"
        hashed = Path(path).parts[:1] == ("assets",)
        response.headers["Cache-Control"] = _IMMUTABLE if hashed else _REVALIDATE
        return response


def _is_ui_route(path: str) -> bool:
    """Đường dẫn không có trong bản build: route của UI (trả index.html) hay 404 thật."""
    parts = PurePath(path).parts
    if not parts:
        return True
    # Có đuôi file (asset thiếu, favicon.ico) là 404 thật.
    if "." in parts[-1]:
        return False
    if parts[0] in _API_NAMESPACES:
        return False
    return not (parts[0] in _API_PARENTS and len(parts) > 1)


# Link đã chia sẻ cho mentor/team và trong tài liệu vẫn mở được: trang HTML tĩnh cũ và UI ở
# `/ui/...`. 307 (tạm thời) để trình duyệt không cache vĩnh viễn nếu sau này đổi đích.
LEGACY_REDIRECTS = {
    "/demo": "/call",
    "/demo/": "/call",
    "/demo/index.html": "/call",
    "/demo/livekit-demo.html": "/livekit",
}


def add_legacy_redirects(app: FastAPI) -> None:
    for path, target in LEGACY_REDIRECTS.items():
        app.add_api_route(path, _redirect_to(target), methods=["GET"], include_in_schema=False)
    app.add_api_route(OLD_UI_PREFIX, _redirect_to("/"), methods=["GET"], include_in_schema=False)
    app.add_api_route(
        f"{OLD_UI_PREFIX}/{{path:path}}",
        _strip_old_prefix,
        methods=["GET"],
        include_in_schema=False,
    )


def _strip_old_prefix(path: str, request: Request) -> RedirectResponse:
    query = request.url.query
    target = f"/{path}"
    return RedirectResponse(f"{target}?{query}" if query else target, status_code=307)


def _redirect_to(target: str):
    def redirect(request: Request) -> RedirectResponse:
        query = request.url.query
        return RedirectResponse(f"{target}?{query}" if query else target, status_code=307)

    return redirect


def mount_ui(app: FastAPI, directory: str) -> bool:
    """Mount UI nếu đã cấu hình và đã build; trả về ``True`` khi đã mount.

    Gọi sau khi đăng ký mọi route khác: mount ở ``/`` khớp mọi đường dẫn.
    """
    if not directory.strip():
        return False
    root = Path(directory)
    if not (root / "index.html").is_file():
        # Cấu hình trỏ tới thư mục chưa build: bot vẫn chạy, chỉ thiếu UI.
        logger.warning("UI_DIST_MISSING: %s", root)
        return False
    app.mount(UI_MOUNT_PATH, SpaStaticFiles(directory=root, html=True), name="ui")
    return True
