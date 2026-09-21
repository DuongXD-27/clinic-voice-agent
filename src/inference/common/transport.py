"""HTTP transport types and timeout construction shared by remote providers."""

from collections.abc import Callable

import httpx

HttpClientFactory = Callable[[], httpx.Client]


def build_http_timeout(timeout_s: float, connect_timeout_s: float) -> httpx.Timeout:
    return httpx.Timeout(timeout_s, connect=connect_timeout_s)
