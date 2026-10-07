"""Các case reschedule của eval mentor (05-10-2026), chạy đúng lời người gọi trên sim `mentor_mock()`.

Dữ liệu như mock deploy: apt_00417 lúc 15:30 thứ Tư 14/10; ngày 14/10 chỉ còn `slot_91d2` (15:00). Đồng
hồ là lúc chạy eval. Mỗi case chạy ở ba chế độ của tầng ngữ nghĩa:

- `rule`: không có model, chỉ có luật.
- `llm`: model đọc câu nêu giờ khác thành CHANGE_INTENT/RESCHEDULE (log eval rs-02, rs-04: 1,75 s, 1,93 s).
- `timeout`: model lỗi ở mọi lượt được gọi (bench run_49c637d1: model chậm ~6 s ở rs-03, rs-04).

Kết quả không được phụ thuộc vào model ở bất kỳ lượt nào.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pytest

from callbot.engine import CallStart
from callbot.engine.dialogue import templates as t
from callbot.engine.extraction.schema import VN_TZ, Intent
from callbot.engine.extraction.semantic import ReplyKind, SemanticContext, SemanticOutcome
from clinic_mock_sim import FakeClinicAPI
from tests.engine.test_orchestrator import _run, create_orchestrator

NOW = datetime(2026, 10, 5, 15, 16, tzinfo=VN_TZ)
IDENTITY = ["Alo", "Nguyễn Văn A", "Mười bốn tháng ba năm một nghìn chín trăm bảy mươi tám"]
RESCHEDULED = ("RESCHEDULED", None, [("apt_00417", "RESCHEDULED", {"new_slot_id": "slot_91d2"})])
TRANSFERRED = ("TRANSFERRED", "PATIENT_REQUEST", [])


@dataclass(frozen=True)
class Case:
    lines: list[str]
    expected: tuple[str, Optional[str], list]


CASES = {
    "qc-rs-02": Case(
        [*IDENTITY, "Đổi cho tôi sang 5 giờ chiều ngày 14", "Không có thì 3 giờ cũng được"],
        RESCHEDULED,
    ),
    "qc-rs-03": Case(
        [*IDENTITY, "Sáng mai khoảng 9 giờ có được không?", "Vậy 3 giờ chiều ngày 14 cũng được"],
        RESCHEDULED,
    ),
    "qc-rs-04": Case(
        [*IDENTITY, "Cho tôi ba giờ kém mười lăm chiều ngày 14", "Thế ba giờ cũng được"],
        RESCHEDULED,
    ),
    "qc-rs-05": Case([*IDENTITY, "Đổi sang 15h ngày 14/10", "Đúng rồi, 15 giờ"], RESCHEDULED),
    "qc-rs-06": Case(
        [*IDENTITY, "Đổi sang ngày 15... à không, vẫn ngày 14 nhưng sớm hơn chút", "Ừ, 3 giờ được"],
        RESCHEDULED,
    ),
    "qc-rs-07": Case(
        [
            "Alo, tôi là Nguyễn Văn A, sinh 14/3/78, tôi muốn đổi lịch sang sớm hơn trong chiều ngày 14",
            "Vâng, 3 giờ được",
        ],
        RESCHEDULED,
    ),
    "qc-rs-08": Case(
        [
            *IDENTITY,
            "Tôi muốn đổi lịch",
            "Không, tôi chỉ đi được 5 giờ chiều thôi",
            "Không có 5 giờ thì thôi",
        ],
        TRANSFERRED,
    ),
}


class _ModelReadsChangeIntent:
    """Model eval: câu nêu giờ khác ở câu đọc lịch là ý định đổi lịch; các câu khác không có ý kiến."""

    def analyze(self, context: SemanticContext) -> Optional[SemanticOutcome]:
        return SemanticOutcome(
            ReplyKind.CHANGE_INTENT, intent=Intent.RESCHEDULE, intent_span=context.transcript
        )


class _ModelDown:
    def analyze(self, context: SemanticContext) -> Optional[SemanticOutcome]:
        raise TimeoutError("model slow")


MODELS = {"rule": None, "llm": _ModelReadsChangeIntent, "timeout": _ModelDown}


def _outbound_call(call_id: str, model: Optional[str] = None, clinic=None):
    clinic = clinic or FakeClinicAPI.mentor_mock()
    bot = create_orchestrator(clinic)
    bot.sessions._clock = lambda: NOW
    semantic = MODELS[model] if model else None
    if semantic is not None:
        bot._extractor._semantic = semantic()
    bot.start_call(CallStart(call_id=call_id, direction="outbound", appointment_id="apt_00417"))
    return clinic, bot


@pytest.mark.parametrize("model", list(MODELS))
@pytest.mark.parametrize("case", list(CASES))
def test_mentor_reschedule_case(case: str, model: str) -> None:
    spec = CASES[case]
    clinic, bot = _outbound_call(f"{case}-{model}", model)

    action = _run(bot, f"{case}-{model}", spec.lines)

    outcome, reason, writes = spec.expected
    assert (action.outcome, action.transfer_reason) == (outcome, reason)
    assert [w for w in clinic.writes if w[1] == "RESCHEDULED"] == writes
    if outcome == "TRANSFERRED":
        assert clinic.appointments["apt_00417"]["starts_at"].startswith("2026-10-14T15:30")


# --- "sớm hơn": mốc là giờ lịch hẹn, không phụ thuộc dữ liệu mock (contract §4.3: seed từng case) ----

LATE_ON_THE_14TH = {
    "slot_id": "slot_late",
    "clinic_id": "cl_vinmec",
    "start_time": "2026-10-14T16:00:00+07:00",
}


@pytest.mark.parametrize("case", ["qc-rs-06", "qc-rs-07"])
def test_earlier_never_offers_a_slot_after_the_current_appointment(case: str) -> None:
    clinic = FakeClinicAPI.mentor_mock()
    clinic.seed_slot(LATE_ON_THE_14TH)
    clinic, bot = _outbound_call(f"{case}-seed", clinic=clinic)
    lines = CASES[case].lines
    action = _run(bot, f"{case}-seed", lines[:-1])
    assert "4 giờ chiều" not in action.utterance and "3 giờ chiều" in action.utterance
    action = _run(bot, f"{case}-seed", lines[-1:], start=len(lines))
    assert action.outcome == "RESCHEDULED"
    assert [w for w in clinic.writes if w[1] == "RESCHEDULED"] == RESCHEDULED[2]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Đổi sớm hơn được không em", "ngày 14 tháng 10 còn khung 3 giờ chiều"),
        ("Muộn hơn chút được không", "10 giờ 30 sáng thứ Năm ngày 15 tháng 10"),
    ],
)
def test_earlier_or_later_at_the_readback_is_a_reschedule_request(line: str, expected: str) -> None:
    clinic, bot = _outbound_call(f"rel-{line}")
    action = _run(bot, f"rel-{line}", [*IDENTITY, line])
    assert expected in action.utterance and clinic.writes == []


# --- R-43: yêu cầu đổi lịch nói cùng lượt xác minh danh tính (qc-rs-07) ----------------------------


def test_request_in_the_identity_turn_is_offered_right_after_verification() -> None:
    clinic, bot = _outbound_call("r43-offer")
    action = _run(bot, "r43-offer", CASES["qc-rs-07"].lines[:1])
    assert action.state == "AWAITING_CONFIRMATION" and clinic.writes == []
    assert "ngày 14 tháng 10 còn khung 3 giờ chiều" in action.utterance


def test_request_with_a_wrong_identity_discloses_nothing() -> None:
    """SF-03: yêu cầu chỉ được lưu; sai danh tính thì chuyển máy, không đọc khung, không ghi."""
    clinic, bot = _outbound_call("r43-wrong")
    action = _run(
        bot,
        "r43-wrong",
        ["Tôi là Nguyễn Văn B, sinh 14/3/78, tôi muốn đổi lịch sang chiều ngày 14"],
    )
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "IDENTITY_FAILED")
    assert clinic.slot_reads == 0 and "14 tháng 10" not in action.utterance
    assert [w for w in clinic.writes if w[1] == "RESCHEDULED"] == []


def test_the_date_of_birth_is_not_a_time_criterion() -> None:
    """ "sinh 14/3/78": ngày sinh không thành ngày muốn đổi; yêu cầu không nêu ngày thì đọc khung sớm nhất."""
    clinic, bot = _outbound_call("r43-dob")
    action = _run(bot, "r43-dob", ["Nguyễn Văn A, sinh 14/03/1978, tôi muốn đổi lịch khám"])
    assert action.state == "OFFERING_SLOTS" and clinic.writes == []
    assert "tháng 3" not in action.utterance


def test_a_request_without_the_identity_is_kept_until_verification() -> None:
    """Như yêu cầu hủy (QC qc-cn-08): lời xin đổi ở lượt chưa có ngày sinh vẫn dùng lượt hỏi lại (R-40),
    được giữ qua phiên lưu và mời khung theo lời đó ngay khi xác minh xong; trước đó không đọc khung."""
    clinic, bot = _outbound_call("r43-held")
    action = _run(bot, "r43-held", ["Nguyễn Văn A", "tôi muốn đổi lịch sang chiều ngày 14"])
    assert action.state == "AWAITING_IDENTITY" and clinic.slot_reads == 0
    action = _run(bot, "r43-held", ["14/03/1978"], start=3)
    assert "chiều thứ Tư ngày 14 tháng 10 còn khung 3 giờ chiều" in action.utterance
    assert clinic.writes == []


def test_a_cancel_request_in_the_identity_turn_asks_the_cancel_confirmation() -> None:
    """QC qc-cn-08: yêu cầu hủy cùng lượt danh tính là lượt yêu cầu; xác minh xong hỏi xác nhận hủy (lượt
    thứ hai của SF-05), không mở luồng đổi lịch, không đọc khung, không ghi."""
    clinic, bot = _outbound_call("r43-cancel")
    action = _run(bot, "r43-cancel", ["Tôi là Nguyễn Văn A, sinh 14/3/78, tôi muốn hủy lịch"])
    assert action.state == "AWAITING_CONFIRMATION"
    assert action.utterance.endswith(t.CANCEL_RECONFIRM)
    assert clinic.slot_reads == 0 and clinic.writes == []
