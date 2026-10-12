"""Tầng model cho câu chọn khung — plan `docs/plans/t10-slot-semantic-jev-2026-10-12.md`.

Không gọi mạng: provider là bản giả. Dữ liệu sim `mentor_mock()`, đồng hồ 12-10-2026 10:00; trang đầu
("Đổi lịch cho tôi") là slot_91d2 14/10 15:00 + slot_b501 15/10 10:30.
"""

import csv
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pytest

from callbot.engine import CallStart
from callbot.engine.dialogue import templates as t
from callbot.engine.extraction.model_budget import invoke_model, model_turn
from callbot.engine.extraction.schema import VN_TZ, QuestionId, SlotAct
from callbot.engine.extraction.slot_semantic import (
    SlotReading,
    SlotSemanticContext,
    SlotSemanticReader,
    ground_slot_reading,
    resolve_slot_act,
)
from callbot.engine.extraction.slot_semantic_jev import (
    ACT_CRITERIA,
    JevSlotSemanticExtractor,
    build_slot_questions,
    build_slot_state,
)
from callbot.engine.extraction.slot_semantic_luna import LunaSlotSemanticExtractor
from callbot.engine.extraction.text import clean, strip_diacritics
from clinic_mock_sim import FakeClinicAPI
from inference.llm.prompt.slot_reply import EXAMPLES, build_slot_messages
from inference.llm.typesafe import ChoiceAnswer, SystemOneReply
from tests.engine.test_mentor_eval_reschedule import CASES as MENTOR_CASES
from tests.engine.test_mentor_eval_reschedule import NOW as MENTOR_NOW
from tests.engine.test_orchestrator import _context, _run, create_orchestrator

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 12, 10, 0, tzinfo=VN_TZ)
FIRST_PAGE = ["Nguyễn Văn A", "14 tháng 3 năm 1978", "Đổi lịch cho tôi"]
READBACK = ["Nguyễn Văn A", "14 tháng 3 năm 1978", "Đổi sang chiều thứ 4 được không"]


@dataclass
class FakeReader:
    """Thay `SlotSemanticReader`: ghi lại mọi lần gọi, trả kết quả cố định (hoặc lỗi)."""

    reading: Optional[SlotReading] = None
    raises: bool = False
    budget_s: float = 4.0
    calls: list[SlotSemanticContext] = field(default_factory=list)
    last_status: Optional[str] = None

    def analyze(self, context: SlotSemanticContext) -> Optional[SlotReading]:
        self.calls.append(context)
        if self.raises:
            raise TimeoutError("model slow")
        if self.reading is None:
            return None
        return ground_slot_reading(self.reading, context)


def _call(call_id: str, reader: Any, direction: str = "outbound", now: datetime = NOW):
    clinic = FakeClinicAPI.mentor_mock()
    bot = create_orchestrator(clinic)
    bot.sessions._clock = lambda: now
    bot._extractor._slot_semantic = reader
    if direction == "outbound":
        start = CallStart(call_id=call_id, direction="outbound", appointment_id="apt_00417")
    else:
        start = CallStart(call_id=call_id, direction="inbound", caller_number="0967769004")
    bot.start_call(start)
    return clinic, bot


def _slot_writes(clinic) -> list:
    return [w for w in clinic.writes if w[1] in ("RESCHEDULED", "BOOKED")]


def _reading(act: str, **kwargs: Any) -> SlotReading:
    return SlotReading(act=act, confident=True, decides_now=True, **kwargs)


# --- C1: 7 case mentor không bao giờ gọi model ---------------------------------------------------


@pytest.mark.parametrize("case", list(MENTOR_CASES))
def test_mentor_cases_never_call_the_slot_model(case: str) -> None:
    """Đếm số lần gọi (không chỉ kết quả cuối): model đọc sai mọi câu vẫn không đổi được kết quả."""
    reader = FakeReader(_reading("KEEP_OLD"))
    clinic, bot = _call(f"mentor-{case}", reader, now=MENTOR_NOW)
    spec = MENTOR_CASES[case]
    action = _run(bot, f"mentor-{case}", spec.lines)
    outcome, reason, writes = spec.expected
    assert reader.calls == []
    assert action.outcome == outcome and action.transfer_reason == reason
    assert _slot_writes(clinic) == writes


# --- Router: câu luật đã có đường đi không gọi model --------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "khung 2",
        "không",
        "dạ",
        "3 giờ chiều",
        "khung khác",
        "thôi giữ lịch cũ",
        "tôi đổi ý",
        "khung nào cũng được",
        "hôm đó tôi bận",
        "không lấy ngày 14, ngày 15 đi",
    ],
)
def test_rule_decided_answers_at_the_offer_do_not_call_the_model(line: str) -> None:
    reader = FakeReader(_reading("AMBIGUOUS"))
    _, bot = _call(f"route-no-{line}", reader)
    _run(bot, f"route-no-{line}", [*FIRST_PAGE, line])
    assert reader.calls == []


@pytest.mark.parametrize(
    ("lines", "line", "route"),
    [
        (FIRST_PAGE, "để tôi tính đã em", "SLOT_UNRESOLVED"),
        (FIRST_PAGE, "lịch này ai đặt cho tôi vậy", "SLOT_UNRESOLVED"),
        (READBACK, "đồng ý nhé mà khoan đã", "SLOT_HEDGED_ANSWER"),
        (READBACK, "không được, cái đó không hợp với tôi đâu em", "SLOT_REFUSAL_WITH_CONTENT"),
    ],
)
def test_answers_without_a_rule_path_call_the_model_once(
    lines: list[str], line: str, route: str
) -> None:
    reader = FakeReader(None)
    _, bot = _call(f"route-yes-{line}", reader)
    _run(bot, f"route-yes-{line}", [*lines, line])
    assert len(reader.calls) == 1
    context = reader.calls[0]
    assert context.route_reason == route and context.transcript == line
    # C3: model chỉ thấy số khung, không thấy giờ khung / lịch hẹn
    assert set(vars(context)) == {
        "transcript",
        "question_id",
        "direction",
        "route_reason",
        "pending_action",
        "page_size",
        "answers_last_question",
    }


def test_a_turn_that_already_used_the_model_does_not_call_the_slot_model() -> None:
    """Một request mỗi lượt (C4): câu lâm sàng đã qua tầng ngữ nghĩa chung thì không gọi tầng này."""

    class Semantic:
        def __init__(self) -> None:
            self.calls = 0

        def analyze(self, context):  # noqa: ANN001, ANN201
            self.calls += 1
            return None

    reader = FakeReader(_reading("AMBIGUOUS"))
    _, bot = _call("budget-once", reader)
    semantic = Semantic()
    bot._extractor._semantic = semantic
    _run(bot, "budget-once", [*FIRST_PAGE, "tôi bị đau dạ dày, để tôi tính đã"])
    assert semantic.calls == 1 and reader.calls == []


# --- Ma trận ưu tiên (§4.9) ----------------------------------------------------------------------

OFFER = SlotSemanticContext("x", QuestionId.OFFER_SLOTS, "outbound", "SLOT_UNRESOLVED", page_size=2)
CHOSEN = SlotSemanticContext(
    "x", QuestionId.SLOT_READBACK, "outbound", "SLOT_HEDGED_ANSWER", page_size=2
)


@pytest.mark.parametrize(
    ("reading", "context", "expected"),
    [
        (_reading("PICK", pick=1), OFFER, SlotAct.PICK),
        (SlotReading("PICK", confident=False, decides_now=True, pick=1), OFFER, SlotAct.UNCLEAR),
        (SlotReading("PICK", confident=True, decides_now=False, pick=1), OFFER, SlotAct.UNCLEAR),
        (SlotReading("ANY", confident=True, decides_now=False), OFFER, SlotAct.UNCLEAR),
        (SlotReading("REFUSE", confident=False, decides_now=False), OFFER, SlotAct.REFUSE),
        (_reading("KEEP_OLD"), OFFER, SlotAct.KEEP_OLD_UNSURE),
        (_reading("CONFIRM"), CHOSEN, SlotAct.CONFIRM),
        (_reading("CONFIRM"), OFFER, SlotAct.UNCLEAR),
        (_reading("QUESTION", intent="OUT_OF_SCOPE"), OFFER, SlotAct.OUT_OF_SCOPE),
        (_reading("AMBIGUOUS", intent="OUT_OF_SCOPE"), OFFER, SlotAct.UNCLEAR),
        (_reading("TIME", intent="CANCEL"), OFFER, SlotAct.CANCEL),
        (SlotReading("CANCEL", confident=True, decides_now=False), OFFER, SlotAct.UNCLEAR),
        (_reading("PICK", pick=1, clinical="ADVICE_REQUEST"), OFFER, SlotAct.UNCLEAR),
        (_reading("QUESTION"), OFFER, SlotAct.UNCLEAR),
    ],
)
def test_priority_matrix(reading: SlotReading, context: SlotSemanticContext, expected) -> None:
    assert resolve_slot_act(reading, context) is expected


@pytest.mark.parametrize(
    ("reading", "context"),
    [
        (_reading("CONFIRM"), OFFER),  # nhãn không được hỏi ở câu này
        (_reading("PICK", pick=3), OFFER),  # vượt số khung
        (_reading("TIME", wanted_span="thứ bảy"), OFFER),  # span không có trong câu
        (
            _reading("AMBIGUOUS", intent="CANCEL"),
            OFFER.__class__("x", QuestionId.OFFER_SLOTS, "inbound", "SLOT_UNRESOLVED", page_size=2),
        ),  # đặt lịch không có hủy
    ],
)
def test_ground_rejects_readings_outside_the_contract(reading, context) -> None:
    assert ground_slot_reading(reading, context) is None


# --- Dialogue theo nhãn model: không bao giờ ghi thẳng ------------------------------------------


@pytest.mark.parametrize(
    ("reading", "slot_id"),
    [(_reading("ANY"), "slot_91d2"), (_reading("PICK", pick=2), "slot_b501")],
)
def test_model_pick_or_any_reads_the_slot_back_without_writing(reading, slot_id) -> None:
    reader = FakeReader(reading)
    clinic, bot = _call(f"dlg-{reading.act}", reader)
    action = _run(bot, f"dlg-{reading.act}", [*FIRST_PAGE, "chọn giúp tôi một cái nào đấy em"])
    ctx = _context(bot, f"dlg-{reading.act}")
    assert ctx.question.question_id is QuestionId.SLOT_READBACK
    assert ctx.selected_slot_id == slot_id and "đồng ý" in action.utterance
    assert _slot_writes(clinic) == []


def test_model_time_on_the_page_reads_that_slot_back() -> None:
    line = "cái hôm thứ năm ấy em"
    reader = FakeReader(_reading("TIME", wanted_span="hôm thứ năm"))
    clinic, bot = _call("dlg-time", reader)
    _run(bot, "dlg-time", [*FIRST_PAGE, line])
    ctx = _context(bot, "dlg-time")
    assert ctx.selected_slot_id == "slot_b501" and _slot_writes(clinic) == []


def test_model_unclear_at_the_offer_asks_which_slot() -> None:
    reader = FakeReader(SlotReading("AMBIGUOUS", confident=True, decides_now=False))
    clinic, bot = _call("dlg-unclear", reader)
    action = _run(bot, "dlg-unclear", [*FIRST_PAGE, "để tôi tính đã em"])
    ctx = _context(bot, "dlg-unclear")
    assert action.utterance.startswith(t.SLOT_AMBIGUOUS_AGAIN + "anh chị chọn")
    assert ctx.question.question_id is QuestionId.OFFER_SLOTS and ctx.unclear_streak == 1
    assert ctx.failed_understandings == 0 and _slot_writes(clinic) == []


def test_model_confirm_at_the_read_back_only_asks_to_say_agree() -> None:
    reader = FakeReader(_reading("CONFIRM"))
    clinic, bot = _call("dlg-confirm", reader)
    action = _run(bot, "dlg-confirm", [*READBACK, "đồng ý nhé mà khoan đã"])
    assert "“đồng ý”" in action.utterance and _slot_writes(clinic) == []


def test_rule_cancel_after_a_refusal_goes_to_the_cancel_question() -> None:
    """Luật: "không, … xóa lịch giúp tôi" là lệnh hủy — hỏi xác nhận hủy, không hỏi A/B (held-out S022)."""
    reader = FakeReader(_reading("AMBIGUOUS"))
    clinic, bot = _call("rule-cancel", reader)
    _run(bot, "rule-cancel", [*READBACK, "không, tôi không khám nữa đâu xóa lịch giúp tôi"])
    ctx = _context(bot, "rule-cancel")
    assert ctx.pending_action == "CANCEL" and reader.calls == [] and clinic.writes == []


def test_model_cancel_goes_to_the_cancel_question() -> None:
    reader = FakeReader(_reading("CANCEL", intent="CANCEL"))
    clinic, bot = _call("dlg-cancel", reader)
    _run(bot, "dlg-cancel", [*READBACK, "không được, cái đó không hợp với tôi đâu em"])
    ctx = _context(bot, "dlg-cancel")
    assert (
        ctx.pending_action == "CANCEL" and ctx.question.question_id is QuestionId.CANCEL_RECONFIRM
    )
    assert clinic.writes == []


def test_model_out_of_scope_transfers() -> None:
    reader = FakeReader(_reading("OUT_OF_SCOPE", intent="OUT_OF_SCOPE"))
    _, bot = _call("dlg-oos", reader)
    action = _run(bot, "dlg-oos", [*FIRST_PAGE, "lịch này ai đặt cho tôi vậy"])
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "OUT_OF_SCOPE")


def test_model_keep_old_asks_hear_more_or_keep() -> None:
    reader = FakeReader(_reading("KEEP_OLD"))
    clinic, bot = _call("dlg-keep", reader)
    action = _run(bot, "dlg-keep", [*FIRST_PAGE, "em cứ để như hiện giờ cho tôi"])
    assert action.utterance == t.SLOT_REFUSE_CHOICE["RESCHEDULE"] and not action.ended
    assert clinic.writes == []


def test_model_clinical_advice_transfers() -> None:
    line = "trước buổi đó tôi có phải kiêng gì không"
    reader = FakeReader(
        _reading("QUESTION", clinical="ADVICE_REQUEST", clinical_span="có phải kiêng gì không")
    )
    _, bot = _call("dlg-clinical", reader)
    action = _run(bot, "dlg-clinical", [*FIRST_PAGE, line])
    assert (action.outcome, action.transfer_reason) == ("TRANSFERRED", "CLINICAL_QUESTION")


# --- §4.7: model lỗi / bị loại -> câu của luật, không SLOT_CONFLICT, không ghi ---------------------


@pytest.mark.parametrize(
    "reader",
    [FakeReader(raises=True), FakeReader(None), FakeReader(_reading("PICK", pick=9))],
    ids=["error", "none", "rejected"],
)
def test_model_failure_keeps_the_rule_answer(reader: FakeReader) -> None:
    clinic, bot = _call(f"fail-{id(reader)}", reader)
    action = _run(bot, f"fail-{id(reader)}", [*FIRST_PAGE, "để tôi tính đã em"])
    ctx = _context(bot, f"fail-{id(reader)}")
    assert action.utterance in t.static_choices(t.NOT_UNDERSTOOD)
    assert action.utterance != t.SLOT_CONFLICT and not action.ended
    assert ctx.failed_understandings == 1  # đúng như chỉ-luật, không cộng thêm vì model lỗi
    assert clinic.writes == []


def test_model_failure_at_the_read_back_reasks_the_same_slot() -> None:
    reader = FakeReader(raises=True)
    clinic, bot = _call("fail-rb", reader)
    action = _run(bot, "fail-rb", [*READBACK, "đồng ý nhé mà khoan đã"])
    ctx = _context(bot, "fail-rb")
    assert ctx.question.question_id is QuestionId.SLOT_READBACK
    assert action.utterance != t.SLOT_CONFLICT and clinic.writes == []


# --- Chọn provider (§4.11) -----------------------------------------------------------------------


@dataclass
class FakeProvider:
    status: str = "accepted"
    reading: Optional[SlotReading] = None
    delay: float = 0.0
    calls: int = 0
    last_status: Optional[str] = None

    class _G:
        model = "fake-model"
        provider_name = "fake"

    _gateway = _G()

    def analyze(self, context):  # noqa: ANN001, ANN201
        self.calls += 1
        self.last_status = self.status
        return self.reading


def _ctx(transcript: str) -> SlotSemanticContext:
    return SlotSemanticContext(
        transcript, QuestionId.OFFER_SLOTS, "outbound", "SLOT_UNRESOLVED", page_size=2
    )


def test_unaccented_answers_go_to_luna_only() -> None:
    jev, luna = FakeProvider(), FakeProvider(reading=_reading("ANY"))
    reader = SlotSemanticReader(jev, luna)
    assert reader.analyze(_ctx("de toi tinh da em")) == _reading("ANY")
    assert (jev.calls, luna.calls, reader.last_reason) == (0, 1, "unaccented")


def test_jev_answer_is_final_even_when_ambiguous_or_rejected() -> None:
    for status in ("accepted", "rejected"):
        jev, luna = FakeProvider(status=status), FakeProvider()
        SlotSemanticReader(jev, luna).analyze(_ctx("để tôi tính đã em"))
        assert (jev.calls, luna.calls) == (1, 0)


@pytest.mark.parametrize("status", ["timeout", "http_error", "network_error", "invalid_response"])
def test_jev_service_failure_falls_back_to_luna_once(status: str) -> None:
    jev, luna = FakeProvider(status=status), FakeProvider(reading=_reading("MORE"))
    reader = SlotSemanticReader(jev, luna)
    assert reader.analyze(_ctx("để tôi tính đã em")) == _reading("MORE")
    assert (jev.calls, luna.calls, reader.last_reason) == (1, 1, "failover")


def test_no_fallback_when_the_turn_has_too_little_time_left() -> None:
    ticks = iter([0.0, 3.0])
    jev, luna = FakeProvider(status="timeout"), FakeProvider()
    reader = SlotSemanticReader(jev, luna, budget_s=4.0, clock=lambda: next(ticks))
    assert reader.analyze(_ctx("để tôi tính đã em")) is None and luna.calls == 0


def _named(model: str, provider: str, **kwargs: Any) -> FakeProvider:
    fake = FakeProvider(**kwargs)
    fake._gateway = type("G", (), {"model": model, "provider_name": provider})()
    return fake


@pytest.mark.parametrize(
    ("transcript", "jev_status", "trace"),
    [
        ("để tôi tính đã em", "accepted", ("jev-m", "typesafe", None)),
        ("de toi tinh da em", "accepted", ("luna-m", "openai", None)),
        ("để tôi tính đã em", "timeout", ("luna-m", "openai", "typesafe")),
    ],
)
def test_the_turn_trace_names_the_provider_that_answered(
    transcript: str, jev_status: str, trace: tuple
) -> None:
    """Panel LiveKit / trace đọc model, provider và provider chính đã lỗi từ ngân sách lượt."""
    jev = _named("jev-m", "typesafe", status=jev_status)
    luna = _named("luna-m", "openai", reading=_reading("ANY"))
    reader = SlotSemanticReader(jev, luna)
    with model_turn() as budget:
        invoke_model(reader, lambda: reader.analyze(_ctx(transcript)))
    assert (budget.model, budget.provider, budget.backup_for) == trace


def test_route_budget_overrides_the_default_turn_budget() -> None:
    with model_turn() as budget:
        assert invoke_model(object(), lambda: "ok", timeout_s=0.5) == "ok"
    assert budget.status == "OK"
    with model_turn() as budget:
        assert invoke_model(object(), lambda: time.sleep(0.4) or "late", timeout_s=0.1) is None
    assert budget.status == "TIMEOUT"


# --- Adapter Jev ---------------------------------------------------------------------------------


class FakeTypeSafe:
    provider_name = "typesafe"
    model = "jev-test"

    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.sent: list[tuple[dict, dict]] = []

    def evaluate(self, state, questions):  # noqa: ANN001, ANN201
        self.sent.append((state, questions))
        return SystemOneReply("completed", answers=self.answers)


def _choice(choice: str, probability: float = 0.9) -> ChoiceAnswer:
    return ChoiceAnswer(
        type="choice", choice=choice, confidence=probability, probabilities={choice: probability}
    )


def _jev_answers(act: str, probability: float = 0.9, **extra: Any) -> dict[str, Any]:
    return {
        "slot_act": _choice(act, probability),
        "intent": _choice("NONE"),
        "clinical": _choice("NONE"),
        **extra,
    }


def test_jev_reads_a_pick_by_order() -> None:
    client = FakeTypeSafe(_jev_answers("PICK", pick=_choice("2")))
    adapter = JevSlotSemanticExtractor(client, min_confidence=0.6)
    reading = adapter.analyze(_ctx("cái em nói sau ấy"))
    assert reading is not None and (reading.act, reading.pick, reading.confident) == (
        "PICK",
        2,
        True,
    )
    state, questions = client.sent[0]
    assert {"slot_act", "pick", "intent", "clinical"} <= set(questions)
    assert "decides_now" not in questions  # Noul không phân biệt được (held-out 12-10), đã bỏ
    assert "CONFIRM" not in questions["slot_act"].criteria  # chỉ hỏi nhãn của câu đang chờ
    assert (
        state["slots_just_read"] == 2
        and "slots" not in state
        and "starts_at" not in json.dumps(state)
    )


def test_jev_low_probability_is_not_confident() -> None:
    client = FakeTypeSafe(_jev_answers("ANY", probability=0.4))
    reading = JevSlotSemanticExtractor(client, min_confidence=0.6).analyze(
        _ctx("giờ nào tiện thì xếp")
    )
    assert reading is not None and not reading.confident
    assert resolve_slot_act(reading, _ctx("giờ nào tiện thì xếp")) is SlotAct.UNCLEAR


def test_jev_time_span_is_one_of_the_cut_candidates() -> None:
    context = _ctx("thôi để sang tuần sau, thứ ba buổi sáng")
    questions = build_slot_questions(context, ["thứ ba buổi sáng", context.transcript])
    assert set(questions["wanted_time_span"].criteria) == {"c0", "c1"}
    client = FakeTypeSafe(_jev_answers("TIME", wanted_time_span=_choice("c0")))
    reading = JevSlotSemanticExtractor(client, min_confidence=0.6).analyze(context)
    assert reading is not None and reading.wanted_span is not None
    assert reading.wanted_span in context.transcript


def test_jev_state_marks_unaccented_transcripts() -> None:
    state = build_slot_state(_ctx("de toi tinh da em"))
    assert "transcript_note" in state and "transcript_glossary" in state


# --- Adapter Luna --------------------------------------------------------------------------------


@dataclass
class FakeGateway:
    content: Optional[str]
    status: str = "completed"
    provider_name: str = "openai"
    model: str = "gpt-6-luna"
    messages: list = field(default_factory=list)

    def generate_structured(self, messages, **_: Any):  # noqa: ANN001, ANN201
        self.messages.append(messages)

        class Reply:
            pass

        reply = Reply()
        reply.status, reply.content = self.status, self.content
        reply.prompt_tokens = reply.completion_tokens = None
        reply.actual_model = reply.provider_request_id = reply.http_status = None
        reply.model_call_latency_ms = None
        return reply


def _luna_json(**overrides: Any) -> str:
    payload = {
        "act": "AMBIGUOUS",
        "pick": None,
        "wanted_time_span": None,
        "decides_now": False,
        "intent": None,
        "clinical": None,
        "clinical_span": None,
        **overrides,
    }
    return json.dumps(payload, ensure_ascii=False)


def test_luna_reads_the_same_labels() -> None:
    gateway = FakeGateway(_luna_json(act="PICK", pick=1, decides_now=True))
    adapter = LunaSlotSemanticExtractor(gateway, max_completion_tokens=200)
    reading = adapter.analyze(_ctx("lay cai som hon"))
    assert reading is not None and (reading.act, reading.pick) == ("PICK", 1)
    system, user = gateway.messages[0]
    assert system["role"] == "system" and json.loads(user["content"])["slots_just_read"] == 2


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        _luna_json(act="CONFIRM"),  # không được hỏi ở câu mời khung
        _luna_json(act="TIME", wanted_time_span="thứ bảy"),  # span bịa
        _luna_json(slot_id="slot_91d2"),  # khóa lạ
    ],
)
def test_luna_invalid_or_ungrounded_answers_are_dropped(content: str) -> None:
    adapter = LunaSlotSemanticExtractor(FakeGateway(content), max_completion_tokens=200)
    assert adapter.analyze(_ctx("để tôi tính đã em")) is None
    assert adapter.last_status in ("invalid_response", "rejected")


def test_luna_prompt_has_no_slot_or_appointment_data() -> None:
    messages = build_slot_messages(_ctx("để tôi tính đã em"))
    text = json.dumps(messages, ensure_ascii=False)
    assert "slot_" not in text and "starts_at" not in text and "apt_" not in text


# --- Ví dụ criteria / prompt không trùng câu eval hay held-out ----------------------------------


def _eval_sentences() -> set[str]:
    sentences: set[str] = set()
    for path in [
        *ROOT.glob("eval/*/cases*.csv"),
        ROOT / "eval/reschedule/heldout_slot_semantic.csv",
    ]:
        with path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                text = row.get("transcript") or ""
                if text:
                    sentences.add(strip_diacritics(clean(text)))
    return sentences


def test_examples_do_not_leak_eval_sentences() -> None:
    examples = [text for _, text, _ in EXAMPLES]
    for criterion in ACT_CRITERIA.values():
        if isinstance(criterion, dict):
            examples += criterion.get("examples", [])
    leaked = [e for e in examples if strip_diacritics(clean(e)) in _eval_sentences()]
    assert leaked == []
