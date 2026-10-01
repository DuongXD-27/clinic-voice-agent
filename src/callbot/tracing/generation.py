"""Privacy-safe metadata for an actual structured model invocation."""

from __future__ import annotations

from callbot.tracing.context import SpanHandle, current_span, null_tracer
from callbot.tracing.pricing import llm_cost


def generation_scope(operation: str):
    parent = current_span()
    tracer = parent._tracer if parent is not None else null_tracer()
    return tracer.generation(component="LLM", operation=operation)


def finish_generation(
    span: SpanHandle, provider: str, model: str, reply: object, result: str
) -> None:
    """Never attach messages, response bodies, exception strings or request IDs."""
    fields = {
        "provider": provider,
        "configured_model": model,
        "actual_model": getattr(reply, "actual_model", None),
        "input_tokens": getattr(reply, "prompt_tokens", None),
        "output_tokens": getattr(reply, "completion_tokens", None),
        "total_tokens": getattr(reply, "total_tokens", None),
        "cached_input_tokens": getattr(reply, "cached_input_tokens", None),
        "reasoning_tokens": getattr(reply, "reasoning_tokens", None),
        "provider_http_status": getattr(reply, "http_status", None),
        "retry_count": 0,
        "result": result,
        "latency_ms": span.elapsed_ms,
        "model_call_latency_ms": getattr(reply, "model_call_latency_ms", None),
        "error_class": {
            "timeout": "TIMEOUT",
            "http_error": "HTTP_ERROR",
            "network_error": "NETWORK_ERROR",
            "invalid_response": "INVALID_RESPONSE",
            "incomplete": "INCOMPLETE",
            "refusal": "REFUSAL",
        }.get(getattr(reply, "status", None)),
    }
    span.enrich(**fields)
    cost = llm_cost(
        getattr(reply, "actual_model", None) or model,
        getattr(reply, "prompt_tokens", None),
        getattr(reply, "completion_tokens", None),
        getattr(reply, "cached_input_tokens", None),
    )
    if cost is not None:
        span.enrich(cost_usd=cost)
    if result != "OK":
        span.set_status("ERROR")


def normalized_result(status: str) -> str:
    if status in {"accepted", "no_name", "completed"}:
        return "OK"
    if status == "timeout":
        return "TIMEOUT"
    if status in {"invalid_response", "incomplete", "rejected"}:
        return "INVALID"
    return "ERROR"
