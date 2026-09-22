"""ClinicGateway trên FakeClinicAPI: đọc hết trang + chuẩn hóa, transfer theo hướng gọi, ba lớp kết quả ghi."""

from datetime import datetime, timedelta
from typing import Any

import pytest

from callbot.engine.errors import (
    AppointmentNotActionable,
    ClinicAPIError,
    ClinicInvalidResponse,
    ClinicWriteRejected,
    WriteOutcomeUnknown,
)
from callbot.engine.extraction.schema import Agreement, Intent, QuestionId
from callbot.engine.journal import ClinicCommand, bind_journal
from callbot.engine.policy.guardrails import SevereFailureBlocked
from callbot.engine.session.context import ActionEvidence, CallContext, Question
from callbot.engine.tools.clinic_gateway import ClinicGateway
from callbot.engine.tools.fake_clinic import FakeClinicAPI, clinic_error
from callbot.engine.tools.telemetry import collect_api_calls
from callbot.engine.types import CallStart

OCT = datetime.fromisoformat("2026-10-14T00:00:00+07:00")


class RecordingJournal:
    def __init__(self) -> None:
        self.events: list[tuple[str, ClinicCommand, Any]] = []

    def begin(self, command: ClinicCommand) -> None:
        self.events.append(("begin", command, None))

    def succeeded(self, command: ClinicCommand, result: dict[str, Any]) -> None:
        self.events.append(("succeeded", command, result))

    def failed(self, command: ClinicCommand, error: str) -> None:
        self.events.append(("failed", command, error))

    def unknown(self, command: ClinicCommand, error: str) -> None:
        self.events.append(("unknown", command, error))

    @property
    def statuses(self) -> list[str]:
        return [name for name, _, _ in self.events]


def _outbound(call_id: str = "c_gw") -> CallContext:
    return CallContext(
        call=CallStart(call_id=call_id, direction="outbound", appointment_id="apt_00417"),
        opened_at=OCT,
        turn=3,
    )


def _inbound(call_id: str = "c_gw_in") -> CallContext:
    return CallContext(
        call=CallStart(call_id=call_id, direction="inbound", caller_number="0912345600"),
        opened_at=OCT,
        turn=3,
    )


def _verify(ctx: CallContext) -> None:
    """FSM (T-02): đã xác minh cần hồ sơ đọc ở lượt 0 và patient_id."""
    ctx.identity_lookup = "LOADED"
    ctx.patient_id = "pt_3391"
    ctx.identity_step = "VERIFIED"


def _ready_to_confirm(call_id: str = "c_cf") -> CallContext:
    """§1.1.3: đọc lại lịch xong, chờ đúng câu hỏi CONFIRM_READBACK — chưa có bằng chứng AGREE."""
    ctx = _outbound(call_id)
    _verify(ctx)
    ctx.state = "AWAITING_CONFIRMATION"
    ctx.question = Question(
        QuestionId.CONFIRM_READBACK, "Anh chị đến được không ạ?", turn=2, action="CONFIRM"
    )
    ctx.set_pending("CONFIRM", None)
    return ctx


def _agree_confirm(ctx: CallContext) -> None:
    ctx.add_evidence(
        ActionEvidence(
            kind="CONFIRMATION",
            action="CONFIRM",
            slot_id=None,
            turn=ctx.turn,
            question_id=QuestionId.CONFIRM_READBACK,
            question_turn=2,
            transcript="Có, tôi đến được.",
            label=Agreement.AGREE.value,
            provenance="EXACT",
            span=None,
        )
    )


def _ready_to_cancel(call_id: str = "c_cancel") -> CallContext:
    """§1.1.4/SF-05: yêu cầu hủy đã ghi nhận ở lượt trước, chờ đúng câu hỏi CANCEL_RECONFIRM."""
    ctx = _outbound(call_id)
    _verify(ctx)
    ctx.state = "AWAITING_CONFIRMATION"
    ctx.question = Question(
        QuestionId.CANCEL_RECONFIRM, "Anh chị muốn hủy hẳn, đúng không ạ?", turn=2, action="CANCEL"
    )
    ctx.set_pending("CANCEL", None)
    ctx.add_evidence(
        ActionEvidence(
            kind="REQUEST",
            action="CANCEL",
            slot_id=None,
            turn=1,
            question_id=None,
            question_turn=None,
            transcript="Tôi muốn hủy.",
            label=Intent.CANCEL.value,
            provenance="EXACT",
            span=None,
        )
    )
    return ctx


def _agree_cancel(ctx: CallContext) -> None:
    ctx.add_evidence(
        ActionEvidence(
            kind="CONFIRMATION",
            action="CANCEL",
            slot_id=None,
            turn=ctx.turn,
            question_id=QuestionId.CANCEL_RECONFIRM,
            question_turn=2,
            transcript="Đúng rồi, hủy giúp tôi.",
            label=Agreement.AGREE.value,
            provenance="EXACT",
            span=None,
        )
    )


# --- Đọc -----------------------------------------------------------------------------


def test_list_open_slots_walks_every_page_and_normalizes() -> None:
    fake = FakeClinicAPI(seed=False, strict_slot_window=True)
    for index in range(230):  # > 2 trang 100
        start = OCT + timedelta(hours=8, minutes=15 * index)
        fake.seed_slot(
            {
                "slot_id": f"slot_{index:03d}",
                "clinic_id": "cl_vinmec",
                "start_time": start.isoformat(),
                "end_time": (start + timedelta(minutes=15)).isoformat(),
                "provider_id": "pr_vinmec_1",
            }
        )
    gateway = ClinicGateway(fake, clinic_id="cl_vinmec")
    ctx = _outbound()

    slots = gateway.list_open_slots(ctx, OCT)

    assert len(slots) == 230 and len({s["slot_id"] for s in slots}) == 230
    assert all(s["starts_at"] == s["start_time"] and s["ends_at"] for s in slots)
    assert ctx.slots == slots and fake.slot_reads == 3  # 100 + 100 + 30


def test_list_open_slots_sends_rfc3339_window_of_14_days() -> None:
    fake = FakeClinicAPI(seed=False, strict_slot_window=True)
    gateway = ClinicGateway(fake, clinic_id="cl_vinmec")
    # Không seed slot: chỉ kiểm tra fake không từ chối tham số cửa sổ (regex, ≤ 14 ngày)
    assert gateway.list_open_slots(_outbound(), datetime(2026, 10, 14, 9, 30, 15, 999)) == []
    assert fake.slot_reads == 1


def test_find_patients_by_phone_returns_canonical_candidates_from_all_pages() -> None:
    fake = FakeClinicAPI(seed=False)
    for index in range(120):
        fake.seed_patient(
            {
                "patient_id": f"pt_{index}",
                "phone": "0912345600",
                "verify": {"full_name": f"Người {index}", "dob": "1978-03-14"},
            }
        )
    fake.seed_patient({"patient_id": "pt_null", "phone": "0912345600", "verify": None})
    gateway = ClinicGateway(fake, clinic_id="cl_vinmec")

    candidates = gateway.find_patients_by_phone("0912345600")

    assert len(candidates) == 121
    assert all(set(c) == {"patient_id", "full_name", "dob", "verifiable"} for c in candidates)
    unverifiable = [c for c in candidates if not c["verifiable"]]
    assert [c["patient_id"] for c in unverifiable] == ["pt_null"]


def test_find_patients_propagates_mock_validation_error() -> None:
    gateway = ClinicGateway(FakeClinicAPI(), clinic_id="cl_vinmec")
    with pytest.raises(ClinicAPIError) as exc:
        gateway.find_patients_by_phone("+84912345600")  # Verifier phải chuẩn hóa trước (T-01)
    assert (exc.value.status, exc.value.code) == (400, "INVALID_REQUEST")


def test_get_appointment_is_readable_before_identity_verified() -> None:
    gateway = ClinicGateway(FakeClinicAPI(), clinic_id="cl_vinmec")
    ctx = _outbound()
    assert not ctx.identity_verified
    appointment = gateway.get_appointment(ctx)
    assert appointment["version"] == 3 and appointment["patient"]["verify"]["dob"] == "1978-03-14"


def test_get_appointment_blocks_other_appointment_ids() -> None:
    gateway = ClinicGateway(FakeClinicAPI(), clinic_id="cl_vinmec")
    ctx = _inbound()  # inbound chưa tạo lịch: không có appointment đích
    with pytest.raises(SevereFailureBlocked):
        gateway.get_appointment(ctx)


# --- Transfer theo hướng gọi --------------------------------------------------------------


def test_transfer_inbound_without_booking_sends_nothing() -> None:
    fake = FakeClinicAPI()
    gateway = ClinicGateway(fake, clinic_id="cl_vinmec")
    journal = RecordingJournal()
    with bind_journal(journal):
        assert gateway.transfer(_inbound(), "PATIENT_NOT_FOUND") is None
    assert fake.writes == [] and fake.requests == [] and journal.events == []


def test_transfer_outbound_writes_with_fresh_if_match_and_fixed_key() -> None:
    fake = FakeClinicAPI()
    gateway = ClinicGateway(fake, clinic_id="cl_vinmec")
    journal = RecordingJournal()
    with bind_journal(journal):
        result = gateway.transfer(_outbound("c_t"), "OUT_OF_SCOPE")
    assert result and result["status"] == "TRANSFERRED"
    assert fake.writes == [("apt_00417", "TRANSFERRED", {"transfer_reason": "OUT_OF_SCOPE"})]
    assert fake.requests == [("c_t:3:transfer", "TRANSFERRED")]
    assert journal.statuses == ["begin", "succeeded"]
    assert journal.events[0][1].if_match == 3


# --- Confirm / Cancel (T-03) --------------------------------------------------------------


def test_confirm_writes_after_valid_readback_agreement() -> None:
    fake = FakeClinicAPI()
    gateway = ClinicGateway(fake, clinic_id="cl_vinmec")
    ctx = _ready_to_confirm("c_cf1")
    _agree_confirm(ctx)
    journal = RecordingJournal()

    with bind_journal(journal):
        result = gateway.confirm(ctx)

    assert result["status"] == "CONFIRMED"
    assert fake.writes == [("apt_00417", "CONFIRMED", {})]
    assert fake.requests == [("c_cf1:3:confirm", "CONFIRMED")]
    assert journal.statuses == ["begin", "succeeded"]


def test_confirm_without_agreement_evidence_is_blocked() -> None:
    fake = FakeClinicAPI()
    gateway = ClinicGateway(fake, clinic_id="cl_vinmec")
    ctx = _ready_to_confirm("c_cf2")  # chưa gọi _agree_confirm

    with bind_journal(RecordingJournal()), pytest.raises(SevereFailureBlocked) as exc:
        gateway.confirm(ctx)

    assert exc.value.code == "CONFIRMATION"
    assert fake.writes == [] and fake.requests == []


def test_confirm_blocks_write_when_call_has_no_target_appointment() -> None:
    """SF-01: dù mọi bằng chứng đều hợp lệ, không có appointment đích thì không được ghi."""
    fake = FakeClinicAPI()
    gateway = ClinicGateway(fake, clinic_id="cl_vinmec")
    ctx = _ready_to_confirm("c_cf3")
    ctx.call = CallStart(call_id="c_cf3", direction="outbound", appointment_id=None)
    _agree_confirm(ctx)

    with bind_journal(RecordingJournal()), pytest.raises(SevereFailureBlocked) as exc:
        gateway.confirm(ctx)

    assert exc.value.code == "SF-01"
    assert fake.writes == [] and fake.requests == []


def test_cancel_writes_reason_and_confirmed_flag_after_second_agreement() -> None:
    fake = FakeClinicAPI()
    gateway = ClinicGateway(fake, clinic_id="cl_vinmec")
    ctx = _ready_to_cancel("c_ca1")
    _agree_cancel(ctx)
    journal = RecordingJournal()

    with bind_journal(journal):
        result = gateway.cancel(ctx, "PATIENT_UNAVAILABLE")

    assert result["status"] == "CANCELLED"
    assert fake.writes == [("apt_00417", "CANCELLED", {"cancel_reason": "PATIENT_UNAVAILABLE"})]
    assert fake.requests == [("c_ca1:3:cancel", "CANCELLED")]
    assert journal.statuses == ["begin", "succeeded"]


def test_cancel_without_prior_request_evidence_is_blocked_by_sf05() -> None:
    """SF-05: chỉ có câu trả lời AGREE ở lượt hiện tại, không có yêu cầu hủy ở lượt trước đó."""
    fake = FakeClinicAPI()
    gateway = ClinicGateway(fake, clinic_id="cl_vinmec")
    ctx = _outbound("c_ca2")
    _verify(ctx)
    ctx.state = "AWAITING_CONFIRMATION"
    ctx.question = Question(
        QuestionId.CANCEL_RECONFIRM, "Anh chị muốn hủy hẳn, đúng không ạ?", turn=2, action="CANCEL"
    )
    ctx.set_pending("CANCEL", None)
    _agree_cancel(ctx)  # không có ActionEvidence(kind="REQUEST", ...) ở lượt trước

    with bind_journal(RecordingJournal()), pytest.raises(SevereFailureBlocked) as exc:
        gateway.cancel(ctx, "PATIENT_UNAVAILABLE")

    assert exc.value.code == "SF-05"
    assert fake.writes == [] and fake.requests == []


def test_cancel_version_conflict_rereads_and_retries_once_with_same_key() -> None:
    fake = FakeClinicAPI()
    fake.fail_next("cancel_appointment", clinic_error(409, "VERSION_CONFLICT"))
    gateway = ClinicGateway(fake, clinic_id="cl_vinmec")
    ctx = _ready_to_cancel("c_ca3")
    _agree_cancel(ctx)

    with bind_journal(RecordingJournal()):
        result = gateway.cancel(ctx, "PATIENT_UNAVAILABLE")

    assert result["status"] == "CANCELLED"
    assert [key for key, _ in fake.requests] == ["c_ca3:3:cancel", "c_ca3:3:cancel"]


# --- Ba lớp kết quả ghi ------------------------------------------------------------------


def test_version_conflict_rereads_and_retries_once_with_same_key() -> None:
    fake = FakeClinicAPI()
    fake.fail_next("transfer_appointment", clinic_error(409, "VERSION_CONFLICT"))
    gateway = ClinicGateway(fake, clinic_id="cl_vinmec")
    journal = RecordingJournal()
    with bind_journal(journal):
        result = gateway.transfer(_outbound("c_vc"), "OUT_OF_SCOPE")
    assert result["status"] == "TRANSFERRED"
    assert [key for key, _ in fake.requests] == ["c_vc:3:transfer", "c_vc:3:transfer"]
    assert journal.statuses == ["begin", "failed", "begin", "succeeded"]


def test_second_version_conflict_is_a_definite_rejection() -> None:
    fake = FakeClinicAPI()
    fake.fail_next("transfer_appointment", clinic_error(409, "VERSION_CONFLICT"))
    fake.fail_next("transfer_appointment", clinic_error(409, "VERSION_CONFLICT"))
    gateway = ClinicGateway(fake, clinic_id="cl_vinmec")
    with bind_journal(RecordingJournal()), pytest.raises(ClinicWriteRejected) as exc:
        gateway.transfer(_outbound("c_vc2"), "OUT_OF_SCOPE")
    assert exc.value.code == "VERSION_CONFLICT" and exc.value.retryable is False
    assert fake.writes == []


@pytest.mark.parametrize(
    "error, retryable",
    [
        (clinic_error(429, "RATE_LIMITED"), True),
        (clinic_error(422, "IDEMPOTENCY_CONFLICT"), False),
        (clinic_error(404, "NOT_FOUND"), False),
        (ClinicAPIError(None, "CONNECT_ERROR", "refused", outcome_known=True), True),
    ],
)
def test_definite_rejections_carry_retryable_flag(error: ClinicAPIError, retryable: bool) -> None:
    fake = FakeClinicAPI()
    fake.fail_next("transfer_appointment", error)
    gateway = ClinicGateway(fake, clinic_id="cl_vinmec")
    journal = RecordingJournal()
    with bind_journal(journal), pytest.raises(ClinicWriteRejected) as exc:
        gateway.transfer(_outbound("c_rej"), "OUT_OF_SCOPE")
    assert (exc.value.status, exc.value.code, exc.value.retryable) == (
        error.status,
        error.code,
        retryable,
    )
    assert journal.statuses == ["begin", "failed"] and fake.writes == []


def test_read_failure_before_send_is_rejection_without_journal_entry() -> None:
    fake = FakeClinicAPI()
    fake.fail_next("get_appointment", clinic_error(503, "UPSTREAM"))
    gateway = ClinicGateway(fake, clinic_id="cl_vinmec")
    journal = RecordingJournal()
    with bind_journal(journal), pytest.raises(ClinicWriteRejected) as exc:
        gateway.transfer(_outbound("c_read"), "OUT_OF_SCOPE")
    assert exc.value.code == "UPSTREAM" and exc.value.retryable is True
    assert journal.events == [] and fake.requests == []  # chưa gửi lệnh ghi nào


def test_unknown_outcome_is_journaled_and_not_retried() -> None:
    fake = FakeClinicAPI()
    fake.fail_next("transfer_appointment", outcome_unknown=True, apply_first=True)
    gateway = ClinicGateway(fake, clinic_id="cl_vinmec")
    journal = RecordingJournal()
    with bind_journal(journal), pytest.raises(WriteOutcomeUnknown):
        gateway.transfer(_outbound("c_unk"), "OUT_OF_SCOPE")
    # Mock đã ghi nhưng bot không biết: nhật ký UNKNOWN, không gửi lại
    assert journal.statuses == ["begin", "unknown"]
    assert fake.writes == [("apt_00417", "TRANSFERRED", {"transfer_reason": "OUT_OF_SCOPE"})]
    assert len(fake.requests) == 1


def test_gateway_api_calls_are_collectable_for_trace() -> None:
    fake = FakeClinicAPI()
    gateway = ClinicGateway(fake, clinic_id="cl_vinmec")
    with collect_api_calls() as calls, bind_journal(RecordingJournal()):
        gateway.get_appointment(_outbound())
        gateway.transfer(_outbound("c_trace"), "OUT_OF_SCOPE")
    operations = [c.operation for c in calls]
    assert operations == ["get_appointment", "get_appointment", "transfer_appointment"]
    assert all(c.outcome == "ok" for c in calls)


# --- Lifecycle: chỉ thao tác trên lịch còn thao tác được ------------------------------------------

ALL_STATUSES = [
    "SCHEDULED",
    "BOOKED",
    "CONFIRMED",
    "CANCELLED",
    "RESCHEDULED",
    "TRANSFERRED",
    "UNREACHABLE",
]
ACTIONABLE = {"SCHEDULED", "BOOKED", "CONFIRMED"}


@pytest.mark.parametrize("status", ALL_STATUSES)
def test_actionable_read_accepts_only_scheduled_booked_confirmed(status: str) -> None:
    fake = FakeClinicAPI()
    fake.appointments["apt_00417"]["status"] = status
    gateway = ClinicGateway(fake, clinic_id="cl_vinmec")
    if status in ACTIONABLE:
        assert gateway.get_actionable_appointment(_outbound())["status"] == status
    else:
        with pytest.raises(AppointmentNotActionable) as exc:
            gateway.get_actionable_appointment(_outbound())
        assert status not in str(exc.value) and status not in exc.value.message


@pytest.mark.parametrize("status", ALL_STATUSES)
def test_confirm_checks_lifecycle_on_the_version_read(status: str) -> None:
    fake = FakeClinicAPI()
    fake.appointments["apt_00417"]["status"] = status
    ctx = _ready_to_confirm()
    _agree_confirm(ctx)
    journal = RecordingJournal()
    with bind_journal(journal):
        if status in ACTIONABLE:
            assert ClinicGateway(fake, "cl_vinmec").confirm(ctx)["status"] == "CONFIRMED"
            return
        with pytest.raises(AppointmentNotActionable):
            ClinicGateway(fake, "cl_vinmec").confirm(ctx)
    # Chặn trước khi gửi: không có lệnh nào vào nhật ký, không request ghi nào tới Clinic
    assert journal.statuses == [] and fake.requests == [] and fake.writes == []


@pytest.mark.parametrize("status", ALL_STATUSES)
def test_unreachable_keeps_its_own_lifecycle(status: str) -> None:
    fake = FakeClinicAPI()
    fake.appointments["apt_00417"]["status"] = status
    gateway = ClinicGateway(fake, clinic_id="cl_vinmec")
    with bind_journal(RecordingJournal()):
        if status in {"SCHEDULED", "BOOKED", "UNREACHABLE"}:
            assert gateway.mark_unreachable(_outbound(), "SILENCE")["status"] == "UNREACHABLE"
            return
        with pytest.raises(AppointmentNotActionable):
            gateway.mark_unreachable(_outbound(), "SILENCE")
    assert fake.requests == []


def test_lifecycle_is_checked_again_after_version_conflict() -> None:
    """Lịch bị hủy ở nơi khác đúng lúc bot ghi: lần đọc lại sau VERSION_CONFLICT phải chặn."""
    fake = FakeClinicAPI()
    original = fake.confirm_appointment

    def cancelled_elsewhere(*args, **kwargs):
        fake.confirm_appointment = original
        fake.appointments["apt_00417"].update(status="CANCELLED", version=4)
        raise clinic_error(409, "VERSION_CONFLICT")

    fake.confirm_appointment = cancelled_elsewhere
    ctx = _ready_to_confirm()
    _agree_confirm(ctx)
    journal = RecordingJournal()
    with bind_journal(journal), pytest.raises(AppointmentNotActionable):
        ClinicGateway(fake, "cl_vinmec").confirm(ctx)
    assert journal.statuses == ["begin", "failed"] and fake.writes == []


@pytest.mark.parametrize("operation", ["confirm_appointment", "transfer_appointment"])
def test_invalid_state_transition_is_not_actionable_and_not_retried(operation: str) -> None:
    fake = FakeClinicAPI()
    fake.fail_next(operation, clinic_error(409, "INVALID_STATE_TRANSITION"))
    gateway = ClinicGateway(fake, clinic_id="cl_vinmec")
    journal = RecordingJournal()
    with bind_journal(journal), pytest.raises(AppointmentNotActionable) as exc:
        if operation == "confirm_appointment":
            ctx = _ready_to_confirm()
            _agree_confirm(ctx)
            gateway.confirm(ctx)
        else:
            gateway.transfer(_outbound(), "OUT_OF_SCOPE")
    assert exc.value.cause_code == "INVALID_STATE_TRANSITION"
    assert journal.statuses == ["begin", "failed"] and len(fake.requests) == 1


@pytest.mark.parametrize(
    "change",
    [{"starts_at": None}, {"status": "WEIRD"}, {"version": "x"}, {"appointment_id": "apt_other"}],
)
def test_invalid_appointment_read_is_invalid_response(change: dict[str, Any]) -> None:
    fake = FakeClinicAPI()
    fake.appointments["apt_00417"].update(change)
    gateway = ClinicGateway(fake, clinic_id="cl_vinmec")
    with pytest.raises(ClinicInvalidResponse):
        gateway.get_appointment(_outbound())
    with bind_journal(RecordingJournal()), pytest.raises(ClinicInvalidResponse):
        gateway.transfer(_outbound(), "OUT_OF_SCOPE")
    assert fake.requests == []
