"""Model observations use safe generation records; rule-only work emits none."""

import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from callbot.engine.extraction.fallback import SlotFillingStatus
from callbot.engine.extraction.name_slot_filling import NameSlotFiller
from callbot.engine.extraction.schema import Intent, QuestionId
from callbot.engine.extraction.semantic import LLMSemanticExtractor, SemanticContext
from callbot.observability.extended import extended_metrics
from callbot.observability.source import JsonlSpanSource
from callbot.tracing import Tracer
from callbot.tracing.langfuse_sink import _otlp_request
from callbot.tracing.pricing import PricingSettings, llm_cost, stt_cost, tts_cost
from callbot.tracing.privacy import SafeAttributes, UnsafeTraceData
from callbot.tracing.pseudonym import CallKeyFactory
from callbot.tracing.scores import EvaluatedScore, LangfuseScorePublisher, ScoreSettings
from inference.llm.gateway import LLMGateway
from inference.llm.providers.base import StructuredReply


class MemorySink:
    def __init__(self):
        self.records = []

    def emit(self, record):
        self.records.append(record)


@dataclass
class Provider:
    reply: StructuredReply
    model: str = "gpt-6-luna"
    calls: int = 0

    def generate_structured(self, messages, *, schema, schema_name, max_completion_tokens=200):
        self.calls += 1
        return self.reply


def _tracer(sink):
    return Tracer(
        sink,
        CallKeyFactory("generation-test-pseudonym-key-0000000", version="v1", environment="test"),
    )


def _context(text="tôi không đủ tiền"):
    return SemanticContext(
        transcript=text,
        question_id=QuestionId.CANCEL_RECONFIRM,
        direction="outbound",
        allowed_intents=(Intent.CANCEL,),
        route_reason="CANCEL_CONTRADICTION",
        pending_action="CANCEL",
    )


def _valid_reply():
    return StructuredReply(
        "completed",
        json.dumps(
            {
                "intent": None,
                "intent_span": None,
                "reply_kind": "INFORM_REASON",
                "reply_span": None,
                "cancel_reason": "COST",
                "reason_span": "không đủ tiền",
                "clinical": None,
                "clinical_span": None,
            }
        ),
        prompt_tokens=12,
        completion_tokens=6,
        total_tokens=18,
        actual_model="gpt-6-luna",
        http_status=200,
    )


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        (_valid_reply(), "OK"),
        (StructuredReply("timeout"), "TIMEOUT"),
        (StructuredReply("http_error", http_status=429), "ERROR"),
        (StructuredReply("completed", "{"), "INVALID"),
    ],
)
def test_semantic_generation_is_child_of_extraction_and_has_normalized_result(reply, expected):
    sink = MemorySink()
    tracer = _tracer(sink)
    provider = Provider(reply)
    adapter = LLMSemanticExtractor(
        LLMGateway(provider, provider_name="openai"),
        max_input_chars=1500,
        max_completion_tokens=400,
    )
    with tracer.start_trace(call_id="call-A", turn=1, component="TURN", operation="http.call_turn"):
        with tracer.span(component="CORE", operation="core.handle_turn"):
            with tracer.span(component="EXTRACTION", operation="core.extract"):
                adapter.analyze(_context())
    generation = next(item for item in sink.records if item.observation_type == "GENERATION")
    extraction = next(item for item in sink.records if item.operation == "core.extract")
    assert generation.operation == "llm.semantic_extract"
    assert generation.parent_span_id == extraction.span_id
    assert generation.attributes["result"] == expected
    assert generation.attributes["configured_model"] == "gpt-6-luna"
    assert generation.attributes["latency_ms"] >= 0
    assert generation.status == ("OK" if expected == "OK" else "ERROR")
    assert _otlp_request([generation], "test")["resourceSpans"][0]["scopeSpans"][0]["spans"][0][
        "status"
    ] == {"code": 1 if expected == "OK" else 2}
    if expected == "OK":
        assert generation.attributes["input_tokens"] == 12
        assert generation.attributes["output_tokens"] == 6
    assert provider.calls == 1
    payload = _otlp_request([generation], "test")
    attributes = {
        item["key"]: next(iter(item["value"].values()))
        for item in payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]
    }
    assert attributes["langfuse.observation.type"] == "generation"
    assert attributes["langfuse.observation.model.name"] == "gpt-6-luna"
    if expected == "OK":
        assert json.loads(attributes["langfuse.observation.usage_details"]) == {
            "input": 12,
            "output": 6,
            "total": 18,
        }


def test_langfuse_usage_buckets_do_not_double_count_cache_or_reasoning():
    sink = MemorySink()
    tracer = _tracer(sink)
    with tracer.start_trace(
        call_id="usage-buckets", turn=1, component="TURN", operation="http.call_turn"
    ):
        with tracer.generation(component="LLM", operation="llm.semantic_extract") as generation:
            generation.enrich(
                input_tokens=100,
                cached_input_tokens=30,
                output_tokens=40,
                reasoning_tokens=15,
                total_tokens=140,
            )
    record = next(item for item in sink.records if item.observation_type == "GENERATION")
    attrs = {
        item["key"]: next(iter(item["value"].values()))
        for item in _otlp_request([record], "test")["resourceSpans"][0]["scopeSpans"][0]["spans"][
            0
        ]["attributes"]
    }
    assert json.loads(attrs["langfuse.observation.usage_details"]) == {
        "input": 70,
        "input_cached_tokens": 30,
        "output": 25,
        "output_reasoning_tokens": 15,
        "total": 140,
    }


def test_model_call_latency_is_separate_safe_generation_metadata():
    sink = MemorySink()
    tracer = _tracer(sink)
    adapter = LLMSemanticExtractor(
        LLMGateway(
            Provider(replace(_valid_reply(), model_call_latency_ms=2950.0)), provider_name="openai"
        ),
        max_input_chars=1500,
        max_completion_tokens=400,
    )
    with tracer.start_trace(
        call_id="latency-synthetic", turn=1, component="TURN", operation="http.call_turn"
    ):
        adapter.analyze(_context())
    generation = next(item for item in sink.records if item.observation_type == "GENERATION")
    assert generation.status == "OK"
    assert generation.attributes["result"] == "OK"
    assert generation.attributes["model_call_latency_ms"] == 2950.0
    assert generation.attributes["latency_ms"] >= 0
    model_call_latency = extended_metrics(sink.records)["llm_model_call_latency"]
    assert model_call_latency["count"] == 1
    assert model_call_latency["p95_ms"] == 2950.0
    attrs = {
        item["key"]: next(iter(item["value"].values()))
        for item in _otlp_request([generation], "test")["resourceSpans"][0]["scopeSpans"][0][
            "spans"
        ][0]["attributes"]
    }
    assert attrs["langfuse.observation.metadata.model_call_latency_ms"] == 2950.0


def test_model_call_latency_summary_excludes_unmeasured_generations():
    sink = MemorySink()
    tracer = _tracer(sink)
    with tracer.start_trace(
        call_id="legacy-generation", turn=1, component="TURN", operation="http.call_turn"
    ):
        with tracer.generation(component="LLM", operation="llm.semantic_extract"):
            pass
    metrics = extended_metrics(sink.records)
    assert metrics["llm_latency"]["count"] == 1
    assert metrics["llm_model_call_latency"]["count"] == 0
    assert metrics["llm_model_call_latency"]["p95_ms"] is None


def test_rule_only_and_skipped_name_do_not_create_generation():
    sink = MemorySink()
    tracer = _tracer(sink)
    provider = Provider(_valid_reply())
    semantic = LLMSemanticExtractor(
        LLMGateway(provider, provider_name="openai"),
        max_input_chars=1500,
        max_completion_tokens=400,
    )
    name = NameSlotFiller(LLMGateway(provider, provider_name="openai"))
    with tracer.start_trace(call_id="call-A", turn=1, component="TURN", operation="http.call_turn"):
        with tracer.span(component="EXTRACTION", operation="core.extract"):
            semantic.analyze(_context(" "))
            name.full_name("", question_id=QuestionId.ASK_NAME)
    assert provider.calls == 0
    assert all(item.observation_type == "SPAN" for item in sink.records)


def test_name_slot_has_distinct_private_generation():
    sink = MemorySink()
    tracer = _tracer(sink)
    private_name = "Nguyễn Thị Bí Mật"
    provider = Provider(
        StructuredReply("completed", json.dumps({"full_name": private_name, "span": private_name}))
    )
    filler = NameSlotFiller(LLMGateway(provider, provider_name="openai"))
    with tracer.start_trace(
        call_id="call-private", turn=1, component="TURN", operation="http.call_turn"
    ):
        with tracer.span(component="EXTRACTION", operation="core.extract"):
            result = filler.full_name(private_name, question_id=QuestionId.ASK_NAME)
    assert result.status is SlotFillingStatus.ACCEPTED
    assert result.field.value == private_name.lower()
    generation = next(item for item in sink.records if item.observation_type == "GENERATION")
    assert generation.operation == "llm.name_slot_fill"
    assert generation.attributes["result"] == "OK"
    serialized = json.dumps([item.to_dict() for item in sink.records], ensure_ascii=False)
    exported = json.dumps(_otlp_request(sink.records, "test"), ensure_ascii=False)
    for secret in (private_name, "call-private"):
        assert secret not in serialized + exported


@pytest.mark.parametrize(
    ("reply", "expected_slot", "expected_generation"),
    [
        (
            StructuredReply("completed", '{"full_name":null,"span":null}'),
            SlotFillingStatus.NO_NAME,
            "OK",
        ),
        (
            StructuredReply("completed", '{"full_name":"Trần Văn B","span":"Trần Văn B"}'),
            SlotFillingStatus.REJECTED,
            "INVALID",
        ),
        (StructuredReply("completed", "{"), SlotFillingStatus.UNAVAILABLE, "INVALID"),
        (StructuredReply("timeout"), SlotFillingStatus.UNAVAILABLE, "TIMEOUT"),
        (StructuredReply("http_error"), SlotFillingStatus.UNAVAILABLE, "ERROR"),
    ],
)
def test_name_slot_outcome_preserves_generation_result(reply, expected_slot, expected_generation):
    sink = MemorySink()
    tracer = _tracer(sink)
    provider = Provider(reply)
    filler = NameSlotFiller(LLMGateway(provider, provider_name="openai"))
    with tracer.start_trace(call_id="call-A", turn=1, component="TURN", operation="http.call_turn"):
        with tracer.span(component="EXTRACTION", operation="core.extract"):
            result = filler.full_name("Nguyễn Văn A", question_id=QuestionId.ASK_NAME)
    assert result.status is expected_slot
    assert not result.field.found
    assert result.elapsed_ms is not None and result.elapsed_ms >= 0
    generations = [item for item in sink.records if item.observation_type == "GENERATION"]
    assert len(generations) == provider.calls == 1
    generation = generations[0]
    extraction = next(item for item in sink.records if item.operation == "core.extract")
    assert generation.parent_span_id == extraction.span_id
    assert generation.attributes["result"] == expected_generation
    assert generation.status == ("OK" if expected_generation == "OK" else "ERROR")


def test_cost_unknown_is_distinct_from_zero(monkeypatch):
    import callbot.tracing.pricing as prices

    monkeypatch.setattr(
        prices,
        "pricing",
        lambda: PricingSettings(
            llm_model="gpt-6-luna",
            llm_input_usd_per_million=1.0,
            llm_output_usd_per_million=2.0,
            tts_provider="vbee",
            tts_voice="voice-a",
            tts_usd_per_character=0.01,
        ),
    )
    assert llm_cost("gpt-6-luna", 100, 50) == pytest.approx(0.0002)
    assert tts_cost("vbee", "voice-a", 3) == pytest.approx(0.03)
    assert stt_cost("gipformer", 1000) is None
    sink = MemorySink()
    tracer = _tracer(sink)
    with tracer.start_trace(call_id="call-A", turn=1, component="TURN", operation="http.call_turn"):
        with tracer.span(component="STT", operation="speech.stt.transcribe"):
            pass
        with tracer.generation(component="LLM", operation="llm.semantic_extract") as generation:
            generation.enrich(cost_usd=0.0002, result="OK")
    summary = extended_metrics(sink.records)["cost"]
    assert summary["known_cost_total"] == pytest.approx(0.0002)
    assert summary["cost_complete"] is False


def test_session_cost_separates_known_zero_partial_and_unknown():
    sink = MemorySink()
    tracer = _tracer(sink)
    with tracer.start_trace(call_id="zero", turn=1, component="TURN", operation="http.call_turn"):
        for component, operation in (
            ("STT", "speech.stt.transcribe"),
            ("LLM", "llm.semantic_extract"),
            ("TTS", "speech.tts.synthesize"),
        ):
            with tracer.span(component=component, operation=operation) as span:
                span.enrich(cost_usd=0.0)
    with tracer.start_trace(
        call_id="partial", turn=1, component="TURN", operation="http.call_turn"
    ):
        with tracer.generation(component="LLM", operation="llm.semantic_extract") as span:
            span.enrich(cost_usd=0.2)
        with tracer.span(component="TTS", operation="speech.tts.synthesize") as span:
            span.enrich(cost_usd=0.3)
        with tracer.span(component="STT", operation="speech.stt.transcribe"):
            pass
    with tracer.start_trace(
        call_id="unknown", turn=1, component="TURN", operation="http.call_turn"
    ):
        with tracer.span(component="STT", operation="speech.stt.transcribe"):
            pass
    sessions = {row["call_key"]: row for row in extended_metrics(sink.records)["cost"]["sessions"]}
    zero = sessions[tracer._call_keys.create("zero")]
    partial = sessions[tracer._call_keys.create("partial")]
    unknown = sessions[tracer._call_keys.create("unknown")]
    assert zero["known_cost_total"] == 0 and zero["cost_known"] and zero["cost_complete"]
    assert partial["known_cost_total"] == pytest.approx(0.5)
    assert partial["cost_known"] and not partial["cost_complete"]
    assert unknown["known_cost_total"] == 0 and not unknown["cost_known"]
    assert not unknown["cost_complete"]


def test_stt_provider_latency_is_distinct_from_streaming_event_offsets():
    sink = MemorySink()
    tracer = _tracer(sink)
    with tracer.start_trace(call_id="batch", turn=1, component="TURN", operation="http.call_turn"):
        with tracer.span(component="STT", operation="speech.stt.transcribe") as stt:
            stt.enrich(input_mode="batch", provider_latency_ms=12.0, audio_duration_ms=1000)
    with tracer.start_trace(
        call_id="stream", turn=1, component="TURN", operation="livekit.call_turn"
    ):
        with tracer.span(component="STT", operation="speech.stt.transcribe") as stt:
            stt.enrich(
                input_mode="streaming",
                first_partial_ms=100.0,
                final_ms=500.0,
                audio_duration_ms=300,
            )
    metrics = extended_metrics(sink.records)
    assert metrics["stt_provider_latency"]["count"] == 1
    assert metrics["stt_provider_latency"]["p95_ms"] == 12
    assert metrics["stt_first_partial"]["p95_ms"] == 100
    assert metrics["stt_final_latency"]["p95_ms"] == 500


def test_score_bridge_disabled_enabled_and_network_failure(tmp_path):
    score = EvaluatedScore("contract_pass", True, trace_id="a" * 32)
    requests = []

    def ok(request):
        requests.append(request)
        return httpx.Response(201, request=request)

    client = httpx.Client(transport=httpx.MockTransport(ok))
    from pydantic import SecretStr

    from callbot.tracing.langfuse_sink import LangfuseOtlpSettings

    config = LangfuseOtlpSettings(
        enabled=True,
        endpoint="https://example.test/api/public/otel",
        public_key=SecretStr("pk-test"),
        secret_key=SecretStr("sk-test"),
        timeout_seconds=1,
        queue_size=4,
        batch_size=2,
        flush_interval_seconds=1,
        environment="test",
    )
    assert (
        LangfuseScorePublisher(ScoreSettings(enabled=False), config, client).publish(score) is False
    )
    assert requests == []
    assert (
        LangfuseScorePublisher(
            ScoreSettings(enabled=True, jsonl_dir=tmp_path), config, client
        ).publish(score)
        is True
    )
    assert json.loads(requests[0].content) == {
        "name": "contract_pass",
        "value": 1,
        "dataType": "BOOLEAN",
        "traceId": "a" * 32,
    }
    now = datetime.now(timezone.utc)
    scores = list(
        JsonlSpanSource(tmp_path).query_scores(
            now - timedelta(minutes=1), now + timedelta(minutes=1)
        )
    )
    assert len(scores) == 1
    assert extended_metrics([], scores=scores)["evaluation"] == {
        "score_count": 1,
        "by_name": {"contract_pass": 1},
        "langfuse_published_count": 1,
        "local_only_count": 0,
    }
    failing = httpx.Client(
        transport=httpx.MockTransport(lambda _request: (_ for _ in ()).throw(OSError("offline")))
    )
    assert (
        LangfuseScorePublisher(
            ScoreSettings(enabled=True, jsonl_dir=tmp_path), config, failing
        ).publish(score)
        is False
    )
    scores = list(
        JsonlSpanSource(tmp_path).query_scores(
            now - timedelta(minutes=1), now + timedelta(minutes=1)
        )
    )
    assert [row["langfuse_published"] for row in scores] == [True, False]
    client.close()
    failing.close()


def test_score_requires_explicit_pseudonymous_correlation():
    with pytest.raises(ValueError):
        EvaluatedScore("task_success", True)
    with pytest.raises(ValueError):
        EvaluatedScore("task_success", True, session_id="raw-call-id")
    with pytest.raises(ValueError):
        EvaluatedScore("task_success", True, trace_id="a" * 32, session_id="ck_v1_raw")
    session = CallKeyFactory(
        "score-pseudonym-key-000000000000000", version="v1", environment="test"
    ).create("patient_24680")
    score = EvaluatedScore("task_success", True, session_id=session)
    assert "patient_24680" not in json.dumps(score.__dict__)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("actual_model", "Nguyễn Thị Bí Mật"),
        ("actual_model", "patient_12345"),
        ("provider_actual", "+84912345678 secret"),
        ("provider_actual", "+84912345678"),
        ("voice", "voice with patient name"),
        ("confidence", 1.5),
    ],
)
def test_dynamic_trace_labels_reject_sensitive_values(field, value):
    with pytest.raises(UnsafeTraceData):
        SafeAttributes.for_span(**{field: value})


def test_export_payload_golden_privacy_with_synthetic_patient_data():
    private = {
        "full_name": "Nguyễn Thị Bí Mật",
        "dob": "1985-04-23",
        "phone": "+84912345678",
        "patient_id": "patient_24680",
        "appointment_id": "apt_13579",
        "transcript": "Tôi là Nguyễn Thị Bí Mật",
        "prompt": "Tên người bệnh Nguyễn Thị Bí Mật",
        "response": "Lịch hẹn của Nguyễn Thị Bí Mật",
    }
    sink = MemorySink()
    tracer = _tracer(sink)
    with tracer.start_trace(
        call_id=private["phone"], turn=1, component="TURN", operation="http.call_turn"
    ) as root:
        root.enrich(**private)
        with tracer.generation(component="LLM", operation="llm.semantic_extract") as generation:
            generation.enrich(provider="openai", configured_model="gpt-6-luna", result="OK")
            generation.enrich(actual_model=private["patient_id"])
    exported = json.dumps(_otlp_request(sink.records, "test"), ensure_ascii=False)
    serialized = json.dumps([item.to_dict() for item in sink.records], ensure_ascii=False)
    for value in private.values():
        assert value not in exported + serialized


def test_jsonl_reader_accepts_historical_spans_and_new_generations(tmp_path):
    sink = MemorySink()
    tracer = _tracer(sink)
    with tracer.start_trace(
        call_id="read-test", turn=1, component="TURN", operation="http.call_turn"
    ):
        with tracer.generation(component="LLM", operation="llm.semantic_extract") as generation:
            generation.enrich(provider="openai", configured_model="gpt-6-luna", result="OK")
    path = tmp_path / "trace-20260930-p1.jsonl"
    path.write_text(
        "\n".join(json.dumps(item.to_dict()) for item in sink.records) + "\n", encoding="utf-8"
    )
    now = datetime.now(timezone.utc)
    rows = list(
        JsonlSpanSource(tmp_path).query(now - timedelta(minutes=1), now + timedelta(minutes=1))
    )
    assert {item.observation_type for item in rows} == {"SPAN", "GENERATION"}
    assert next(
        item for item in rows if item.observation_type == "GENERATION"
    ).parent_span_id == next(item.span_id for item in rows if item.observation_type == "SPAN")
