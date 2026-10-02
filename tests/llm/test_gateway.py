import gzip
import json
from unittest.mock import patch

import httpx
import pytest
import yaml
from pydantic import ValidationError

from appconfig import CONFIG_DIR
from callbot.engine import EngineSettings, create_orchestrator
from callbot.engine.extraction.name_slot_filling import NameExtraction, NameSlotFiller
from callbot.engine.types import CallerInput, CallStart
from clinic_mock_sim import FakeClinicAPI
from inference.llm.config import GeminiConfig, GroqConfig, OpenAIConfig, OpenRouterConfig
from inference.llm.gateway import create_gateway
from inference.llm.prompt.name_slot_filling import build_messages

# Default model / token budget per provider come from config/llm.yaml, not from the code.
_LLM_YAML = yaml.safe_load((CONFIG_DIR / "llm.yaml").read_text(encoding="utf-8"))
CONFIGS = {
    provider: (cls, _LLM_YAML[provider]["model"], _LLM_YAML[provider]["max_completion_tokens"])
    for provider, cls in {
        "openai": OpenAIConfig,
        "gemini": GeminiConfig,
        "groq": GroqConfig,
        "openrouter": OpenRouterConfig,
    }.items()
}
NAME = "Nguyễn Văn A"
TEXT = "À ừ thì là Nguyễn Văn A nhé em"
OUTPUT = json.dumps({"full_name": NAME, "span": NAME}, ensure_ascii=False)
SECRET = "synthetic-provider-key"


def response_body(provider, content=OUTPUT):
    if provider == "gemini":
        return {
            "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": content}]}}],
            "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 15},
        }
    return {
        "choices": [{"finish_reason": "stop", "message": {"content": content}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 15},
    }


@pytest.fixture(autouse=True)
def provider_defaults_from_yaml(monkeypatch):
    """Blank env means config/llm.yaml per-provider values (conftest pins an OpenAI model)."""
    monkeypatch.setenv("NAME_FALLBACK_MODEL", "")
    monkeypatch.setenv("NAME_FALLBACK_MAX_TOKENS", "")


def endpoint(provider):
    return CONFIGS[provider][0](api_key=SECRET, _env_file=None).endpoint


def mocked_gateway(provider, handler, **overrides):
    config_class, _, _ = CONFIGS[provider]
    config = config_class(_env_file=None, api_key=SECRET, **overrides)
    clients = []

    def factory():
        client = httpx.Client(transport=httpx.MockTransport(handler))
        clients.append(client)
        return client

    return create_gateway(provider, config=config, client_factory=factory), clients


def generate(gateway, **kwargs):
    return gateway.generate_structured(
        build_messages(TEXT),
        schema=NameExtraction.model_json_schema(),
        schema_name="name_slot_filling_v1",
        **kwargs,
    )


@pytest.mark.parametrize(
    "model,effort", [("gpt-6-luna", "none"), ("gpt-6-sol", "none"), ("gpt-6-astra", None)]
)
def test_gpt_6_omits_unsupported_temperature(model, effort):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=response_body("openai"))

    gateway, _ = mocked_gateway("openai", handle, model=model)
    assert generate(gateway).status == "completed"
    payload = json.loads(requests[0].content)
    assert payload["model"] == model
    assert "temperature" not in payload
    if effort is None:
        assert "reasoning_effort" not in payload
    else:
        assert payload["reasoning_effort"] == effort
    assert payload["store"] is False


@pytest.mark.parametrize("provider", CONFIGS)
def test_gateway_calls_correct_provider_and_normalizes_usage(provider):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=response_body(provider))

    gateway, clients = mocked_gateway(provider, handle, timeout_s=2.5)
    reply = generate(gateway)
    assert reply.status == "completed" and reply.content == OUTPUT
    assert reply.prompt_tokens == 100 and reply.completion_tokens == 15
    assert gateway.provider_name == provider
    assert gateway.model == CONFIGS[provider][1]
    assert len(requests) == 1 and clients[0].is_closed
    request = requests[0]
    payload = json.loads(request.content)
    assert request.extensions["timeout"] == {"connect": 1.0, "read": 2.5, "write": 2.5, "pool": 2.5}
    assert SECRET not in str(request.url)
    if provider == "gemini":
        assert str(request.url) == f"{endpoint('gemini')}/{CONFIGS['gemini'][1]}:generateContent"
        assert request.headers["x-goog-api-key"] == SECRET
        assert "authorization" not in request.headers
        messages = build_messages(TEXT)
        assert payload["systemInstruction"] == {"parts": [{"text": messages[0]["content"]}]}
        assert payload["contents"] == [
            {
                "role": "model" if m["role"] == "assistant" else "user",
                "parts": [{"text": m["content"]}],
            }
            for m in messages[1:]
        ]
        assert payload["generationConfig"] == {
            "temperature": 0,
            "maxOutputTokens": CONFIGS["gemini"][2],
            "responseMimeType": "application/json",
            "responseJsonSchema": NameExtraction.model_json_schema(),
            "thinkingConfig": {"thinkingBudget": 0},
        }
    else:
        assert str(request.url) == endpoint(provider)
        assert request.headers["authorization"] == f"Bearer {SECRET}"
        assert payload["messages"] == build_messages(TEXT)
        assert payload["response_format"]["json_schema"] == {
            "name": "name_slot_filling_v1",
            "strict": True,
            "schema": NameExtraction.model_json_schema(),
        }
        if provider == "openai":
            assert payload["store"] is False
        else:
            assert "store" not in payload
        if provider == "groq":
            assert payload["max_completion_tokens"] == CONFIGS["groq"][2]
            assert payload["reasoning_effort"] == "low"
        elif provider == "openrouter":
            assert payload["max_tokens"] == CONFIGS["openrouter"][2]
            assert "max_completion_tokens" not in payload
            assert payload["provider"] == {"require_parameters": True, "allow_fallbacks": False}


@pytest.mark.parametrize("provider", CONFIGS)
def test_gateway_accepts_gzip_response_and_preserves_usage(provider):
    body = gzip.compress(json.dumps(response_body(provider)).encode())

    def handle(request):
        return httpx.Response(
            200,
            headers={"Content-Encoding": "gzip", "Content-Length": str(len(body))},
            stream=httpx.ByteStream(body),
        )

    gateway, _ = mocked_gateway(provider, handle)
    reply = generate(gateway)
    assert reply.status == "completed" and reply.content == OUTPUT
    assert reply.prompt_tokens == 100 and reply.completion_tokens == 15
    assert reply.model_call_latency_ms is not None


@pytest.mark.parametrize("provider", CONFIGS)
@pytest.mark.parametrize("error", ["timeout", "network", "json", 401, 429, 500])
def test_failures_are_uniform_and_never_retried(provider, error, caplog):
    requests = []

    def handle(request):
        requests.append(request)
        if error == "timeout":
            raise httpx.ReadTimeout(SECRET, request=request)
        if error == "network":
            raise httpx.ConnectError(SECRET, request=request)
        if error == "json":
            return httpx.Response(200, content=SECRET)
        return httpx.Response(error, text=SECRET)

    gateway, clients = mocked_gateway(provider, handle)
    reply = generate(gateway)
    expected = {"timeout": "timeout", "network": "network_error", "json": "invalid_response"}
    assert reply.status == expected.get(error, "http_error")
    assert reply.content is None
    assert len(requests) == 1 and clients[0].is_closed
    assert SECRET not in caplog.text


@pytest.mark.parametrize("provider", CONFIGS)
@pytest.mark.parametrize("content", ["not JSON", "", "```json\n{}\n```"])
def test_gateway_rejects_invalid_generated_json_and_keeps_usage(provider, content):
    gateway, _ = mocked_gateway(
        provider, lambda _: httpx.Response(200, json=response_body(provider, content))
    )
    reply = generate(gateway)
    assert reply.status == "invalid_response" and reply.content is None
    assert reply.prompt_tokens == 100


@pytest.mark.parametrize(
    "body,status",
    [
        ({"promptFeedback": {"blockReason": "SAFETY"}}, "refusal"),
        ({"candidates": [{"finishReason": "SAFETY"}]}, "refusal"),
        ({"candidates": [{"finishReason": "RECITATION"}]}, "refusal"),
        ({"candidates": [{"finishReason": "MAX_TOKENS"}]}, "incomplete"),
        ({"candidates": []}, "invalid_response"),
        ({"candidates": [{"finishReason": "STOP"}]}, "invalid_response"),
        (
            {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": "secret", "thought": True}]},
                    }
                ]
            },
            "invalid_response",
        ),
        ({"candidates": "bad"}, "invalid_response"),
        ([], "invalid_response"),
    ],
)
def test_gemini_refusal_incomplete_and_malformed(body, status):
    gateway, _ = mocked_gateway("gemini", lambda _: httpx.Response(200, json=body))
    reply = generate(gateway)
    assert reply.status == status and reply.content is None


def test_gemini_ignores_thought_parts_and_counts_reasoning_tokens():
    body = response_body("gemini")
    body["candidates"][0]["content"]["parts"] = [
        {"text": "private reasoning", "thought": True},
        {"text": OUTPUT[:15]},
        {"text": OUTPUT[15:]},
    ]
    body["usageMetadata"]["thoughtsTokenCount"] = 9
    gateway, _ = mocked_gateway("gemini", lambda _: httpx.Response(200, json=body))
    reply = generate(gateway)
    assert reply.content == OUTPUT and reply.completion_tokens == 24


@pytest.mark.parametrize("provider", CONFIGS)
def test_gateway_model_and_token_override(provider):
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=response_body(provider))

    gateway, _ = mocked_gateway(provider, handle, model="custom-model", max_completion_tokens=350)
    generate(gateway)
    generate(gateway, max_completion_tokens=450)
    assert gateway.model == "custom-model"
    if provider == "gemini":
        assert [r["generationConfig"]["maxOutputTokens"] for r in requests] == [350, 450]
        assert all("thinkingConfig" not in r["generationConfig"] for r in requests)
    else:
        key = "max_tokens" if provider == "openrouter" else "max_completion_tokens"
        assert [r[key] for r in requests] == [350, 450]
        assert all(r["model"] == "custom-model" for r in requests)


@pytest.mark.parametrize("provider", CONFIGS)
def test_only_selected_api_key_is_required(provider, monkeypatch):
    monkeypatch.setenv("NAME_FALLBACK_MODEL", "")
    monkeypatch.setenv("NAME_FALLBACK_MAX_TOKENS", "")
    for config, _, _ in CONFIGS.values():
        monkeypatch.setenv(config.key_env, "")
    with pytest.raises(ValidationError, match=CONFIGS[provider][0].key_env):
        create_gateway(provider)
    monkeypatch.setenv(CONFIGS[provider][0].key_env, SECRET)
    gateway = create_gateway(provider)
    assert gateway.model == CONFIGS[provider][1]


def test_gateway_rejects_mismatched_config_or_invalid_provider():
    with pytest.raises(ValueError, match="Unsupported"):
        create_gateway("unsupported")
    with pytest.raises(ValueError, match="does not match"):
        create_gateway("groq", config=OpenAIConfig(api_key=SECRET, _env_file=None))


def test_invalid_input_makes_no_request():
    gateway, clients = mocked_gateway("openai", lambda _: pytest.fail("Unexpected API request"))
    with pytest.raises(ValueError, match="positive"):
        generate(gateway, max_completion_tokens=0)
    with pytest.raises(ValueError, match="text messages"):
        gateway.generate_structured(
            [{"role": "tool", "content": "x"}], schema={}, schema_name="test"
        )
    assert not clients


@pytest.mark.parametrize("provider", CONFIGS)
def test_name_slot_filling_and_orchestrator_route_through_gateway(provider):
    gateway, clients = mocked_gateway(
        provider, lambda _: httpx.Response(200, json=response_body(provider))
    )
    adapter = NameSlotFiller(gateway)
    assert adapter.full_name(TEXT).field.value == "nguyễn văn a"
    with patch("callbot.engine.create_gateway", return_value=gateway) as factory:
        bot = create_orchestrator(
            FakeClinicAPI(),
            settings=EngineSettings(name_fallback_provider=provider, _env_file=None),
        )
    factory.assert_called_once_with(provider)
    bot.start_call(
        CallStart(call_id="gateway-slot-filling", direction="inbound", caller_number="0912345600")
    )
    action = bot.handle_turn("gateway-slot-filling", CallerInput(turn=1, text=TEXT))
    assert action.state == "AWAITING_IDENTITY"
    session = bot.sessions.store.get_session("gateway-slot-filling")
    assert session.context["claimed_name"] == "nguyễn văn a"
    assert session.context["identity_step"] == "ASK_DOB"
    assert len(clients) == 2 and all(client.is_closed for client in clients)
