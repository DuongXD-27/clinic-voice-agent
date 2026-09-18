"""AC-7: dữ liệu chuẩn nội bộ (identity_reference) không lọt vào IE, trace hay kết quả Verifier."""

import json
from dataclasses import fields
from datetime import date, datetime, timezone

from callbot.engine.extraction.schema import TurnContext
from callbot.engine.orchestrator import build_turn_context
from callbot.engine.session.context import CallContext
from callbot.engine.tools.clinic_gateway import ClinicGateway
from callbot.engine.tools.fake_clinic import FakeClinicAPI
from callbot.engine.types import CallStart
from callbot.engine.verification import IdentityVerifier

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
SECRETS = ("Nguyễn Văn A", "nguyen van a", "1978-03-14", "pt_3391", "N. V. A.")


def _prepared_outbound() -> tuple[IdentityVerifier, CallContext]:
    fake = FakeClinicAPI()
    verifier = IdentityVerifier(ClinicGateway(fake, clinic_id="cl_vinmec"))
    ctx = CallContext(
        call=CallStart(call_id="c_iso", direction="outbound", appointment_id="apt_00417"),
        opened_at=NOW,
    )
    verifier.prepare(ctx)
    assert ctx.identity_reference  # tiền điều kiện: có dữ liệu để rò
    return verifier, ctx


def test_turn_context_has_no_identity_reference_field() -> None:
    _, ctx = _prepared_outbound()
    turn_context = build_turn_context(ctx, 1, NOW)

    assert "identity_reference" not in {f.name for f in fields(TurnContext)}
    assert "identity_lookup" not in {f.name for f in fields(TurnContext)}
    dumped = repr(turn_context)
    assert not any(secret in dumped for secret in SECRETS)


def test_prepare_and_verify_results_carry_no_record_values() -> None:
    verifier, ctx = _prepared_outbound()
    prepare = verifier.prepare(ctx)
    ctx.claimed_name, ctx.claimed_dob = "Trần Văn B", date(1979, 1, 1)
    result = verifier.verify(ctx)

    for blob in (repr(prepare), json.dumps(prepare.to_trace()), repr(result)):
        assert not any(secret in blob for secret in SECRETS), blob
    # to_trace của verify chứa patient_id chỉ khi VERIFIED; ở đây MISMATCH nên là None
    trace = json.dumps(result.to_trace(), ensure_ascii=False)
    assert "Nguyễn" not in trace and "1978" not in trace and trace.count("pt_3391") == 0


def test_verified_trace_exposes_only_patient_id() -> None:
    verifier, ctx = _prepared_outbound()
    ctx.claimed_name, ctx.claimed_dob = "Nguyễn Văn A", date(1978, 3, 14)
    trace = verifier.verify(ctx).to_trace()

    assert trace["patient_id"] == "pt_3391"
    assert set(trace) == {"status", "detail", "candidates", "patient_id"}
