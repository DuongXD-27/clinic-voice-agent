"""Output Guard (R-01): chốt kiểm tra duy nhất cho mọi câu bot sắp nói, dùng chung cho HTTP và Phone.

Chỉ `CallOrchestrator` gọi module này, ngay trước khi commit lượt (và trước khi lưu lời mở đầu).
Nguyên tắc: không tin nội dung tự khai. Một câu chỉ được nói khi biết chắc nó do template đã đăng ký
tạo ra và render lại từ dữ liệu gốc Gateway trả về cho ra đúng nguyên văn.

| Luật | Kiểm tra | Mã |
| --- | --- | --- |
| OG-0 | Câu không thuộc allow-list (hằng tĩnh / renderer trong ledger / đọc lại câu hỏi trước), hoặc tham số chuỗi ngoài miền | OUTPUT_UNREGISTERED |
| OG-1 | Câu lộ lịch khi chưa xác minh, hoặc trên voicemail (outcome UNREACHABLE) | SF-03 |
| OG-2 | Appointment ngoài {target, created} | SF-01 |
| OG-3 | Slot không có nguồn / ngoài phạm vi, hoặc render lại ra text khác | SF-02 |
| OG-4 | Dấu hiệu tư vấn lâm sàng | SF-04 |
| OG-5 | Báo thành công không có receipt đúng outcome và đúng đối tượng đã ghi | OUTPUT_UNPROVEN_SUCCESS |
| OG-6 | `ctx.slots` khác snapshot nguồn; `ctx.question` không ứng với câu vừa nói | SF-02 / OUTPUT_UNREGISTERED |

Receipt gate (§3.5) đọc nhật ký lệnh ghi của lượt TRƯỚC mọi fallback: còn lệnh chưa rõ hoặc nhiều lệnh
thành công thì chặn đối soát; đúng một lệnh thành công thì cấm chuyển máy, chỉ được báo đúng kết quả đó.
"""

import inspect
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Optional

from callbot.engine.dialogue import templates as t
from callbot.engine.errors import WriteOutcomeUnknown
from callbot.engine.extraction.schema import QuestionId
from callbot.engine.extraction.text import normalize, strip_diacritics
from callbot.engine.journal import ClinicCommand, JournalEntry
from callbot.engine.policy import guardrails
from callbot.engine.policy.guardrails import SevereFailureBlocked
from callbot.engine.policy.sources import SourceRegistry
from callbot.engine.policy.utterances import (
    OUTPUT_UNPROVEN_SUCCESS,
    OUTPUT_UNREGISTERED,
    RENDERERS,
    STATIC_UTTERANCES,
    RendererSpec,
    RenderRecord,
    UtteranceSpec,
    check_str_args,
)
from callbot.engine.session.context import CallContext, Question
from callbot.engine.types import BotAction, Outcome

SUCCESS_OUTCOMES: frozenset[str] = frozenset({"CONFIRMED", "CANCELLED", "RESCHEDULED", "BOOKED"})
# Lệnh ghi đóng -> outcome. Từ T-12 Gateway chỉ ghi SUCCEEDED khi body ở đúng trạng thái này.
OPERATION_OUTCOME: dict[str, Outcome] = {
    "confirm": "CONFIRMED",
    "cancel": "CANCELLED",
    "reschedule": "RESCHEDULED",
    "book": "BOOKED",
    "transfer": "TRANSFERRED",
    "unreachable": "UNREACHABLE",
}
# Câu đọc lại câu hỏi động của lượt trước: nguồn gốc không persist nên coi như lộ lịch (fail-closed)
_REREAD = UtteranceSpec(
    "QUESTION_REREAD", discloses=True, disclosed_fields=frozenset({"starts_at", "clinic", "status"})
)

_BASE_FIELDS = frozenset({"starts_at", "clinic", "status"})
STATE_FIELDS = {
    "AWAITING_IDENTITY": frozenset(),
    "AWAITING_INTENT": _BASE_FIELDS,
    "AWAITING_CONFIRMATION": _BASE_FIELDS,
    "CLOSING": _BASE_FIELDS,
    "OFFERING_SLOTS": _BASE_FIELDS | {"slot_id"},
}
_FIELD_KEYS = {
    "starts_at": frozenset({"starts_at"}),
    "clinic": frozenset({"clinic", "clinic_id", "clinic_name", "department"}),
    "status": frozenset({"status"}),
    "slot_id": frozenset({"slot_id"}),
}
_NEVER_FIELDS = frozenset(
    {
        "phone",
        "phone_number",
        "caller_number",
        "patient_id",
        "appointment_id",
        "full_name",
        "display_name",
        "dob",
        "provider_name",
        "doctor_name",
        "physician_name",
        "reason",
        "visit_reason",
        "appointment_reason",
        "cancel_reason",
    }
)


def _allowed_fields(inp: "GuardInput") -> frozenset[str]:
    if not inp.ctx.identity_verified or inp.action.outcome == "UNREACHABLE":
        return frozenset()
    state = (
        "CLOSING"
        if inp.action.ended and inp.action.outcome in SUCCESS_OUTCOMES
        else inp.action.state
    )
    return STATE_FIELDS.get(state, frozenset())


def _project(data: dict[str, Any], allowed: frozenset[str]) -> dict[str, Any]:
    keys = set().union(*(_FIELD_KEYS[field] for field in allowed if field in _FIELD_KEYS))
    return {key: value for key, value in data.items() if key in keys}


def _protected_text(inp: "GuardInput") -> None:
    """Detect protected values even if a source smuggles one into an allowed display field."""
    utterance = normalize(inp.action.utterance)
    numeric = re.sub(r"\D", "", utterance)
    allowed = _allowed_fields(inp)

    def walk(data: Any) -> None:
        if isinstance(data, dict):
            for key, value in data.items():
                denied = key in _NEVER_FIELDS or (key == "slot_id" and "slot_id" not in allowed)
                if denied and isinstance(value, str) and value.strip():
                    token = normalize(value)
                    if re.search(r"(?<!\w)" + re.escape(token) + r"(?!\w)", utterance):
                        raise _Violation("OG-1", "SF-03")
                    if key in {"phone", "phone_number", "caller_number"}:
                        digits = re.sub(r"\D", "", value)
                        if len(digits) >= 7 and digits in numeric:
                            raise _Violation("OG-1", "SF-03")
                    if key in {"full_name", "provider_name", "doctor_name", "physician_name"}:
                        if len(token) > 3 and strip_diacritics(token) in strip_diacritics(
                            utterance
                        ):
                            raise _Violation("OG-1", "SF-03")
                walk(value)
        elif isinstance(data, (list, tuple)):
            for item in data:
                walk(item)

    walk(inp.ctx.call.to_dict())
    walk(inp.ctx.identity_reference)
    walk(inp.sources.appointments)
    walk(inp.sources.slots)
    if inp.receipt is not None:
        walk(inp.receipt.result)


@dataclass(frozen=True)
class GuardVerdict:
    ok: bool
    rule: Optional[str] = None  # OG-0 .. OG-6
    code: Optional[str] = None  # SF-0x | OUTPUT_UNREGISTERED | OUTPUT_UNPROVEN_SUCCESS


PASS = GuardVerdict(True)


@dataclass(frozen=True)
class Receipt:
    """Lệnh ghi thành công duy nhất của lượt, lấy từ nhật ký trong RAM (không từ store)."""

    command: ClinicCommand
    result: dict[str, Any]

    @property
    def outcome(self) -> Outcome:
        return OPERATION_OUTCOME[self.command.operation]


@dataclass(frozen=True)
class WriteSummary:
    """Số liệu cho trace: số lệnh đã thử khác số lệnh thành công (unreachable FAILED rồi transfer)."""

    attempted: int
    succeeded: int
    operation: str
    status_match: Optional[bool]


@dataclass(frozen=True)
class GuardInput:
    action: BotAction
    ctx: CallContext
    # Chụp ở đầu lượt, trước Dialogue
    prior_question: Optional[Question]
    ledger: Sequence[RenderRecord]
    sources: SourceRegistry
    receipt: Optional[Receipt]


class _Violation(Exception):
    def __init__(self, rule: str, code: str) -> None:
        self.rule = rule
        self.code = code
        super().__init__(f"{rule} {code}")


# --- Receipt gate -----------------------------------------------------------------


def summarize_writes(entries: Sequence[JournalEntry]) -> WriteSummary:
    succeeded = [entry for entry in entries if entry.status == "SUCCEEDED"]
    operation = succeeded[0].command.operation if len(succeeded) == 1 else "NONE"
    status_match = _status_matches(succeeded[0]) if len(succeeded) == 1 else None
    return WriteSummary(len(entries), len(succeeded), operation, status_match)


def receipt_gate(entries: Sequence[JournalEntry]) -> Optional[Receipt]:
    """§3.5, xét theo thứ tự: chưa rõ -> một thành công -> nhiều thành công -> chỉ từ chối / không lệnh.

    Raise `WriteOutcomeUnknown` (SessionManager chặn đối soát, không chuyển máy) khi còn lệnh
    PENDING / UNKNOWN, khi có từ hai lệnh thành công, hoặc receipt sai trạng thái đích.
    """
    unsettled = [entry for entry in entries if entry.status in ("PENDING", "UNKNOWN")]
    if unsettled:
        keys = ", ".join(entry.command.idempotency_key for entry in unsettled)
        raise WriteOutcomeUnknown(f"lệnh ghi chưa rõ kết quả: {keys}")
    succeeded = [entry for entry in entries if entry.status == "SUCCEEDED"]
    if len(succeeded) > 1:
        keys = ", ".join(entry.command.idempotency_key for entry in succeeded)
        raise WriteOutcomeUnknown(f"nhiều lệnh ghi thành công trong một lượt: {keys}")
    if not succeeded:
        return None
    entry = succeeded[0]
    # Phòng thủ lớp hai sau Gateway (T-12): SUCCEEDED mà sai trạng thái đích là bug, xử lý như chưa rõ
    if not _status_matches(entry) or entry.result is None:
        raise WriteOutcomeUnknown(f"{entry.command.idempotency_key}: receipt sai trạng thái đích")
    return Receipt(entry.command, entry.result)


def _status_matches(entry: JournalEntry) -> bool:
    expected = OPERATION_OUTCOME.get(entry.command.operation)
    return (
        expected is not None
        and isinstance(entry.result, dict)
        and (entry.result.get("status") == expected)
    )


def matches_receipt(action: BotAction, receipt: Receipt) -> bool:
    """Lượt có lệnh ghi thành công phải đóng phiên với đúng outcome và lý do đã ghi."""
    outcome = receipt.outcome
    payload = receipt.command.payload
    transfer_reason = payload.get("transfer_reason") if outcome == "TRANSFERRED" else None
    unreachable_reason = payload.get("unreachable_reason") if outcome == "UNREACHABLE" else None
    return (
        action.ended
        and action.state == "ENDED"
        and action.outcome == outcome
        and action.transfer_reason == transfer_reason
        and action.unreachable_reason == unreachable_reason
    )


def safe_action(receipt: Receipt) -> BotAction:
    """Câu báo không chi tiết cho đúng kết quả đã ghi; outcome và lý do lấy từ receipt."""
    outcome = receipt.outcome
    payload = receipt.command.payload
    return BotAction(
        t.DONE_SAFE[outcome],
        "ENDED",
        ended=True,
        outcome=outcome,
        transfer_reason=payload.get("transfer_reason") if outcome == "TRANSFERRED" else None,
        unreachable_reason=(
            payload.get("unreachable_reason") if outcome == "UNREACHABLE" else None
        ),
    )


# --- Chuẩn hóa trạng thái trước khi kiểm ---------------------------------------------------


def normalize_question(ctx: CallContext, action: BotAction) -> None:
    """Phiên kết thúc thì không còn câu nào chờ trả lời: câu hỏi đặt trong lượt mà chưa được phát
    (vd. Dialogue hỏi rồi Policy chuyển máy NOT_UNDERSTOOD) bị bỏ, không bị kiểm."""
    if action.ended:
        ctx.question = None


# --- Kiểm tra -----------------------------------------------------------------------


def check(inp: GuardInput) -> GuardVerdict:
    try:
        spec, record = _origin(inp)
        _disclosure(inp, spec)
        _protected_text(inp)
        if record is not None:
            _sources(inp, record)
        _clinical(inp.action.utterance)
        _success(inp, spec, record)
        _state(inp)
    except _Violation as violation:
        return GuardVerdict(False, violation.rule, violation.code)
    return PASS


def check_opening(action: BotAction, ctx: CallContext) -> GuardVerdict:
    """Lời mở đầu: không có journal, không đặt chỗ lượt — chỉ được là hằng tĩnh không lộ lịch,
    không kết thúc, không outcome (§3.7)."""
    try:
        spec = STATIC_UTTERANCES.get(action.utterance)
        if spec is None or spec.success_outcome is not None:
            raise _Violation("OG-0", OUTPUT_UNREGISTERED)
        if action.ended or action.outcome is not None:
            raise _Violation("OG-5", OUTPUT_UNPROVEN_SUCCESS)
        if spec.discloses:
            raise _Violation("OG-1", "SF-03")
        _clinical(action.utterance)
        if ctx.slots:
            raise _Violation("OG-6", "SF-02")
        question = ctx.question
        if question is not None and (
            question.text != action.utterance or question.turn != ctx.turn
        ):
            raise _Violation("OG-6", OUTPUT_UNREGISTERED)
    except _Violation as violation:
        return GuardVerdict(False, violation.rule, violation.code)
    return PASS


def check_tts_fallback(utterance: str) -> GuardVerdict:
    """Câu phát bằng audio ghi sẵn khi TTS lỗi (R-39): chỉ được là câu `TRANSFER` tĩnh, nguyên văn,
    không lộ thông tin lịch. Không có lượt, journal hay nguồn dữ liệu để đối chiếu."""
    try:
        spec = STATIC_UTTERANCES.get(utterance)
        if utterance != t.TRANSFER or spec is None or spec.success_outcome is not None:
            raise _Violation("OG-0", OUTPUT_UNREGISTERED)
        if spec.discloses:
            raise _Violation("OG-1", "SF-03")
        _clinical(utterance)
    except _Violation as violation:
        return GuardVerdict(False, violation.rule, violation.code)
    return PASS


def _origin(inp: GuardInput) -> tuple[UtteranceSpec, Optional[RenderRecord]]:
    """OG-0: câu phải khớp nguyên văn một dạng trong allow-list §3.2."""
    utterance = inp.action.utterance
    record = next((item for item in reversed(inp.ledger) if item.text == utterance), None)
    if record is not None:
        spec = RENDERERS.get(record.template_id)
        if spec is None:
            raise _Violation("OG-0", OUTPUT_UNREGISTERED)
        try:
            check_str_args(spec, record.args)
        except SevereFailureBlocked as exc:
            raise _Violation("OG-0", OUTPUT_UNREGISTERED) from exc
        if record.template_id != "SILENCE_REPROMPT":
            return spec, record
        prior = inp.prior_question
        if prior is None or record.args.get("question_text") != prior.text:
            raise _Violation("OG-0", OUTPUT_UNREGISTERED)
        return _reread(inp, prior), None
    static = STATIC_UTTERANCES.get(utterance)
    if static is not None:
        return static, None
    prior = inp.prior_question
    if prior is not None and utterance in (prior.text, _silence_reprompt(prior.text)):
        return _reread(inp, prior), None
    raise _Violation("OG-0", OUTPUT_UNREGISTERED)


def _reread(inp: GuardInput, prior: Question) -> UtteranceSpec:
    """Metadata câu hỏi đọc lại được xác định lại fail-closed: câu tĩnh dùng metadata của hằng,
    câu động coi như lộ lịch. Slot câu hỏi tham chiếu phải còn trong snapshot nguồn."""
    referenced = [prior.slot_id] if prior.slot_id else []
    if prior.question_id is QuestionId.OFFER_SLOTS:
        referenced.extend(inp.ctx.presented_slot_ids)
    available = set(inp.sources.slot_ids)
    if any(slot_id not in available for slot_id in referenced):
        raise _Violation("OG-3", "SF-02")
    return STATIC_UTTERANCES.get(prior.text, _REREAD)


def _disclosure(inp: GuardInput, spec: UtteranceSpec) -> None:
    """OG-1 (SF-03): kể cả khi đọc lại câu hỏi đã từng qua guard ở lượt trước."""
    if spec.discloses and (not inp.ctx.identity_verified or inp.action.outcome == "UNREACHABLE"):
        raise _Violation("OG-1", "SF-03")
    if not spec.disclosed_fields <= _allowed_fields(inp):
        raise _Violation("OG-1", "SF-03")


def _sources(inp: GuardInput, record: RenderRecord) -> None:
    """OG-2 / OG-3: mọi ref phải có nguồn và nằm trong phạm vi; render lại phải ra đúng nguyên văn."""
    spec = RENDERERS[record.template_id]
    allowed_fields = _allowed_fields(inp)
    ctx = inp.ctx
    allowed_appointments = {
        appointment_id
        for appointment_id in (ctx.target_appointment_id, ctx.created_appointment_id)
        if appointment_id
    }
    available = set(inp.sources.slot_ids)
    data: dict[str, Any] = {name: [] for name, kind in spec.sources.items() if kind == "SLOTS"}
    for ref in record.refs:
        kind = spec.sources[ref.param]
        if ref.kind == "APPOINTMENT":
            if ref.id not in allowed_appointments:
                raise _Violation("OG-2", "SF-01")
            if kind == "WRITTEN":
                # Dữ liệu câu báo đã xác nhận là bản ghi Clinic trả về trong receipt
                receipt = inp.receipt
                if receipt is None or receipt.result.get("appointment_id") != ref.id:
                    raise _Violation("OG-5", OUTPUT_UNPROVEN_SUCCESS)
                data[ref.param] = _project(dict(receipt.result), allowed_fields)
            else:
                appointment = inp.sources.appointment(ref.id)
                if appointment is None:
                    raise _Violation("OG-3", "SF-02")
                data[ref.param] = _project(appointment, allowed_fields)
            continue
        if ref.id is None or ref.id not in available:
            raise _Violation("OG-3", "SF-02")
        if spec.slot_scope == "PRESENTED" and ref.id not in ctx.presented_slot_ids:
            raise _Violation("OG-3", "SF-02")
        if spec.slot_scope == "SELECTED" and ref.id != ctx.selected_slot_id:
            raise _Violation("OG-3", "SF-02")
        slot = _project(inp.sources.slot(ref.id), allowed_fields)
        if kind == "SLOTS":
            data[ref.param].append(slot)
        else:
            data[ref.param] = slot
    if set(data) != set(spec.sources):
        raise _Violation("OG-3", "SF-02")
    try:
        rendered = _render(spec, ctx, {**data, **record.args})
    except Exception as exc:
        raise _Violation("OG-3", "SF-02") from exc
    if rendered != record.text:
        raise _Violation("OG-3", "SF-02")


def _render(spec: RendererSpec, ctx: CallContext, arguments: dict[str, Any]) -> str:
    """Gọi hàm gốc (không qua decorator nên không ghi thêm vào ledger)."""
    if "ctx" in inspect.signature(spec.render).parameters:
        arguments = {"ctx": ctx, **arguments}
    return spec.render(**arguments)


def _silence_reprompt(question_text: str) -> str:
    return RENDERERS["SILENCE_REPROMPT"].render(question_text)


def _clinical(utterance: str) -> None:
    """OG-4 (SF-04)."""
    try:
        guardrails.assert_no_clinical_advice(utterance)
    except SevereFailureBlocked as exc:
        raise _Violation("OG-4", "SF-04") from exc


def _success(inp: GuardInput, spec: UtteranceSpec, record: Optional[RenderRecord]) -> None:
    """OG-5: lời báo thành công cần receipt đúng outcome và đúng đối tượng vừa ghi; ngược lại outcome
    thành công phải đi với câu của đúng template thành công."""
    outcome = inp.action.outcome
    expected = spec.success_outcome
    if expected is None:
        if outcome in SUCCESS_OUTCOMES:
            raise _Violation("OG-5", OUTPUT_UNPROVEN_SUCCESS)
        return
    receipt = inp.receipt
    if outcome != expected or receipt is None or receipt.outcome != expected:
        raise _Violation("OG-5", OUTPUT_UNPROVEN_SUCCESS)
    if record is not None and not _bound_to_receipt(record, receipt):
        raise _Violation("OG-5", OUTPUT_UNPROVEN_SUCCESS)


def _bound_to_receipt(record: RenderRecord, receipt: Receipt) -> bool:
    """§3.3 bước 4: ghi slot A mà đọc slot B (B cũng có nguồn) vẫn là báo sai lịch vừa ghi."""
    payload, result = receipt.command.payload, receipt.result
    slots = [ref.id for ref in record.refs if ref.kind == "SLOT"]
    appointments = [ref.id for ref in record.refs if ref.kind == "APPOINTMENT"]
    if record.template_id == "RESCHEDULED_DONE":
        new_slot = payload.get("new_slot_id")
        return slots == [new_slot] and result.get("new_slot_id") == new_slot
    if record.template_id == "BOOKED_DONE":
        return slots == [payload.get("slot_id")] and all(
            appointment == result.get("appointment_id") for appointment in appointments
        )
    if record.template_id == "CONFIRMED_DONE":
        return appointments == [_endpoint_appointment(receipt.command)]
    return not slots and not appointments


def _endpoint_appointment(command: ClinicCommand) -> Optional[str]:
    parts = command.endpoint.strip("/").split("/")
    return parts[1] if len(parts) >= 2 and parts[0] == "appointments" else None


def _state(inp: GuardInput) -> None:
    """OG-6: trạng thái sắp commit phải khớp đúng câu vừa kiểm (sau khi đã chuẩn hóa)."""
    ctx, action, prior = inp.ctx, inp.action, inp.prior_question
    if not inp.sources.slots_intact(ctx):
        raise _Violation("OG-6", "SF-02")
    question = ctx.question
    if action.ended:
        valid = question is None
    elif question == prior:
        # Không đổi: HOLD, "em chưa hiểu", nhắc im lặng khi chưa có câu hỏi
        valid = True
    elif (
        question is not None
        and prior is not None
        and replace(question, turn=prior.turn) == prior
        and question.turn == ctx.turn
    ):
        # Nhắc lại / quay lại / nhắc im lặng: hỏi lại nguyên văn câu đang chờ ở lượt này
        valid = action.utterance in (question.text, _silence_reprompt(question.text))
    else:
        # Hỏi mới: đúng cách `questions.ask()` gán
        valid = (
            question is not None and question.turn == ctx.turn and question.text == action.utterance
        )
    if not valid:
        raise _Violation("OG-6", OUTPUT_UNREGISTERED)
