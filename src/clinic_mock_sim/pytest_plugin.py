"""Fixture pytest cho cả repo — đăng ký một lần trong `tests/conftest.py`:

    pytest_plugins = ["clinic_mock_sim.pytest_plugin"]

- `clinic`: `FakeClinicAPI()` mới cho mỗi test. Override trong file test để đổi dữ liệu/lỗi;
  fixture `client` (app HTTP) dùng theo.
- `clinic_scenario`: factory `clinic_scenario("slot_race", **params)` → sim đã dựng sẵn edge case.
- Chặn gọi mạng thật (autouse): request tới host của CLINIC_MOCK_BASE_URL bị chặn trừ khi
  `CLINIC_MOCK_LIVE=1` — test quên truyền clinic sẽ đỏ thay vì âm thầm ghi vào mock chung của team.
"""

import os
from collections.abc import Callable, Iterator
from typing import Any, Optional
from urllib.parse import urlsplit

import httpx
import pytest

from clinic_mock_sim import scenarios
from clinic_mock_sim.routes import FakeClinicAPI

LIVE_ENV = "CLINIC_MOCK_LIVE"


@pytest.fixture
def clinic() -> FakeClinicAPI:
    return FakeClinicAPI()


@pytest.fixture
def clinic_scenario() -> Callable[..., FakeClinicAPI]:
    def factory(name: str, base: Optional[FakeClinicAPI] = None, **params: Any) -> FakeClinicAPI:
        return scenarios.build(name, base, **params)

    return factory


def _clinic_host() -> Optional[str]:
    try:
        from callbot.transports.http.config import Settings

        return urlsplit(Settings().clinic_mock_base_url).hostname
    except Exception:  # noqa: BLE001 — thiếu cấu hình thì không có gì để chặn
        return None


@pytest.fixture(autouse=True)
def block_live_clinic(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    if os.environ.get(LIVE_ENV) == "1":
        yield
        return
    host = _clinic_host()
    if not host or host in {"localhost", "127.0.0.1"}:
        # Mock chạy local (test cross-service tự bật) không phải instance chung của team
        yield
        return
    original = httpx.HTTPTransport.handle_request

    def guarded(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        if request.url.host == host:
            raise RuntimeError(
                f"Test đang gọi clinic mock thật ({host}). Dùng fixture `clinic` hoặc truyền "
                f"clinic_factory; muốn gọi thật thì đặt {LIVE_ENV}=1 (báo team trước)."
            )
        return original(self, request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", guarded)
    yield
