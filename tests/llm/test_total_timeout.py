"""R-31: the full model response has one monotonic three-second deadline."""

import gzip
import json
import zlib
from threading import Event, Lock

import httpx
import pytest

from callbot.tracing.context import Tracer
from callbot.tracing.generation import finish_generation, normalized_result
from callbot.tracing.pseudonym import CallKeyFactory
from inference.common.transport import TotalRequestTimeout, post_with_total_timeout
from inference.llm.config import OpenAIConfig
from inference.llm.gateway import create_gateway
from inference.llm.providers import _chat_completions


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0
        self.lock = Lock()

    def __call__(self) -> float:
        with self.lock:
            return self.value

    def advance(self, seconds: float) -> None:
        with self.lock:
            self.value += seconds


class DelayedBody(httpx.SyncByteStream):
    def __init__(self, clock: FakeClock, seconds: float, body: bytes) -> None:
        self.clock = clock
        self.seconds = seconds
        self.body = body

    def __iter__(self):
        self.clock.advance(self.seconds)
        yield self.body


_BODY = json.dumps(
    {
        "model": "gpt-6-luna",
        "choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
    }
).encode()
_MESSAGES = [{"role": "user", "content": "synthetic"}]
_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


def _gateway(
    monkeypatch, clock: FakeClock, delay: float, *, body: bytes = _BODY, budget: float = 3.0
):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, stream=DelayedBody(clock, delay, body))

    original = post_with_total_timeout
    monkeypatch.setattr(
        _chat_completions,
        "post_with_total_timeout",
        lambda client, **kwargs: original(client, clock=clock, **kwargs),
    )
    config = OpenAIConfig(api_key="synthetic-key", timeout_s=budget, _env_file=None)
    gateway = create_gateway(
        "openai",
        config=config,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    return gateway, calls


@pytest.mark.parametrize(
    ("full_body_seconds", "expected"),
    [(2.90, "completed"), (2.99, "completed"), (3.00, "completed"), (3.01, "timeout")],
)
def test_full_body_deadline_boundary(monkeypatch, full_body_seconds, expected):
    clock = FakeClock()
    gateway, calls = _gateway(monkeypatch, clock, full_body_seconds)
    reply = gateway.generate_structured(_MESSAGES, schema=_SCHEMA, schema_name="synthetic")
    assert reply.status == expected
    assert len(calls) == 1
    if expected == "completed":
        assert reply.model_call_latency_ms == pytest.approx(full_body_seconds * 1000)
    else:
        assert reply.content is None


def test_trickled_body_stops_at_total_deadline(monkeypatch):
    clock = FakeClock()
    calls = []

    class Trickle(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(4):
                clock.advance(1.0)
                yield b"x"

    def handler(request):
        calls.append(request)
        return httpx.Response(200, stream=Trickle())

    original = post_with_total_timeout
    monkeypatch.setattr(
        _chat_completions,
        "post_with_total_timeout",
        lambda factory, **kwargs: original(factory, clock=clock, **kwargs),
    )
    gateway = create_gateway(
        "openai",
        config=OpenAIConfig(api_key="synthetic-key", timeout_s=3.0, _env_file=None),
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    reply = gateway.generate_structured(_MESSAGES, schema=_SCHEMA, schema_name="synthetic")
    assert reply.status == "timeout"
    assert len(calls) == 1


def test_parse_after_full_response_does_not_trigger_model_timeout(monkeypatch):
    clock = FakeClock()
    gateway, _ = _gateway(monkeypatch, clock, 2.95)
    original = _chat_completions._Completion.model_validate_json

    def delayed_parse(body):
        clock.advance(0.10)
        return original(body)

    monkeypatch.setattr(
        _chat_completions._Completion, "model_validate_json", staticmethod(delayed_parse)
    )
    reply = gateway.generate_structured(_MESSAGES, schema=_SCHEMA, schema_name="synthetic")
    assert clock() == pytest.approx(3.05)
    assert reply.status == "completed"
    assert reply.model_call_latency_ms == pytest.approx(2950)


def test_config_override_cannot_raise_r31_hard_limit(monkeypatch):
    clock = FakeClock()
    gateway, calls = _gateway(monkeypatch, clock, 3.01, budget=9.0)
    reply = gateway.generate_structured(_MESSAGES, schema=_SCHEMA, schema_name="synthetic")
    assert reply.status == "timeout"
    assert len(calls) == 1


def test_late_response_cannot_be_accepted_and_has_no_retry(monkeypatch):
    entered = Event()
    release = Event()
    closed = Event()
    calls = []

    def handler(request):
        calls.append(request)
        entered.set()
        release.wait(1)
        return httpx.Response(200, content=_BODY)

    class TrackingClient(httpx.Client):
        def close(self):
            closed.set()
            super().close()

    config = OpenAIConfig(api_key="synthetic-key", timeout_s=0.02, _env_file=None)
    gateway = create_gateway(
        "openai",
        config=config,
        client_factory=lambda: TrackingClient(transport=httpx.MockTransport(handler)),
    )
    try:
        reply = gateway.generate_structured(_MESSAGES, schema=_SCHEMA, schema_name="synthetic")
        assert entered.is_set()
        assert reply.status == "timeout"
        assert len(calls) == 1
        assert not closed.is_set()
    finally:
        release.set()
    assert closed.wait(1)


def test_timeout_during_client_creation_does_not_send_late_request():
    release = Event()
    closed = Event()
    calls = []

    class TrackingClient(httpx.Client):
        def close(self):
            closed.set()
            super().close()

    def factory():
        release.wait(1)
        return TrackingClient(
            transport=httpx.MockTransport(
                lambda request: calls.append(request) or httpx.Response(200)
            )
        )

    try:
        with pytest.raises(TotalRequestTimeout):
            post_with_total_timeout(factory, total_timeout_s=0.02, url="https://example.test")
    finally:
        release.set()
    assert closed.wait(1)
    assert calls == []


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        ("timeout", "timeout"),
        ("network", "network_error"),
        ("http", "http_error"),
        ("invalid", "invalid_response"),
    ],
)
def test_failure_classification_and_generation_result(monkeypatch, outcome, expected):
    calls = []

    def handler(request):
        calls.append(request)
        if outcome == "timeout":
            raise httpx.ConnectTimeout("synthetic", request=request)
        if outcome == "network":
            raise httpx.ConnectError("synthetic", request=request)
        if outcome == "http":
            return httpx.Response(503)
        return httpx.Response(200, content=b"invalid")

    config = OpenAIConfig(api_key="synthetic-key", timeout_s=3.0, _env_file=None)
    gateway = create_gateway(
        "openai",
        config=config,
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    reply = gateway.generate_structured(_MESSAGES, schema=_SCHEMA, schema_name="synthetic")
    assert reply.status == expected
    assert len(calls) == 1
    if outcome in {"http", "invalid"}:
        assert reply.model_call_latency_ms is not None
    result = normalized_result(reply.status)
    assert (
        result
        == {"timeout": "TIMEOUT", "network": "ERROR", "http": "ERROR", "invalid": "INVALID"}[
            outcome
        ]
    )

    class Sink:
        records = []

        def emit(self, span):
            self.records.append(span)

    sink = Sink()
    tracer = Tracer(
        sink,
        CallKeyFactory("synthetic-r31-key-0000000000000000", version="v1", environment="test"),
    )
    with tracer.start_trace(
        call_id="synthetic-r31", turn=1, component="TURN", operation="http.call_turn"
    ):
        with tracer.generation(component="LLM", operation="llm.semantic_extract") as generation:
            finish_generation(generation, "openai", gateway.model, reply, result)
    record = next(item for item in sink.records if item.observation_type == "GENERATION")
    assert record.attributes["result"] == result
    assert record.status == "ERROR"
    assert "synthetic-key" not in json.dumps(record.to_dict())


def test_transport_deadline_exception_is_distinct_from_httpx_phase_timeout():
    assert not issubclass(TotalRequestTimeout, httpx.TimeoutException)


@pytest.mark.parametrize("encoding", ["gzip", "deflate", None])
@pytest.mark.parametrize("status", [200, 503])
def test_rebuilt_response_headers_describe_decoded_body(encoding, status):
    clock = FakeClock()
    body = {"gzip": gzip.compress, "deflate": zlib.compress}.get(encoding, lambda b: b)(_BODY)
    headers = [
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
        ("X-Request-Id", "synthetic-request"),
        ("Set-Cookie", "first=1"),
        ("Set-Cookie", "second=2"),
    ]
    if encoding:
        headers.append(("Content-Encoding", encoding))
    requests = []
    responses = []

    def handler(request):
        requests.append(request)
        response = httpx.Response(
            status,
            headers=headers,
            stream=DelayedBody(clock, 0.25, body),
            extensions={"http_version": b"HTTP/2"},
        )
        responses.append(response)
        return response

    timed = post_with_total_timeout(
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
        total_timeout_s=3.0,
        clock=clock,
        url="https://example.test",
    )
    response = timed.response
    assert response.content == _BODY
    assert response.json() == json.loads(_BODY)
    assert response.status_code == status
    assert "content-encoding" not in response.headers
    assert int(response.headers["content-length"]) == len(_BODY)
    assert response.headers["content-type"] == "application/json"
    assert response.headers["x-request-id"] == "synthetic-request"
    assert response.headers.get_list("set-cookie") == ["first=1", "second=2"]
    assert response.request is requests[0]
    assert response.extensions["http_version"] == b"HTTP/2"
    assert responses[0].headers["content-length"] == str(len(body))
    if encoding:
        assert responses[0].headers["content-encoding"] == encoding
    assert timed.model_call_latency_ms == pytest.approx(250)
