from typing import Any, Optional

import pytest

from callbot.engine.errors import WriteOutcomeUnknown
from callbot.engine.journal import bind_journal
from callbot.engine.policy.guardrails import SevereFailureBlocked
from callbot.engine.session.context import ActionEvidence, CallContext
from callbot.engine.tools.clinic_gateway import ClinicGateway
from tests.engine.fake_clinic import FakeClinicAPI
from tests.engine.tools.test_clinic_gateway import RecordingJournal


def _ready_to_book() -> CallContext:
    from callbot.engine.extraction.schema import QuestionId
    from callbot.engine.session.context import Question
    from callbot.engine.types import CallStart
    ctx = CallContext(
        CallStart(call_id="c_book", caller_number="0987654321", direction="inbound", appointment_id=None),
        opened_at=None,
        turn=3
    )
    ctx.identity_lookup = "LOADED"
    ctx.identity_step = "VERIFIED"
    ctx.patient_id = "pt_3391"
    ctx.state = "AWAITING_CONFIRMATION"
    ctx.question = Question(QuestionId.SLOT_READBACK, "Anh chị đặt lịch khung giờ này đúng không ạ?", turn=2, action="BOOK", slot_id="slot_91d2")
    ctx.set_pending("BOOK")
    ctx.slots = [{"slot_id": "slot_91d2", "start_time": "2026-10-14T15:00:00+07:00", "end_time": "2026-10-14T15:30:00+07:00"}]
    ctx.select_slot("slot_91d2")
    ctx.add_evidence(
        ActionEvidence(
            kind="CONFIRMATION",
            action="BOOK",
            slot_id="slot_91d2",
            turn=3,
            question_id=QuestionId.SLOT_READBACK,
            question_turn=2,
            transcript="Vâng đặt cho tôi",
            label="AGREE",
            provenance="EXACT",
            span=None,
        )
    )
    return ctx


class MissingIdClinicAPI(FakeClinicAPI):
    def create_appointment(self, patient_id: str, slot_id: str, idempotency_key: Optional[str] = None) -> dict[str, Any]:
        return {"status": "BOOKED"}


class WrongStatusClinicAPI(FakeClinicAPI):
    def create_appointment(self, patient_id: str, slot_id: str, idempotency_key: Optional[str] = None) -> dict[str, Any]:
        return {"appointment_id": "apt_new_1", "status": "SCHEDULED"}


def test_book_missing_appointment_id_raises_unknown() -> None:
    fake = MissingIdClinicAPI()
    gateway = ClinicGateway(fake, clinic_id="cl_vinmec")
    ctx = _ready_to_book()

    with bind_journal(RecordingJournal()), pytest.raises(WriteOutcomeUnknown):
        gateway.book(ctx, "slot_91d2")


def test_book_wrong_status_raises_unknown() -> None:
    fake = WrongStatusClinicAPI()
    gateway = ClinicGateway(fake, clinic_id="cl_vinmec")
    ctx = _ready_to_book()

    with bind_journal(RecordingJournal()), pytest.raises(WriteOutcomeUnknown) as exc:
        gateway.book(ctx, "slot_91d2")

    assert "book trả status SCHEDULED" in str(exc.value)


def test_book_duplicate_prevented_by_sf01() -> None:
    fake = FakeClinicAPI()
    gateway = ClinicGateway(fake, clinic_id="cl_vinmec")
    ctx = _ready_to_book()

    with bind_journal(RecordingJournal()):
        gateway.book(ctx, "slot_91d2")

    assert ctx.created_appointment_id is not None

    # Try again
    with pytest.raises(SevereFailureBlocked) as exc:
        gateway.book(ctx, "slot_91d2")
    assert exc.value.code == "SF-01"


def test_sf02_blocks_unoffered_slot() -> None:
    ctx = _ready_to_book()
    with pytest.raises(SevereFailureBlocked) as exc:
        from callbot.engine.policy.guardrails import assert_slot_offered
        assert_slot_offered(ctx, "slot_unoffered")
    assert exc.value.code == "SF-02"
