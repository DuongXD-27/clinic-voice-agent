import json
import logging
import unicodedata
from datetime import date
from unittest.mock import patch

import httpx
import pytest
from pydantic import ValidationError

from callbot.engine import EngineSettings, create_orchestrator
from callbot.engine.extraction import InformationExtractor, Intent, Provenance, QuestionId
from callbot.engine.extraction.ner import NameNER
from callbot.engine.types import CallerInput, CallStart
from clinic_mock_sim import FakeClinicAPI
from inference.llm.config import OpenAIConfig
from inference.llm.gateway import create_gateway
from inference.llm.prompt.ner import FEW_SHOTS, PROMPT_VERSION, build_messages
from tests.engine.extraction.test_extractor import ctx

TRANSCRIPT = "À ừ thì là Nguyễn Văn A nhé em"
KEY = "synthetic-test-secret"


def completion(name="Nguyễn Văn A", span="Nguyễn Văn A", **choice_changes):
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": json.dumps({"full_name": name, "span": span})},
                **choice_changes,
            }
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 20},
    }


def adapter_for(handler):
    clients = []

    def factory():
        client = httpx.Client(transport=httpx.MockTransport(handler))
        clients.append(client)
        return client

    config = OpenAIConfig(api_key=KEY, _env_file=None)
    return NameNER(create_gateway("openai", config=config, client_factory=factory)), clients


def test_request_contract_and_private_telemetry(caplog):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=completion())

    adapter, clients = adapter_for(handle)
    with caplog.at_level(logging.INFO, logger="callbot.engine.extraction.ner"):
        result = adapter.full_name(TRANSCRIPT)
    assert result.value == result.span == "nguyễn văn a"
    assert result.provenance is Provenance.FALLBACK
    assert len(requests) == 1 and clients[0].is_closed
    request = requests[0]
    assert str(request.url) == OpenAIConfig.endpoint and request.method == "POST"
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    assert request.extensions["timeout"] == {"connect": 1.0, "read": 3.0, "write": 3.0, "pool": 3.0}
    payload = json.loads(request.content)
    assert payload["model"] == "gpt-4o-mini"
    assert payload["temperature"] == 0
    assert payload["max_completion_tokens"] == 200
    assert payload["store"] is False
    assert payload["messages"] == build_messages(TRANSCRIPT)
    assert len(payload["messages"]) == 2 * len(FEW_SHOTS) + 2
    schema = payload["response_format"]["json_schema"]
    assert schema["strict"] is True and schema["name"] == PROMPT_VERSION
    assert schema["schema"]["additionalProperties"] is False
    assert set(schema["schema"]["required"]) == {"full_name", "span"}
    record = next(r for r in caplog.records if hasattr(r, "ner_status"))
    assert record.ner_status == "accepted"
    assert record.ner_prompt_tokens == 120 and record.ner_completion_tokens == 20
    assert record.ner_elapsed_ms >= 0
    assert record.ner_prompt_version == PROMPT_VERSION
    for private in (KEY, TRANSCRIPT, "Nguyễn Văn A", "nguyễn văn a"):
        assert private not in str(record.__dict__)


@pytest.mark.parametrize(
    "transcript,name,expected",
    [
        (TRANSCRIPT, "Nguyễn Văn A", "nguyễn văn a"),
        (unicodedata.normalize("NFD", TRANSCRIPT), "Nguyễn Văn A", "nguyễn văn a"),
        ("À tôi tên Lê Thị Hoà em nhé", "Lê Thị Hoà", "lê thị hòa"),
        ("a u thi ten toi la nguyen van a nhe em", "nguyen van a", "nguyen van a"),
        ("Nguyễn Thị Nha", "Nguyễn Thị Nha", "nguyễn thị nha"),
        ("Lê Nha", "Lê Nha", "lê nha"),
    ],
)
def test_normalizes_only_existing_name(transcript, name, expected):
    adapter, _ = adapter_for(lambda _: httpx.Response(200, json=completion(name, name)))
    assert adapter.full_name(transcript).value == expected


@pytest.mark.parametrize(
    "name,span,transcript",
    [
        ("Trần Văn B", "Trần Văn B", TRANSCRIPT),
        ("Nguyễn Văn A", "Trần Văn B", TRANSCRIPT),
        ("Nguyễn Văn A", "Nguyễn Văn A", "toi ten la nguyen van a"),
        ("Nguyễn Văn A", "Nguyễn Văn A", "tôi là Nguyễn Văn An"),
        ("tôi là Nguyễn Văn A", "tôi là Nguyễn Văn A", "tôi là Nguyễn Văn A"),
        ("Nguyễn 123", "Nguyễn 123", "tôi là Nguyễn 123"),
        ("Hoa", "Hoa", "tôi là Hoa"),
        ("Nguyễn Văn A nhé em", "Nguyễn Văn A nhé em", "Nguyễn Văn A nhé em"),
        ("", "", TRANSCRIPT),
        (None, "Nguyễn Văn A", TRANSCRIPT),
        ("Nguyễn Văn A", None, TRANSCRIPT),
        (123, 123, TRANSCRIPT),
    ],
)
def test_rejects_ungrounded_or_invalid_name(name, span, transcript):
    adapter, _ = adapter_for(lambda _: httpx.Response(200, json=completion(name, span)))
    result = adapter.full_name(transcript)
    assert result.value is None and result.provenance is Provenance.NONE


@pytest.mark.parametrize(
    "body",
    [
        completion(None, None),
        completion(finish_reason="length"),
        completion(finish_reason="content_filter"),
        completion(message={"refusal": "Cannot comply", "content": None}),
        completion(message={"content": None}),
        completion(message={"content": "not json"}),
        completion(message={"content": '{"full_name":"Nguyễn Văn A"}'}),
        completion(message={"content": '{"full_name":null,"span":null,"extra":1}'}),
        {"choices": []},
        {"choices": "invalid"},
        [],
    ],
)
def test_unusable_responses_return_none(body):
    adapter, clients = adapter_for(lambda _: httpx.Response(200, json=body))
    assert not adapter.full_name(TRANSCRIPT).found
    assert len(clients) == 1 and clients[0].is_closed


@pytest.mark.parametrize("error", ["timeout", "network", "json", 401, 429, 500, 503])
def test_api_failures_do_not_retry_or_leak_details(error, caplog):
    attempts = []

    def handle(request):
        attempts.append(request)
        if error == "timeout":
            raise httpx.ReadTimeout(KEY, request=request)
        if error == "network":
            raise httpx.ConnectError(KEY, request=request)
        if error == "json":
            return httpx.Response(200, content=KEY)
        return httpx.Response(error, text=KEY)

    adapter, clients = adapter_for(handle)
    with caplog.at_level(logging.INFO):
        assert not adapter.full_name(TRANSCRIPT).found
    assert len(attempts) == 1 and clients[0].is_closed
    assert KEY not in caplog.text and TRANSCRIPT not in caplog.text


@pytest.mark.parametrize(
    "question,text,silence,enabled",
    [
        (QuestionId.ASK_NAME, TRANSCRIPT, 0, False),
        (QuestionId.ASK_NAME, "Nguyễn Văn A", 0, True),
        (QuestionId.ASK_DOB, TRANSCRIPT, 0, True),
        (QuestionId.ASK_INTENT, TRANSCRIPT, 0, True),
        (QuestionId.CONFIRM_READBACK, "có lẽ", 0, True),
        (QuestionId.ASK_NAME, TRANSCRIPT, 1000, True),
        (QuestionId.ASK_NAME, "", 0, True),
        (QuestionId.ASK_NAME, "   ", 0, True),
        (QuestionId.ASK_NAME, "cho tôi gặp nhân viên", 0, True),
        (QuestionId.ASK_NAME, "tôi là vợ anh ấy", 0, True),
        (QuestionId.ASK_NAME, "tôi đang khó thở", 0, True),
        (QuestionId.ASK_NAME, "tôi nên uống thuốc gì", 0, True),
        (QuestionId.ASK_NAME, "Ai đấy?", 0, True),
        (QuestionId.ASK_NAME, "ai the", 0, True),
        (QuestionId.ASK_NAME, "Dạ, cho hỏi ai đấy ạ?", 0, True),
        (QuestionId.ASK_NAME, "Nguyễn Văn A nhé em", 0, True),
    ],
)
def test_state_and_rule_gates_make_no_http_request(question, text, silence, enabled):
    def unexpected_request(_):
        pytest.fail("Unexpected OpenAI request")

    adapter, clients = adapter_for(unexpected_request)
    extractor = InformationExtractor(fallback=adapter, name_fallback=enabled)
    extractor.extract(ctx(question), text, silence_ms=silence)
    assert clients == []
    assert adapter.intent(text, frozenset({Intent.CANCEL})) is None
    assert adapter.agreement(text, question) is None


def test_settings_validate_activation_and_hide_secret(monkeypatch):
    assert EngineSettings(_env_file=None).name_fallback_provider == "none"
    with pytest.raises(ValidationError, match="requires OPENAI_API_KEY"):
        OpenAIConfig(api_key=" ", _env_file=None)
    monkeypatch.setenv("NAME_FALLBACK_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    monkeypatch.setenv("NAME_FALLBACK_TIMEOUT_S", "2.5")
    config = OpenAIConfig(_env_file=None)
    assert config.timeout_s == 2.5
    assert KEY not in repr(config)
    assert config.api_key.get_secret_value() == KEY


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_settings_reject_invalid_timeout(timeout):
    with pytest.raises(ValidationError):
        OpenAIConfig(api_key=KEY, timeout_s=timeout, _env_file=None)


@pytest.mark.parametrize("success", [True, False])
@pytest.mark.parametrize("transcript", [TRANSCRIPT, "Nguyễn Văn A đúng rồi"])
def test_orchestrator_uses_normalized_name_or_reprompts(success, transcript, monkeypatch):
    adapter, clients = adapter_for(
        lambda _: httpx.Response(200, json=completion()) if success else httpx.Response(503)
    )
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    settings = EngineSettings(name_fallback_provider="openai", _env_file=None)
    with patch("callbot.engine.create_gateway", return_value=adapter._gateway) as factory:
        bot = create_orchestrator(FakeClinicAPI(), settings=settings)
    factory.assert_called_once_with("openai")
    bot.start_call(CallStart(call_id="ner", direction="inbound", caller_number="0912345600"))
    action = bot.handle_turn("ner", CallerInput(turn=1, text=transcript))
    assert action.state == "AWAITING_IDENTITY"
    session = bot.sessions.store.get_session("ner")
    assert session.context["identity_step"] == ("ASK_DOB" if success else "ASK_NAME")
    assert len(clients) == 1 and clients[0].is_closed
    if success:
        verifier = bot._dialogue._verifier
        received = []
        original = verifier.verify

        def record(context):
            received.append((context.claimed_name, context.claimed_dob))
            return original(context)

        with patch.object(verifier, "verify", side_effect=record):
            bot.handle_turn("ner", CallerInput(turn=2, text="14/03/1978"))
        assert received == [("nguyễn văn a", date(1978, 3, 14))]
        # Replaying the committed first turn must not spend another model request.
        bot.handle_turn("ner", CallerInput(turn=1, text=transcript))
        assert len(clients) == 1


def test_orchestrator_accepts_name_ending_in_nha_from_ner(monkeypatch):
    name = "Nguyễn Văn Nha"
    adapter, _ = adapter_for(lambda _: httpx.Response(200, json=completion(name, name)))
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    settings = EngineSettings(name_fallback_provider="openai", _env_file=None)
    with patch("callbot.engine.create_gateway", return_value=adapter._gateway):
        bot = create_orchestrator(FakeClinicAPI(), settings=settings)

    bot.start_call(CallStart(call_id="ner-nha", direction="inbound", caller_number="0912345600"))
    run = bot.handle_turn_with_details("ner-nha", CallerInput(turn=1, text=name))

    assert run.action.state == "AWAITING_IDENTITY"
    assert bot.sessions.store.get_session("ner-nha").context["identity_step"] == "ASK_DOB"
    assert run.extraction["full_name"]["value"] == "nguyễn văn nha"
    assert run.extraction["full_name"]["provenance"] == "FALLBACK"


def test_disabled_provider_does_not_construct_adapter():
    with patch("callbot.engine.create_gateway") as factory:
        create_orchestrator(
            FakeClinicAPI(),
            settings=EngineSettings(name_fallback_provider="none", _env_file=None),
        )
    factory.assert_not_called()


def test_enabled_provider_requires_key_at_orchestrator_startup():
    settings = EngineSettings(name_fallback_provider="openai", _env_file=None)
    with pytest.raises(ValidationError, match="requires OPENAI_API_KEY"):
        create_orchestrator(FakeClinicAPI(), settings=settings)
