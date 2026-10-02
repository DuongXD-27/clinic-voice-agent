import json
from uuid import uuid4

import fakeredis
from fastapi.testclient import TestClient
from tests.transports.http.fakes import make_speech_bundle

from callbot.engine import CallerInput, CallStart, EngineSettings, create_orchestrator
from callbot.engine.policy.guardrails import SevereFailureBlocked
from callbot.tracing import Tracer
from callbot.tracing.langfuse_sink import _otlp_span
from callbot.tracing.models import CompletedSpan
from callbot.tracing.pseudonym import CallKeyFactory
from callbot.transports.http.call_mode import CallModeStore
from callbot.transports.http.main import create_app
from clinic_mock_sim import FakeClinicAPI, clinic_error


class MemorySink:
    def __init__(self, fail: bool = False) -> None:
        self.spans: list[CompletedSpan] = []
        self.fail = fail

    def emit(self, span: CompletedSpan) -> None:
        if self.fail:
            raise OSError("trace output unavailable")
        self.spans.append(span)


def _tracer(sink: MemorySink) -> Tracer:
    return Tracer(
        sink,
        CallKeyFactory("tracing-test-secret-key-0000000000", version="v1", environment="test"),
    )


def _start(bot, tracer: Tracer, call_id: str) -> None:
    with tracer.start_trace(call_id=call_id, turn=0, component="TURN", operation="http.start_call"):
        bot.start_call(
            CallStart(
                call_id=call_id,
                direction="outbound",
                appointment_id="apt_00417",
                caller_number="0912345600",
            )
        )


def _turn(bot, tracer: Tracer, call_id: str, turn: int, text: str):
    with tracer.start_trace(
        call_id=call_id, turn=turn, component="TURN", operation="http.call_turn"
    ):
        return bot.handle_turn(call_id, CallerInput(turn=turn, text=text))


def _records(sink: MemorySink) -> list[dict]:
    return [span.to_dict() for span in sink.spans]


def test_full_hierarchy_policy_fsm_session_and_privacy(redis_store_factory) -> None:
    sink = MemorySink()
    tracer = _tracer(sink)
    bot = create_orchestrator(FakeClinicAPI(), tracer=tracer, store=redis_store_factory())
    call_id = "private-call-id"
    _start(bot, tracer, call_id)
    action = _turn(bot, tracer, call_id, 1, "cho tôi gặp nhân viên")

    assert action.ended and action.outcome == "TRANSFERRED"
    transfer_turn = next(span for span in sink.spans if span.operation == "http.call_turn")
    assert transfer_turn.status == "OK"
    assert _otlp_span(transfer_turn, "test")["status"] == {"code": 1}
    records = _records(sink)
    turn = next(record for record in records if record["operation"] == "http.call_turn")
    core = next(
        record
        for record in records
        if record["operation"] == "core.handle_turn" and record["turn"] == 1
    )
    extraction = next(record for record in records if record["operation"] == "core.extract")
    dialogue = next(
        record
        for record in records
        if record["operation"] == "core.dialogue" and record["turn"] == 1
    )
    clinic = next(
        record for record in records if record["operation"] == "clinic.transfer_appointment"
    )

    assert {item["component"] for item in (turn, core, extraction, dialogue, clinic)} == {
        "TURN",
        "CORE",
        "EXTRACTION",
        "DIALOGUE",
        "CLINIC",
    }
    assert core["parent_span_id"] == turn["span_id"]
    assert extraction["parent_span_id"] == core["span_id"]
    assert dialogue["parent_span_id"] == core["span_id"]
    assert clinic["parent_span_id"] == dialogue["span_id"]
    assert len({item["trace_id"] for item in (turn, core, extraction, dialogue, clinic)}) == 1
    assert len({item["call_key"] for item in (turn, core, extraction, dialogue, clinic)}) == 1
    assert core["state_before"] == "AWAITING_IDENTITY"
    assert core["state_after"] == "ENDED"
    assert core["decision"] == "TRANSFER"
    assert core["decision_reason"] == "PATIENT_REQUEST"
    assert core["clinic_call_count"] == 1
    assert clinic["endpoint_template"] == "/appointments/{id}/transfer"
    assert "apt_00417" not in clinic["endpoint_template"]

    event_names = [event["name"] for event in core["events"]]
    assert event_names == [
        "session.admitted",
        "policy.decision",
        "policy.decision",
        "policy.decision",
        "fsm.transition",
        "session.committed",
    ]
    stages = [
        event["attributes"]["stage"]
        for event in core["events"]
        if event["name"] == "policy.decision"
    ]
    assert stages == ["preconditions", "silence", "signals"]

    serialized = json.dumps(records, ensure_ascii=False)
    forbidden = [
        call_id,
        "apt_00417",
        "0912345600",
        "cho tôi gặp nhân viên",
        "Nguyễn Văn A",
        "1978-03-14",
        "audio_url",
        "utterance",
        "transcript",
        "idempotency_key",
        "slot_id",
        '"span":',
        '"value":',
    ]
    assert all(value not in serialized for value in forbidden)


def test_replay_has_new_trace_same_call_key_and_no_business_children(redis_store_factory) -> None:
    sink = MemorySink()
    tracer = _tracer(sink)
    bot = create_orchestrator(FakeClinicAPI(), tracer=tracer, store=redis_store_factory())
    call_id = "replay-private"
    _start(bot, tracer, call_id)
    _turn(bot, tracer, call_id, 1, "Nguyễn Văn A")
    _turn(bot, tracer, call_id, 1, "Nguyễn Văn A")

    roots = [
        record
        for record in _records(sink)
        if record["operation"] == "http.call_turn" and record["turn"] == 1
    ]
    assert len(roots) == 2
    all_roots = [record for record in _records(sink) if record["component"] == "TURN"]
    assert len({record["call_key"] for record in all_roots}) == 1
    assert roots[0]["trace_id"] != roots[1]["trace_id"]
    assert roots[0]["call_key"] == roots[1]["call_key"]
    assert roots[1]["replayed"] is True

    replay_records = [
        record for record in _records(sink) if record["trace_id"] == roots[1]["trace_id"]
    ]
    assert {record["component"] for record in replay_records} == {"TURN", "CORE"}
    core = next(record for record in replay_records if record["component"] == "CORE")
    assert [event["name"] for event in core["events"]] == ["session.replayed"]


def test_sink_failure_after_clinic_success_does_not_retry_mutation(redis_store_factory) -> None:
    sink = MemorySink(fail=True)
    tracer = _tracer(sink)
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic, tracer=tracer, store=redis_store_factory())
    _start(bot, tracer, "sink-failure-call")
    _turn(bot, tracer, "sink-failure-call", 1, "Nguyễn Văn A")
    _turn(bot, tracer, "sink-failure-call", 2, "14/03/1978")
    result = _turn(bot, tracer, "sink-failure-call", 3, "Có, tôi đến được")

    assert result.outcome == "CONFIRMED"
    assert clinic.writes == [("apt_00417", "CONFIRMED", {})]


def test_invalid_post_dialogue_metadata_does_not_change_business(
    monkeypatch, redis_store_factory
) -> None:
    sink = MemorySink()
    tracer = _tracer(sink)
    bot = create_orchestrator(FakeClinicAPI(), tracer=tracer, store=redis_store_factory())
    canary = "private dialogue metadata"
    monkeypatch.setattr(bot, "_dialogue_action", lambda action, question: canary)

    _start(bot, tracer, "metadata-call")
    action = _turn(bot, tracer, "metadata-call", 1, "Nguyễn Văn A")

    assert action.ended is False
    assert action.state == "AWAITING_IDENTITY"
    assert bot.sessions.store.get_turn("metadata-call", 1).status == "COMPLETED"
    assert canary not in json.dumps(_records(sink), ensure_ascii=False)


def test_confirmation_guardrail_remains_transfer_and_commits_over_http(
    tmp_path, monkeypatch, redis_store_factory, redis_server
) -> None:
    trace_dir = tmp_path / "guardrail-traces"
    monkeypatch.setenv("TRACE_ENABLED", "true")
    monkeypatch.setenv("TRACE_JSONL_DIR", str(trace_dir))
    monkeypatch.setenv("TRACE_PSEUDONYMIZATION_KEY", "guardrail-trace-secret-key-00000000")
    monkeypatch.setenv("TRACE_KEY_VERSION", "v1")
    monkeypatch.setenv("TRACE_ENVIRONMENT", "test")
    clinic = FakeClinicAPI()
    app = create_app(
        clinic_factory=lambda: clinic,
        engine_settings=EngineSettings(),
        session_store_factory=redis_store_factory,
        speech_factory=lambda: make_speech_bundle(tmp_path / "audio"),
        call_mode_factory=lambda: CallModeStore(
            fakeredis.FakeRedis(server=redis_server, decode_responses=True),
            key_prefix=f"test:{uuid4().hex}",
        ),
    )
    call_id = "guardrail-confirmation-call"

    with TestClient(app) as client:

        def reject_confirmation(_ctx) -> None:
            raise SevereFailureBlocked("CONFIRMATION", "private guardrail detail")

        monkeypatch.setattr(
            app.state.orchestrator._dialogue._gateway, "confirm", reject_confirmation
        )
        started = client.post(
            "/v1/calls",
            json={
                "call_id": call_id,
                "direction": "outbound",
                "appointment_id": "apt_00417",
                "caller_number": "0912345600",
                "locale": "vi-VN",
                "mode": "text",
                "max_turns": 20,
            },
        )
        assert started.status_code == 200
        for turn, text in ((1, "Nguyễn Văn A"), (2, "14/03/1978")):
            response = client.post(
                f"/v1/calls/{call_id}/turn",
                json={"turn": turn, "text": text, "silence_ms": 0, "audio_url": None},
            )
            assert response.status_code == 200
        response = client.post(
            f"/v1/calls/{call_id}/turn",
            json={
                "turn": 3,
                "text": "Có, tôi đến được",
                "silence_ms": 0,
                "audio_url": None,
            },
        )

        assert response.status_code == 200
        assert response.json()["outcome"] == "TRANSFERRED"
        assert app.state.session_store.get_turn(call_id, 3).status == "COMPLETED"

    records = [
        json.loads(line)
        for path in trace_dir.glob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    core = next(
        record
        for record in records
        if record["operation"] == "core.handle_turn" and record["turn"] == 3
    )
    assert core["error_code"] == "GUARDRAIL_CONFIRMATION"
    assert "private guardrail detail" not in json.dumps(records, ensure_ascii=False)


def test_version_conflict_is_one_logical_span_with_two_attempts(redis_store_factory) -> None:
    sink = MemorySink()
    tracer = _tracer(sink)
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic, tracer=tracer, store=redis_store_factory())
    _start(bot, tracer, "version-call")
    _turn(bot, tracer, "version-call", 1, "Nguyễn Văn A")
    _turn(bot, tracer, "version-call", 2, "14/03/1978")
    clinic.fail_next("confirm_appointment", clinic_error(409, "VERSION_CONFLICT"))
    result = _turn(bot, tracer, "version-call", 3, "Có, tôi đến được")

    assert result.outcome == "CONFIRMED"
    spans = [
        record for record in _records(sink) if record["operation"] == "clinic.confirm_appointment"
    ]
    assert len(spans) == 1
    assert spans[0]["attempt_count"] == 2
    assert spans[0]["retry_count"] == 1
    assert spans[0]["if_match_used"] is True
    assert spans[0]["idempotency_used"] is True
    assert spans[0]["version_conflict"] is True
    assert spans[0]["status"] == "OK"
    assert [event["attributes"]["attempt"] for event in spans[0]["events"]] == [1, 2]
    assert [event["attributes"]["version_conflict"] for event in spans[0]["events"]] == [
        True,
        False,
    ]
    serialized = json.dumps(_records(sink), ensure_ascii=False)
    assert "14/03/1978" not in serialized
    assert "1978-03-14" not in serialized


def test_http_routes_emit_jsonl_without_request_content(
    tmp_path, monkeypatch, redis_store_factory, redis_server
) -> None:
    trace_dir = tmp_path / "trace-output"
    secret = "http-trace-test-secret-key-000000000"
    monkeypatch.setenv("TRACE_ENABLED", "true")
    monkeypatch.setenv("TRACE_JSONL_DIR", str(trace_dir))
    monkeypatch.setenv("TRACE_PSEUDONYMIZATION_KEY", secret)
    monkeypatch.setenv("TRACE_KEY_VERSION", "v1")
    monkeypatch.setenv("TRACE_ENVIRONMENT", "test")
    app = create_app(
        clinic_factory=FakeClinicAPI,
        engine_settings=EngineSettings(),
        session_store_factory=redis_store_factory,
        speech_factory=lambda: make_speech_bundle(tmp_path / "audio"),
        call_mode_factory=lambda: CallModeStore(
            fakeredis.FakeRedis(server=redis_server, decode_responses=True),
            key_prefix=f"test:{uuid4().hex}",
        ),
    )
    call_id = "http-private-call"
    with TestClient(app) as client:
        started = client.post(
            "/v1/calls",
            json={
                "call_id": call_id,
                "direction": "outbound",
                "appointment_id": "apt_00417",
                "caller_number": "0912345600",
                "locale": "vi-VN",
                "mode": "text",
                "max_turns": 20,
            },
        )
        assert started.status_code == 200
        turned = client.post(
            f"/v1/calls/{call_id}/turn",
            json={"turn": 1, "text": "Nguyễn Văn A", "silence_ms": 0, "audio_url": None},
        )
        assert turned.status_code == 200
        rejected_audio = client.post(
            f"/v1/calls/{call_id}/turn",
            json={
                "turn": 2,
                "text": None,
                "silence_ms": 0,
                "audio_url": "https://private.example/audio.wav",
            },
        )
        assert rejected_audio.status_code == 422

    lines = [
        line
        for path in trace_dir.glob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    records = [json.loads(line) for line in lines]
    roots = [record for record in records if record["component"] == "TURN"]
    assert [record["operation"] for record in roots] == [
        "http.start_call",
        "http.call_turn",
        "http.call_turn",
    ]
    assert roots[0]["route_template"] == "/v1/calls"
    assert roots[1]["route_template"] == "/v1/calls/{call_id}/turn"
    assert [record["http_status"] for record in roots] == [200, 200, 422]
    serialized = "\n".join(lines)
    assert call_id not in serialized
    assert "apt_00417" not in serialized
    assert "0912345600" not in serialized
    assert "Nguyễn Văn A" not in serialized
    assert "https://private.example/audio.wav" not in serialized
    assert secret not in serialized
