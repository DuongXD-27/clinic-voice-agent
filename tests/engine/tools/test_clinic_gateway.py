"""ClinicGateway trên FakeClinicAPI: đọc hết trang + chuẩn hóa, transfer theo hướng gọi, ba lớp kết quả ghi."""

from datetime import datetime, timedelta
from typing import Any

import pytest

from callbot.engine.errors import (
    AppointmentNotActionable,
    ClinicAPIError,
    ClinicInvalidResponse,
    ClinicWriteRejected,
    SlotTaken,
    WriteOutcomeUnknown,
)
from callbot.engine.extraction.schema import Agreement, Intent, QuestionId
from callbot.engine.journal import ClinicCommand, bind_journal
from callbot.engine.policy.guardrails import SevereFailureBlocked
from callbot.engine.session.context import ActionEvidence, CallContext, Question
from callbot.engine.tools.clinic_gateway import (
    WRITE_BACKOFF_S,
    WRITE_BUDGET_S,
    WRITE_MAX_SENDS,
    ClinicGateway,
)
from callbot.engine.tools.telemetry import collect_api_calls
from callbot.engine.types import CallStart
from clinic_mock_sim import FakeClinicAPI, clinic_error

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


def _ready_to_reschedule(slot_id: str, call_id: str = "c_rs") -> CallContext:
    """§1.1.6: slot lấy từ GET /slots của cuộc gọi, đã đọc lại và người gọi vừa đồng ý."""
    ctx = _outbound(call_id)
    _verify(ctx)
    ctx.state = "AWAITING_CONFIRMATION"
    ctx.set_pending("RESCHEDULE")
    ctx.slots = [{"slot_id": slot_id}]
    ctx.select_slot(slot_id)
    ctx.question = Question(
        QuestionId.SLOT_READBACK,
        "Anh chị đổi sang khung giờ này đúng không ạ?",
        turn=2,
        action="RESCHEDULE",
        slot_id=slot_id,
    )
    ctx.add_evidence(
        ActionEvidence(
            kind="CONFIRMATION",
            action="RESCHEDULE",
            slot_id=slot_id,
            turn=ctx.turn,
            question_id=QuestionId.SLOT_READBACK,
            question_turn=2,
            transcript="Vâng, đổi giúp tôi.",
            label=Agreement.AGREE.value,
            provenance="EXACT",
            span=None,
        )
    )
    return ctx


class FakeClock:
    """Đồng hồ giả cho ngân sách ghi của Gateway: `sleep` tiến thời gian, không chờ thật."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _gateway(fake: FakeClinicAPI) -> tuple[ClinicGateway, FakeClock]:
    clock = FakeClock()
    # Độ trễ giả của fake (`delay`) cũng tiến đồng hồ này
    fake.sleep = clock.sleep
    return ClinicGateway(fake, clinic_id="cl_vinmec", sleep=clock.sleep, clock=clock), clock


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
    # Không seed slot: mọi cửa sổ policy đều phải hợp lệ (regex, ≤ 14 ngày).
    assert gateway.list_open_slots(_outbound(), datetime(2026, 10, 14, 9, 30, 15, 999)) == []
    assert fake.slot_reads == 5


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
    # Lỗi tạm thời được gửi lại tới giới hạn (T-12); lỗi cố định chỉ gửi một lần
    sends = WRITE_MAX_SENDS if retryable else 1
    fake = FakeClinicAPI()
    fake.fail_times("transfer_appointment", sends, error)
    gateway, _ = _gateway(fake)
    journal = RecordingJournal()
    with bind_journal(journal), pytest.raises(ClinicWriteRejected) as exc:
        gateway.transfer(_outbound("c_rej"), "OUT_OF_SCOPE")
    assert (exc.value.status, exc.value.code, exc.value.retryable) == (
        error.status,
        error.code,
        retryable,
    )
    assert journal.statuses == ["begin", "failed"] * sends and fake.writes == []
    assert [key for key, _ in fake.requests] == ["c_rej:3:transfer"] * sends


def test_read_failure_before_send_is_rejection_without_journal_entry() -> None:
    fake = FakeClinicAPI()
    fake.fail_times("get_appointment", WRITE_MAX_SENDS, clinic_error(503, "UPSTREAM"))
    gateway, _ = _gateway(fake)
    journal = RecordingJournal()
    with bind_journal(journal), pytest.raises(ClinicWriteRejected) as exc:
        gateway.transfer(_outbound("c_read"), "OUT_OF_SCOPE")
    assert exc.value.code == "UPSTREAM" and exc.value.retryable is True
    assert journal.events == [] and fake.requests == []  # chưa gửi lệnh ghi nào


def test_unknown_outcome_on_every_send_is_journaled_as_unknown() -> None:
    fake = FakeClinicAPI()
    fake.fail_unknown("transfer_appointment", WRITE_MAX_SENDS, apply_first=True)
    gateway, clock = _gateway(fake)
    journal = RecordingJournal()
    with bind_journal(journal), pytest.raises(WriteOutcomeUnknown):
        gateway.transfer(_outbound("c_unk"), "OUT_OF_SCOPE")
    # Mock đã ghi nhưng mọi lần gửi lại đều timeout: nhật ký UNKNOWN, không ghi thêm lần nào
    assert journal.statuses == ["begin", "unknown"]
    assert fake.writes == [("apt_00417", "TRANSFERRED", {"transfer_reason": "OUT_OF_SCOPE"})]
    assert [key for key, _ in fake.requests] == ["c_unk:3:transfer"] * WRITE_MAX_SENDS
    assert clock.sleeps == list(WRITE_BACKOFF_S)


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
        assert status not in str(exc.value)


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


# --- T-12: phục hồi lỗi ghi ------------------------------------------------------------------


def _version_reads(fake: FakeClinicAPI) -> int:
    return sum(call.operation == "get_appointment" for call in fake.calls)


@pytest.mark.parametrize("apply_first", [True, False], ids=["applied", "not_applied"])
def test_timeout_resends_the_identical_request_and_writes_once(apply_first: bool) -> None:
    """Chưa rõ kết quả: gửi lại cùng key + cùng If-Match. Mock đã ghi thì replay, chưa thì ghi lần đầu.

    Đọc lại version trước khi gửi lại sẽ đổi If-Match -> mock trả 422 thay vì replay; test này đỏ
    nếu Gateway làm vậy (fake mô phỏng đúng dấu vân tay idempotency của mock).
    """
    fake = FakeClinicAPI()
    fake.fail_next("confirm_appointment", outcome_unknown=True, apply_first=apply_first)
    gateway, clock = _gateway(fake)
    ctx = _ready_to_confirm("c_t12_timeout")
    _agree_confirm(ctx)
    journal = RecordingJournal()

    with bind_journal(journal):
        result = gateway.confirm(ctx)

    assert result["status"] == "CONFIRMED"
    assert [status for _, status, _ in fake.writes] == ["CONFIRMED"]
    assert [key for key, _ in fake.requests] == ["c_t12_timeout:3:confirm"] * 2
    assert _version_reads(fake) == 1
    # Lệnh vẫn PENDING giữa hai lần gửi: nhật ký không có UNKNOWN (UNKNOWN xóa nội dung phiên)
    assert journal.statuses == ["begin", "succeeded"]
    assert clock.sleeps == [WRITE_BACKOFF_S[0]]


def test_timeout_after_the_write_budget_is_spent_is_not_resent() -> None:
    fake = FakeClinicAPI()
    fake.delay("transfer_appointment", WRITE_BUDGET_S - 0.5, times=1)
    fake.fail_next("transfer_appointment", outcome_unknown=True, apply_first=True)
    gateway, clock = _gateway(fake)
    journal = RecordingJournal()

    with bind_journal(journal), pytest.raises(WriteOutcomeUnknown):
        gateway.transfer(_outbound("c_t12_budget"), "OUT_OF_SCOPE")

    assert len(fake.requests) == 1
    assert journal.statuses == ["begin", "unknown"]
    assert WRITE_BACKOFF_S[0] not in clock.sleeps


def test_rate_limited_once_is_resent_with_the_same_key() -> None:
    fake = FakeClinicAPI()
    fake.fail_next("transfer_appointment", clinic_error(429, "RATE_LIMITED"))
    gateway, clock = _gateway(fake)
    journal = RecordingJournal()

    with bind_journal(journal):
        result = gateway.transfer(_outbound("c_t12_429"), "OUT_OF_SCOPE")

    assert result["status"] == "TRANSFERRED"
    assert [key for key, _ in fake.requests] == ["c_t12_429:3:transfer"] * 2
    assert journal.statuses == ["begin", "failed", "begin", "succeeded"]
    assert clock.sleeps == [WRITE_BACKOFF_S[0]]


def test_version_conflict_then_timeout_after_apply_still_writes_once() -> None:
    fake = FakeClinicAPI()
    fake.fail_next("confirm_appointment", clinic_error(409, "VERSION_CONFLICT"))
    fake.fail_next("confirm_appointment", outcome_unknown=True, apply_first=True)
    gateway, _ = _gateway(fake)
    ctx = _ready_to_confirm("c_t12_vc")
    _agree_confirm(ctx)
    journal = RecordingJournal()

    with bind_journal(journal):
        assert gateway.confirm(ctx)["status"] == "CONFIRMED"

    assert [status for _, status, _ in fake.writes] == ["CONFIRMED"]
    assert [key for key, _ in fake.requests] == ["c_t12_vc:3:confirm"] * 3
    # Đọc lại version đúng một lần, sau VERSION_CONFLICT; lần gửi sau timeout giữ version đó
    assert _version_reads(fake) == 2
    assert journal.statuses == ["begin", "failed", "begin", "succeeded"]


def test_transient_version_read_failure_is_read_again_before_any_write() -> None:
    fake = FakeClinicAPI()
    fake.fail_next("get_appointment", clinic_error(503, "UPSTREAM"))
    gateway, _ = _gateway(fake)
    journal = RecordingJournal()

    with bind_journal(journal):
        assert gateway.transfer(_outbound("c_t12_read"), "OUT_OF_SCOPE")["status"] == "TRANSFERRED"

    assert journal.statuses == ["begin", "succeeded"] and len(fake.requests) == 1


def test_unreachable_resent_after_timeout_increments_attempt_count_once() -> None:
    """§4.2.5: cùng Idempotency-Key không được tăng attempt_count hai lần."""
    fake = FakeClinicAPI()
    fake.fail_next("mark_unreachable", outcome_unknown=True, apply_first=True)
    gateway, _ = _gateway(fake)

    with bind_journal(RecordingJournal()):
        assert gateway.mark_unreachable(_outbound("c_t12_ur"), "SILENCE")["status"] == "UNREACHABLE"

    assert fake.appointments["apt_00417"]["attempt_count"] == 1
    assert [key for key, _ in fake.requests] == ["c_t12_ur:3:unreachable"] * 2


def test_slot_taken_is_not_resent() -> None:
    fake = FakeClinicAPI()
    fake.fail_next("reschedule_appointment", clinic_error(409, "SLOT_TAKEN"))
    gateway, _ = _gateway(fake)

    with bind_journal(RecordingJournal()), pytest.raises(SlotTaken):
        gateway.reschedule(_ready_to_reschedule("slot_91d2"), "slot_91d2")

    assert len(fake.requests) == 1 and fake.writes == []


def test_reschedule_reports_success_only_for_the_chosen_slot() -> None:
    fake = FakeClinicAPI()
    gateway, _ = _gateway(fake)
    with bind_journal(RecordingJournal()):
        result = gateway.reschedule(_ready_to_reschedule("slot_91d2"), "slot_91d2")
    assert (result["status"], result["new_slot_id"]) == ("RESCHEDULED", "slot_91d2")

    fake = FakeClinicAPI()
    fake.after_next("reschedule_appointment", lambda body: body.update(new_slot_id="slot_aa01"))
    gateway, _ = _gateway(fake)
    with bind_journal(RecordingJournal()), pytest.raises(WriteOutcomeUnknown):
        gateway.reschedule(_ready_to_reschedule("slot_91d2", "c_rs_other"), "slot_91d2")


def _confirm(gateway: ClinicGateway) -> Any:
    ctx = _ready_to_confirm("c_t12_status")
    _agree_confirm(ctx)
    return gateway.confirm(ctx)


def _cancel(gateway: ClinicGateway) -> Any:
    ctx = _ready_to_cancel("c_t12_status")
    _agree_cancel(ctx)
    return gateway.cancel(ctx, "PATIENT_UNAVAILABLE")


@pytest.mark.parametrize(
    "operation, write",
    [
        ("confirm_appointment", _confirm),
        ("cancel_appointment", _cancel),
        ("transfer_appointment", lambda g: g.transfer(_outbound("c_t12_status"), "OUT_OF_SCOPE")),
        ("mark_unreachable", lambda g: g.mark_unreachable(_outbound("c_t12_status"), "SILENCE")),
        (
            "reschedule_appointment",
            lambda g: g.reschedule(_ready_to_reschedule("slot_91d2", "c_t12_status"), "slot_91d2"),
        ),
    ],
)
def test_a_2xx_with_the_wrong_status_is_not_success(operation: str, write) -> None:
    """D-2: Gateway chỉ trả thành công khi body ở đúng trạng thái đích, cho mọi thao tác ghi."""
    fake = FakeClinicAPI()
    fake.after_next(operation, lambda body: body.update(status="SCHEDULED"))
    gateway, _ = _gateway(fake)
    journal = RecordingJournal()
    with bind_journal(journal), pytest.raises(WriteOutcomeUnknown) as exc:
        write(gateway)
    assert "trả status SCHEDULED" in str(exc.value)
    assert len(fake.requests) == 1  # không gửi lại khi mock đã trả lời
    # Kiểm tra TRƯỚC khi ghi nhật ký: không có lệnh SUCCEEDED nào thiếu bằng chứng
    assert journal.statuses == ["begin", "unknown"]


def test_each_send_is_a_traced_clinic_attempt() -> None:
    fake = FakeClinicAPI()
    fake.fail_next("transfer_appointment", outcome_unknown=True, apply_first=True)
    gateway, _ = _gateway(fake)
    with collect_api_calls() as calls, bind_journal(RecordingJournal()):
        gateway.transfer(_outbound("c_t12_trace"), "OUT_OF_SCOPE")
    sends = [c for c in calls if c.operation == "transfer_appointment"]
    assert [c.outcome for c in sends] == ["unknown", "ok"]


# --- T-12 sau review: đã có lần gửi chưa rõ thì không bao giờ là "từ chối" -----------------------


@pytest.mark.parametrize(
    "later",
    [
        [clinic_error(429, "RATE_LIMITED")] * (WRITE_MAX_SENDS - 1),
        [ClinicAPIError(None, "CONNECT_ERROR", "refused", outcome_known=True)]
        * (WRITE_MAX_SENDS - 1),
        [clinic_error(409, "VERSION_CONFLICT")],
        [clinic_error(409, "INVALID_STATE_TRANSITION")],
        [clinic_error(404, "NOT_FOUND")],
    ],
    ids=["429", "connect_error", "version_conflict", "invalid_state", "not_found"],
)
def test_a_definite_error_after_an_uncertain_send_is_still_unknown(later) -> None:
    """Lần gửi đầu timeout (mock ĐÃ ghi), lần gửi lại gặp lỗi xác định: vẫn chưa rõ kết quả.

    Báo "từ chối" ở đây sẽ làm Dialogue chuyển máy và ghi /transfer đè lên lịch đã CONFIRMED.
    """
    fake = FakeClinicAPI()
    fake.fail_next("confirm_appointment", outcome_unknown=True, apply_first=True)
    for error in later:
        fake.fail_next("confirm_appointment", error)
    gateway, _ = _gateway(fake)
    ctx = _ready_to_confirm("c_t12_mixed")
    _agree_confirm(ctx)
    journal = RecordingJournal()

    with bind_journal(journal), pytest.raises(WriteOutcomeUnknown):
        gateway.confirm(ctx)

    assert journal.statuses == ["begin", "unknown"]  # không có FAILED cho lệnh có thể đã áp dụng
    assert [status for _, status, _ in fake.writes] == ["CONFIRMED"]
    assert _version_reads(fake) == 1  # không đọc lại version, kể cả sau VERSION_CONFLICT


def test_uncertain_then_rate_limited_then_replayed_is_success() -> None:
    fake = FakeClinicAPI()
    fake.fail_next("confirm_appointment", outcome_unknown=True, apply_first=True)
    fake.fail_next("confirm_appointment", clinic_error(429, "RATE_LIMITED"))
    gateway, _ = _gateway(fake)
    ctx = _ready_to_confirm("c_t12_replay")
    _agree_confirm(ctx)
    journal = RecordingJournal()

    with bind_journal(journal):
        assert gateway.confirm(ctx)["status"] == "CONFIRMED"

    assert journal.statuses == ["begin", "succeeded"]
    assert [status for _, status, _ in fake.writes] == ["CONFIRMED"]
    assert len(fake.requests) == WRITE_MAX_SENDS


def test_version_conflict_is_always_reread_even_after_transient_retries() -> None:
    """AC-5 / §4.2.5: lần gửi lại do VERSION_CONFLICT không bị giới hạn lỗi tạm thời chặn."""
    fake = FakeClinicAPI()
    fake.fail_times("confirm_appointment", WRITE_MAX_SENDS - 1, clinic_error(429, "RATE_LIMITED"))
    fake.fail_next("confirm_appointment", clinic_error(409, "VERSION_CONFLICT"))
    gateway, _ = _gateway(fake)
    ctx = _ready_to_confirm("c_t12_vc_last")
    _agree_confirm(ctx)

    with bind_journal(RecordingJournal()):
        assert gateway.confirm(ctx)["status"] == "CONFIRMED"

    assert _version_reads(fake) == 2
    assert [key for key, _ in fake.requests] == ["c_t12_vc_last:3:confirm"] * (WRITE_MAX_SENDS + 1)


def test_a_non_json_2xx_on_write_is_unknown_not_rejected() -> None:
    """Mock đã nhận lệnh (2xx) nhưng body hỏng: không được chuyển máy như lệnh bị từ chối."""
    fake = FakeClinicAPI()
    bad_body = ClinicAPIError(200, "BAD_RESPONSE", "Body không phải JSON", outcome_known=False)
    # Lần đầu mock ghi rồi mới hỏng body; các lần gửi lại vẫn nhận body hỏng
    fake.fail_next("confirm_appointment", bad_body, apply_first=True)
    fake.fail_times("confirm_appointment", WRITE_MAX_SENDS - 1, bad_body)
    gateway, _ = _gateway(fake)
    ctx = _ready_to_confirm("c_t12_nonjson")
    _agree_confirm(ctx)
    journal = RecordingJournal()

    with bind_journal(journal), pytest.raises(WriteOutcomeUnknown):
        gateway.confirm(ctx)

    assert journal.statuses == ["begin", "unknown"]
    assert [status for _, status, _ in fake.writes] == ["CONFIRMED"]


# --- T-12 rà soát lần 2: ngân sách chung cho cả lượt ------------------------------------------


def test_the_write_budget_is_shared_by_every_write_in_the_turn() -> None:
    """Clinic không kết nối được: confirm dùng hết ngân sách thì /transfer cùng lượt chỉ thử một lần."""
    fake = FakeClinicAPI()
    gateway, clock = _gateway(fake)
    fake.delay("*", 1.0)  # connect timeout
    fake.fail_always("*", ClinicAPIError(None, "CONNECT_ERROR", "down", outcome_known=True))
    ctx = _ready_to_confirm("c_t12_turn")
    _agree_confirm(ctx)

    with bind_journal(RecordingJournal()):
        with pytest.raises(ClinicWriteRejected):
            gateway.confirm(ctx)
        calls_after_confirm = len(fake.calls)
        with pytest.raises(ClinicWriteRejected):
            gateway.transfer(ctx, "SYSTEM_ERROR")

    assert len(fake.calls) - calls_after_confirm == 1  # một lần đọc version, không thử lại
    assert clock.now <= WRITE_BUDGET_S + 2.0


def test_a_new_turn_gets_a_fresh_write_budget() -> None:
    fake = FakeClinicAPI()
    gateway, clock = _gateway(fake)
    fake.fail_next("transfer_appointment", clinic_error(404, "NOT_FOUND"))  # lịch giữ nguyên
    with bind_journal(RecordingJournal()), pytest.raises(ClinicWriteRejected):
        gateway.transfer(_outbound("c_t12_turn1"), "OUT_OF_SCOPE")
    clock.now += WRITE_BUDGET_S * 10  # lượt sau, rất lâu sau đó
    fake.fail_next("transfer_appointment", clinic_error(429, "RATE_LIMITED"))
    with bind_journal(RecordingJournal()):
        assert gateway.transfer(_outbound("c_t12_turn2"), "OUT_OF_SCOPE")["status"] == "TRANSFERRED"
    assert clock.sleeps == [WRITE_BACKOFF_S[0]]


def test_a_dropped_connection_on_the_version_read_is_read_again() -> None:
    fake = FakeClinicAPI()
    fake.fail_next(
        "get_appointment", ClinicAPIError(None, "TRANSPORT_ERROR", "reset", outcome_known=False)
    )
    gateway, _ = _gateway(fake)
    with bind_journal(RecordingJournal()):
        assert gateway.transfer(_outbound("c_t12_reset"), "OUT_OF_SCOPE")["status"] == "TRANSFERRED"
    assert _version_reads(fake) == 2
