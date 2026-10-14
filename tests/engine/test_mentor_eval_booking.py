"""Bộ qc-ib (đặt lịch inbound) của eval mentor 13-10-2026, chạy đúng lời người gọi trên sim — ground truth
của luồng đặt lịch (plan `docs/plans/t11-booking-inbound-2026-10-13.md` §1.1).

Harness gửi `caller_number` là số đã đăng ký của người gọi (mentor bổ sung chiều 13-10). Người gọi là hai
bản ghi per-tenant của mock, chưa có lịch hẹn: Nguyễn Thị Mai (0912345678, 12/04/1985) và Trần Văn Nam
(0987654321, 03/11/1972). Đồng hồ là lúc mentor chạy: thứ Ba 13/10/2026 10:00.

Lượt sau chỗ bot của lần chạy 3 dừng chưa biết: các câu đó ghi chú "đoán". qc-ib-03 / 05 không biết harness
gửi số nào nên chạy cả số không có hồ sơ lẫn số có hồ sơ.

Mỗi case chạy trên seed gốc của mock (chỉ `slot_91d2` 14/10 15:00) và trên mock deploy của đội (thêm 10
khung demo), ở ba chế độ model: kết quả không phụ thuộc model, và cả hai tầng model (hiểu ý, chọn khung)
không được gọi ở lượt nào — luật quyết hết các câu của mentor.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pytest

from callbot.engine import CallerInput, CallStart
from callbot.engine.dialogue import templates as t
from callbot.engine.extraction.schema import VN_TZ, Intent
from callbot.engine.extraction.semantic import ReplyKind, SemanticContext, SemanticOutcome
from clinic_mock_sim import FakeClinicAPI
from tests.engine.test_orchestrator import create_orchestrator

NOW = datetime(2026, 10, 13, 10, 0, tzinfo=VN_TZ)
MAI, NAM, UNKNOWN = "0912345678", "0987654321", "0911111111"
MAI_DOB = "Mười hai tháng tư năm một nghìn chín trăm tám mươi lăm"
NAM_DOB = "Ngày 3 tháng 11 năm 1972"
BOOKED = ("BOOKED", None)


@dataclass(frozen=True)
class Case:
    phone: str
    lines: list[str]
    expected: tuple[str, Optional[str]]


CASES = {
    "qc-ib-01": Case(
        MAI,
        [
            "Alo, tôi muốn đặt lịch khám",
            "Nguyễn Thị Mai",
            MAI_DOB,
            "Khám tổng quát",
            "Còn lịch nào gần nhất không em?",
            "Được, em đặt giúp chị",  # đoán
        ],
        BOOKED,
    ),
    "qc-ib-02": Case(
        NAM,
        [
            "Cho tôi đặt lịch khám",
            "Trần Văn Nam",
            NAM_DOB,
            "Chiều thứ tư ngày 14 tháng này được không?",
            "Ừ, 3 giờ chiều đó được",
        ],
        BOOKED,
    ),
    "qc-ib-03-unknown-number": Case(
        UNKNOWN, ["Tôi muốn đặt lịch"], ("TRANSFERRED", "PATIENT_NOT_FOUND")
    ),
    "qc-ib-03-registered-number": Case(
        MAI,
        [
            "Tôi muốn đặt lịch",
            "Hoàng Văn Không Có",
            "Mười tháng mười năm một nghìn chín trăm chín mươi",  # đoán
        ],
        ("TRANSFERRED", "PATIENT_NOT_FOUND"),
    ),
    "qc-ib-04": Case(
        MAI,
        ["Tôi muốn đặt lịch khám", "Nguyễn Thị Mai", "Hai mươi tháng mười năm 1990"],
        ("TRANSFERRED", "PATIENT_NOT_FOUND"),
    ),
    "qc-ib-05-unknown-number": Case(
        UNKNOWN,
        ["Tôi chưa có hồ sơ ở đây, em tạo mới giúp tôi rồi đặt lịch luôn nhé"],
        ("TRANSFERRED", "PATIENT_NOT_FOUND"),
    ),
    "qc-ib-05-registered-number": Case(
        MAI,
        ["Tôi chưa có hồ sơ ở đây, em tạo mới giúp tôi rồi đặt lịch luôn nhé"],
        ("TRANSFERRED", "PATIENT_NOT_FOUND"),
    ),
    "qc-ib-06": Case(
        NAM,
        [
            "Đặt lịch khám cho tôi",
            "Trần Văn Nam",
            NAM_DOB,
            "Tôi chỉ đi được 7 giờ sáng chủ nhật",
            "Giờ khác không được",
        ],
        ("TRANSFERRED", "PATIENT_REQUEST"),
    ),
    "qc-ib-07": Case(
        MAI,
        [
            "Tôi muốn đặt lịch",
            "Nguyễn Thị Mai",
            MAI_DOB,
            "Đặt cho chị 8 giờ sáng mai",
            "Không có thì giờ em vừa nói cũng được",
        ],
        BOOKED,
    ),
    "qc-ib-08": Case(
        NAM,
        [
            "Tôi muốn đặt lịch khám",
            "Trần Văn Nam",
            NAM_DOB,
            "Tôi hay đau bụng bên phải, nên khám khoa nào em?",
        ],
        ("TRANSFERRED", "CLINICAL_QUESTION"),
    ),
    "qc-ib-09": Case(
        MAI,
        ["Cho hỏi đặt lịch có dùng bảo hiểm y tế được không?"],
        ("TRANSFERRED", "OUT_OF_SCOPE"),
    ),
    "qc-ib-10": Case(
        MAI,
        [
            "Chào em, chị là Nguyễn Thị Mai, sinh 12/4/1985, muốn đặt khám tổng quát chiều 14 tháng 10",
            "Vâng, đặt giúp chị",
        ],
        BOOKED,
    ),
}


class _SemanticModel:
    """Tầng hiểu ý (Jev / Luna) giả: đếm số lần được gọi."""

    def __init__(self, mode: str) -> None:
        self.mode, self.calls = mode, 0

    def analyze(self, context: SemanticContext) -> Optional[SemanticOutcome]:
        self.calls += 1
        if self.mode == "timeout":
            raise TimeoutError("model slow")
        # Đọc sai mọi câu thành ngoài phạm vi (qc-rs-04 trên giao diện): luật vẫn phải quyết
        return SemanticOutcome(
            ReplyKind.CHANGE_INTENT, intent=Intent.OUT_OF_SCOPE, intent_span=context.transcript
        )


class _SlotModel:
    """Tầng chọn khung giả: đếm số lần được gọi."""

    budget_s = 1.0

    def __init__(self, mode: str) -> None:
        self.mode, self.calls = mode, 0

    def analyze(self, context) -> None:
        self.calls += 1
        if self.mode == "timeout":
            raise TimeoutError("model slow")
        return None


MODES = ["rule", "timeout", "misreads"]
DATASETS = ["canonical", "mentor_mock"]


def _clinic(dataset: str) -> FakeClinicAPI:
    clinic = FakeClinicAPI.mentor_mock()
    if dataset == "canonical":
        # Seed gốc của mock mentor: khung trống duy nhất là slot_91d2 (14/10 15:00)
        clinic.slots = [slot for slot in clinic.slots if slot["slot_id"] == "slot_91d2"]
    return clinic


def _call(call_id: str, phone: Optional[str], lines: list[str], dataset="canonical", mode="rule"):
    clinic = _clinic(dataset)
    bot = create_orchestrator(clinic)
    bot.sessions._clock = lambda: NOW
    semantic = slot = None
    if mode != "rule":
        semantic, slot = _SemanticModel(mode), _SlotModel(mode)
        bot._extractor._semantic = semantic
        bot._extractor._slot_semantic = slot
    actions = [bot.start_call(CallStart(call_id=call_id, direction="inbound", caller_number=phone))]
    for turn, line in enumerate(lines, start=1):
        assert not actions[-1].ended, f"cuộc gọi đã kết thúc trước lượt {turn}"
        actions.append(bot.handle_turn(call_id, CallerInput(turn=turn, text=line)))
    calls = (semantic.calls if semantic else 0) + (slot.calls if slot else 0)
    return actions, clinic, calls


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("dataset", DATASETS)
@pytest.mark.parametrize("case", list(CASES))
def test_mentor_booking_case(case: str, dataset: str, mode: str) -> None:
    spec = CASES[case]
    actions, clinic, calls = _call(
        f"{case}-{dataset}-{mode}", spec.phone, spec.lines, dataset, mode
    )

    last = actions[-1]
    assert last.ended, "kịch bản hết mà bot chưa kết thúc (harness chấm MISSING)"
    assert (last.outcome, last.transfer_reason) == spec.expected
    if last.outcome == "BOOKED":
        # Bảng 2: đúng một lịch mới, trên khung /slots đã mời
        assert [(w[1], w[2]) for w in clinic.writes] == [("BOOKED", {"slot_id": "slot_91d2"})]
    else:
        # Inbound chưa tạo lịch thì không ghi gì (§2.1)
        assert clinic.writes == []
    assert calls == 0, "case mentor phải do luật quyết, không gọi model"


@pytest.mark.parametrize("case", ["qc-ib-01", "qc-ib-10"])
def test_without_caller_number_hands_off_at_turn_one(case: str) -> None:
    """D-10: không có số gọi đến thì không có khóa tra hồ sơ — chuyển máy ở lượt 1, 0 tra cứu, 0 ghi."""
    actions, clinic, _ = _call(f"{case}-null", None, CASES[case].lines[:1])
    assert (actions[-1].outcome, actions[-1].transfer_reason) == (
        "TRANSFERRED",
        "PATIENT_NOT_FOUND",
    )
    assert clinic.patient_lookups == [] and clinic.writes == []


def test_booking_need_asks_the_time_and_department_is_never_spoken() -> None:
    """Xác minh xong (đã nói muốn đặt lịch, chưa nêu giờ) hỏi ngày / buổi; chỉ nêu khoa thì hỏi lại một lần.
    Bot không nhắc lại tên khoa (D-5: mock không nhận khoa)."""
    actions, _, _ = _call("ib01-questions", MAI, CASES["qc-ib-01"].lines)
    questions = t.static_choices(t.ASK_SLOT_PREFERENCE["BOOK"])
    assert actions[3].utterance in questions and actions[4].utterance in questions
    assert actions[3].utterance != actions[4].utterance
    # "gần nhất": một khung sớm nhất, hỏi có/không
    assert (
        actions[5].state == "AWAITING_CONFIRMATION" and "giờ này được không" in actions[5].utterance
    )
    assert all("tổng quát" not in action.utterance.lower() for action in actions)


@pytest.mark.parametrize("dataset", DATASETS)
def test_missing_time_offers_one_nearest_slot(dataset: str) -> None:
    """G21: không có giờ khách xin thì báo rồi mời MỘT khung gần nhất, để "giờ em vừa nói" rõ nghĩa."""
    actions, clinic, _ = _call(f"ib07-{dataset}", MAI, CASES["qc-ib-07"].lines[:4], dataset)
    offer = actions[-1].utterance
    assert offer.startswith(t.SLOT_NO_MATCH) and offer.count("Em còn trống") == 1
    assert "khung" not in offer
    assert "3 giờ chiều" in offer and clinic.writes == []


@pytest.mark.parametrize(
    "line",
    [
        "Dạo này tôi hay đau bụng",
        "Chị bị đau dạ dày, muốn khám tiêu hóa chiều mai",
    ],
)
def test_symptoms_transfer_even_with_a_chosen_department(line: str) -> None:
    """Owner 13-10 (D-11): kể triệu chứng là chuyển máy, kể cả khi đã tự chọn khoa (§1.2.1)."""
    actions, clinic, _ = _call("symptom", NAM, [*CASES["qc-ib-02"].lines[:3], line])
    assert (actions[-1].outcome, actions[-1].transfer_reason) == (
        "TRANSFERRED",
        "CLINICAL_QUESTION",
    )
    assert clinic.writes == []


def test_department_without_symptoms_still_books() -> None:
    actions, clinic, _ = _call(
        "department", NAM, [*CASES["qc-ib-02"].lines[:3], "Khám tiêu hóa chiều mai", "Được"]
    )
    assert actions[-1].outcome == "BOOKED"
    assert [(w[1], w[2]) for w in clinic.writes] == [("BOOKED", {"slot_id": "slot_91d2"})]


def test_symptom_word_inside_a_name_is_not_a_symptom() -> None:
    """Luật lâm sàng nhận "Ho" là triệu chứng: lượt khai tên có đọc ra tên thì không chuyển máy."""
    actions, _, _ = _call("symptom-name", MAI, ["Nguyễn Văn Ho"])
    assert not actions[-1].ended and actions[-1].state == "AWAITING_IDENTITY"


@pytest.mark.parametrize(
    "line, reason",
    [
        ("Đặt lịch khám cho mẹ tôi", "OUT_OF_SCOPE"),
        ("Tôi muốn hủy lịch khám", "OUT_OF_SCOPE"),
        ("Tôi muốn đổi lịch khám sang thứ sáu", "OUT_OF_SCOPE"),
    ],
)
def test_out_of_scope_requests_at_identity_turn_transfer_without_verifying(
    line: str, reason: str
) -> None:
    """Bảng 1: inbound chỉ có bệnh nhân gọi đến tự đặt lịch mới (G12, G22)."""
    actions, clinic, _ = _call("identity-oos", MAI, [line])
    assert (actions[-1].outcome, actions[-1].transfer_reason) == ("TRANSFERRED", reason)
    assert clinic.writes == []


def test_booking_need_at_identity_turn_is_exempt_only_once() -> None:
    """D-2: câu nêu nhu cầu đặt lịch ở bước danh tính không tính hiểu sai — chỉ một lần."""
    actions, _, _ = _call(
        "need-twice", MAI, ["Tôi muốn đặt lịch", "Tôi muốn đặt lịch", "Tôi muốn đặt lịch"]
    )
    assert actions[1].utterance == t.ASK_NAME_FOR_REQUEST and not actions[2].ended
    assert (actions[-1].outcome, actions[-1].transfer_reason) == ("TRANSFERRED", "NOT_UNDERSTOOD")
