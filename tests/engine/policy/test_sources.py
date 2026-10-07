"""SourceRecorder: Dialogue đọc lịch tối đa một lần mỗi lượt (review PR 06/10, evidence §10, ý 8)."""

from datetime import datetime

import pytest

from callbot.engine import CallStart
from callbot.engine.errors import AppointmentNotActionable
from callbot.engine.extraction.schema import VN_TZ
from callbot.engine.policy.sources import SourceRecorder, SourceRegistry, bind_sources
from callbot.engine.session.context import CallContext
from callbot.engine.tools.clinic_gateway import ClinicGateway
from clinic_mock_sim import FakeClinicAPI

NOW = datetime(2026, 10, 5, 15, 16, tzinfo=VN_TZ)


def _setup():
    clinic = FakeClinicAPI.mentor_mock()
    recorder = SourceRecorder(ClinicGateway(clinic, clinic_id="cl_vinmec"))
    ctx = CallContext(
        call=CallStart(call_id="c_sources", direction="outbound", appointment_id="apt_00417"),
        opened_at=NOW,
    )
    return clinic, recorder, ctx


def _reads(clinic) -> int:
    return sum(1 for call in clinic.calls if call.operation == "get_appointment")


def test_the_appointment_is_read_once_per_turn() -> None:
    clinic, recorder, ctx = _setup()
    with bind_sources(SourceRegistry([])):
        first = recorder.get_actionable_appointment(ctx)
        second = recorder.get_actionable_appointment(ctx)
    assert first == second and _reads(clinic) == 1

    # Lượt mới có registry mới: đọc lại từ mock
    with bind_sources(SourceRegistry([])):
        recorder.get_actionable_appointment(ctx)
    assert _reads(clinic) == 2


def test_the_copy_of_the_turn_still_checks_the_status() -> None:
    _, recorder, ctx = _setup()
    with bind_sources(SourceRegistry([])):
        recorder.get_actionable_appointment(ctx)
        with pytest.raises(AppointmentNotActionable):
            recorder.get_actionable_appointment(ctx, frozenset({"CONFIRMED"}))


def test_without_a_turn_every_call_reads_the_mock() -> None:
    clinic, recorder, ctx = _setup()
    recorder.get_actionable_appointment(ctx)
    recorder.get_actionable_appointment(ctx)
    assert _reads(clinic) == 2
