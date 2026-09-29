"""R-01 §3.9: span GUARD và hai event mới đi qua allowlist đóng; trace không chứa câu thoại hay ID."""

import json

import pytest

from callbot.engine import CallerInput, CallStart, create_orchestrator
from callbot.engine.diagnostics import TurnDiagnostics
from callbot.engine.dialogue import templates as t
from callbot.tracing import Tracer
from callbot.tracing.errors import ERROR_CODES, classify_guardrail
from callbot.tracing.privacy import (
    SafeAttributes,
    UnsafeTraceData,
    validate_component_operation,
)
from callbot.tracing.pseudonym import CallKeyFactory
from clinic_mock_sim import FakeClinicAPI


class MemorySink:
    def __init__(self) -> None:
        self.spans = []

    def emit(self, span) -> None:
        self.spans.append(span)


def test_guard_span_fields_and_events_are_allowlisted() -> None:
    validate_component_operation("GUARD", "core.output_guard")
    SafeAttributes.for_span(
        guard_verdict="REPLACE",
        guard_rule="OG-5",
        render_count=2,
        write_attempted=2,
        write_succeeded=1,
        write_operation="transfer",
        write_status_match=True,
    )
    SafeAttributes.for_event(
        "output_guard.blocked",
        guard_rule="OG-0",
        error_type="INTERNAL",
        error_code="GUARDRAIL_OUTPUT_UNREGISTERED",
    )
    SafeAttributes.for_event(
        "output_guard.replaced", guard_rule="OG-5", outcome="CONFIRMED", write_operation="confirm"
    )


@pytest.mark.parametrize(
    "attributes",
    [
        {"guard_utterance": "Dạ"},  # ngoài allowlist
        {"write_operation": ["confirm", "transfer"]},  # không nhận list
        {"write_attempted": -1},
        {"guard_rule": "OG 0 lịch khám"},
    ],
)
def test_guard_attributes_outside_contract_are_rejected(attributes) -> None:
    with pytest.raises(UnsafeTraceData):
        SafeAttributes.for_span(**attributes)


def test_output_guard_codes_are_registered() -> None:
    for code in ("OUTPUT_UNREGISTERED", "OUTPUT_UNPROVEN_SUCCESS"):
        assert classify_guardrail(code).error_code in ERROR_CODES
        assert TurnDiagnostics(error_code=code).error_code == code


def test_blocked_turn_trace_has_rule_and_code_but_no_content(monkeypatch, redis_store_factory):
    sink = MemorySink()
    tracer = Tracer(
        sink, CallKeyFactory("r01-trace-test-secret-00000000000000", version="v1", environment="t")
    )
    bot = create_orchestrator(FakeClinicAPI(), tracer=tracer, store=redis_store_factory())
    call_id = "private-r01-call"
    with tracer.start_trace(call_id=call_id, turn=0, component="TURN", operation="http.start_call"):
        bot.start_call(CallStart(call_id=call_id, direction="outbound", appointment_id="apt_00417"))
    monkeypatch.setattr(
        t, "appointment_summary", lambda ctx, appointment: "Lịch khám khoa Tim mạch lúc 9 giờ."
    )
    for turn, text in enumerate(["Nguyễn Văn A", "14/03/1978"], start=1):
        with tracer.start_trace(
            call_id=call_id, turn=turn, component="TURN", operation="http.call_turn"
        ):
            action = bot.handle_turn(call_id, CallerInput(turn=turn, text=text))

    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "SYSTEM_ERROR")
    records = [span.to_dict() for span in sink.spans]
    guard = [record for record in records if record["component"] == "GUARD" and record["turn"] == 2]
    blocked = next(record for record in guard if record.get("guard_verdict") == "BLOCK")
    assert blocked["guard_rule"] == "OG-0"
    assert blocked["error_code"] == "GUARDRAIL_OUTPUT_UNREGISTERED"
    assert [event["name"] for event in blocked["events"]] == ["output_guard.blocked"]
    core = next(
        record
        for record in records
        if record["operation"] == "core.handle_turn" and record["turn"] == 2
    )
    assert core["guardrail_code"] == "GUARDRAIL_OUTPUT_UNREGISTERED"

    serialized = json.dumps(records, ensure_ascii=False)
    for forbidden in (call_id, "apt_00417", "Tim mạch", "9 giờ", "utterance", "slot_"):
        assert forbidden not in serialized
