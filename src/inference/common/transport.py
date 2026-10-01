"""HTTP transport types and timeout construction shared by remote providers."""

from collections.abc import Callable
from dataclasses import dataclass
from threading import Event, Thread
from time import monotonic
from typing import Any

import httpx

HttpClientFactory = Callable[[], httpx.Client]
MODEL_CALL_HARD_LIMIT_S = 3.0


def build_http_timeout(timeout_s: float, connect_timeout_s: float) -> httpx.Timeout:
    return httpx.Timeout(timeout_s, connect=connect_timeout_s)


class TotalRequestTimeout(Exception):
    """The complete HTTP response was not received within the model-call budget."""


@dataclass(frozen=True)
class TimedResponse:
    response: httpx.Response
    model_call_latency_ms: float


def post_with_total_timeout(
    client_factory: HttpClientFactory,
    *,
    total_timeout_s: float,
    clock: Callable[[], float] = monotonic,
    **request: Any,
) -> TimedResponse:
    """Bound header and full-body receipt, independent of HTTPX phase timeouts.

    A late worker may finish after the caller times out, but its response is never
    accepted. The worker owns and closes its client, including after a timeout.
    """
    started = Event()
    finished = Event()
    cancelled = Event()
    state: dict[str, Any] = {}

    def send() -> None:
        client = None
        try:
            client = client_factory()
            if cancelled.is_set():
                return
            state["start"] = clock()
            started.set()
            if cancelled.is_set():
                return
            deadline = state["start"] + total_timeout_s
            with client.stream("POST", **request) as response:
                body = bytearray()
                for chunk in response.iter_bytes():
                    if cancelled.is_set() or clock() > deadline:
                        raise TotalRequestTimeout
                    body.extend(chunk)
                body_received_at = clock()
                if cancelled.is_set() or body_received_at > deadline:
                    raise TotalRequestTimeout
                # iter_bytes() has already decoded the body. Preserve other headers,
                # but let HTTPX calculate the length of the decoded content.
                headers = response.headers.copy()
                headers.pop("content-encoding", None)
                headers.pop("content-length", None)
                state["response"] = httpx.Response(
                    response.status_code,
                    headers=headers,
                    content=bytes(body),
                    request=response.request,
                    extensions=response.extensions,
                )
                state["end"] = body_received_at
                finished.set()
        except Exception as exc:
            state["error"] = exc
        finally:
            state.setdefault("end", clock())
            started.set()
            finished.set()
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

    Thread(target=send, name="model-http-call", daemon=True).start()
    if not started.wait(total_timeout_s):
        cancelled.set()
        raise TotalRequestTimeout
    if "start" not in state:
        if "error" in state:
            raise state["error"]
        raise TotalRequestTimeout
    deadline = state["start"] + total_timeout_s
    finished.wait(max(0.0, deadline - clock()))
    if not finished.is_set() or state["end"] > deadline:
        cancelled.set()
        raise TotalRequestTimeout
    if "error" in state:
        raise state["error"]
    return TimedResponse(state["response"], (state["end"] - state["start"]) * 1000)
