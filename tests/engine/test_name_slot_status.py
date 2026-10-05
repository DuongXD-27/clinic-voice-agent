"""Bước hỏi tên khi luật thiếu dấu hiệu họ tên (UNANCHORED): kết cục slot filling quyết định.

Đi qua `NameSlotFiller` thật với gateway giả trả từng `StructuredReply`, không mock exception ở
extractor. Model lỗi hoặc trả dữ liệu không hợp lệ phải hỏi lại, không khôi phục tên của luật.
Tên đã nghe được đối chiếu ngay: câu rác mà mô hình coi là tên thì chuyển máy khi không khớp.
"""

import json
from typing import Optional
from unittest.mock import patch

import pytest

from callbot.engine import BotAction, CallerInput, CallStart, EngineSettings, create_orchestrator
from callbot.engine.dialogue import templates as t
from callbot.engine.extraction import (
    InformationExtractor,
    Provenance,
    QuestionId,
    SlotFillingStatus,
)
from callbot.engine.extraction.name_slot_filling import NameSlotFiller
from callbot.engine.verification.names import normalize_text, strip_diacritics
from clinic_mock_sim import FakeClinicAPI
from inference.llm.providers.base import StructuredReply
from tests.engine.extraction.test_extractor import ctx

DOB = "14/03/1978"


def named(name: Optional[str], span: Optional[str] = None) -> StructuredReply:
    content = json.dumps({"full_name": name, "span": span if span is not None else name})
    return StructuredReply("completed", content, prompt_tokens=1, completion_tokens=1)


class FakeGateway:
    provider_name, model = "fake", "fake-model"

    def __init__(self, reply: StructuredReply) -> None:
        self.reply = reply
        self.calls = 0

    def generate_structured(self, *args, **kwargs) -> StructuredReply:
        self.calls += 1
        return self.reply


REPLIES = {
    "accepted": named("Lê Na"),
    "no_name": named(None),
    "rejected": named("Lê Na", "Nguyễn Văn B"),  # span không khớp tên
    "timeout": StructuredReply("timeout"),
    "refusal": StructuredReply("refusal"),
    "invalid_response": StructuredReply("invalid_response"),
}
STATUS = {
    "accepted": SlotFillingStatus.ACCEPTED,
    "no_name": SlotFillingStatus.NO_NAME,
    "rejected": SlotFillingStatus.REJECTED,
    "timeout": SlotFillingStatus.UNAVAILABLE,
    "refusal": SlotFillingStatus.UNAVAILABLE,
    "invalid_response": SlotFillingStatus.UNAVAILABLE,
}


def extract_name(transcript: str, reply: StructuredReply):
    gateway = FakeGateway(reply)
    extractor = InformationExtractor(fallback=NameSlotFiller(gateway), name_fallback=True)
    return extractor.extract(ctx(QuestionId.ASK_NAME), transcript).full_name, gateway


@pytest.mark.parametrize("outcome", list(REPLIES))
def test_slot_filler_reports_each_outcome(outcome):
    result = NameSlotFiller(FakeGateway(REPLIES[outcome])).full_name("dạ Lê Na ạ")
    assert result.status is STATUS[outcome]
    assert result.field.found is (outcome == "accepted")
    assert result.elapsed_ms is not None and result.elapsed_ms >= 0


# Bảng §4.1, hàng UNANCHORED: model accepted -> tên model; no_name -> không phải tên;
# rejected / unavailable -> không có tên chắc chắn, phải hỏi lại.
@pytest.mark.parametrize("transcript", ["dạ Lê Na ạ", "dạ tôi tên Lê Na ạ", "Lê Na"])
@pytest.mark.parametrize(
    "outcome, expected, provenance",
    [
        ("accepted", "lê na", Provenance.FALLBACK),
        ("no_name", None, Provenance.NONE),
        ("rejected", None, Provenance.NONE),
        ("timeout", None, Provenance.NONE),
        ("refusal", None, Provenance.NONE),
        ("invalid_response", None, Provenance.NONE),
    ],
)
def test_unanchored_name_by_slot_filling_outcome(transcript, outcome, expected, provenance):
    name, gateway = extract_name(transcript, REPLIES[outcome])
    assert gateway.calls == 1
    assert name.value == expected
    assert name.provenance is provenance


# Bảng §4.1, hàng NO_SIGNAL / UNRESOLVED_BOUNDARY: không có tên của luật để giữ lại
@pytest.mark.parametrize("transcript", ["à ừ thì là Lê Na nhé em", "Nguyễn Văn A đúng rồi"])
@pytest.mark.parametrize("outcome", ["no_name", "rejected", "timeout", "refusal"])
def test_without_a_rule_name_only_the_model_can_name(transcript, outcome):
    name, gateway = extract_name(transcript, REPLIES[outcome])
    assert gateway.calls == 1
    assert not name.found


def test_anchored_name_never_asks_the_model():
    name, gateway = extract_name("Nguyễn Văn An", REPLIES["no_name"])
    assert name.value == "nguyễn văn an" and gateway.calls == 0


# --- Qua orchestrator -----------------------------------------------------------------------


def _bot(monkeypatch, reply: Optional[StructuredReply]):
    if reply is None:
        settings = EngineSettings(name_fallback_provider="none", _env_file=None)
        return create_orchestrator(FakeClinicAPI(), settings=settings), None
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-secret")
    gateway = FakeGateway(reply)
    settings = EngineSettings(name_fallback_provider="openai", _env_file=None)
    with patch("callbot.engine.create_gateway", return_value=gateway):
        return create_orchestrator(FakeClinicAPI(), settings=settings), gateway


def _start(direction: str, call_id: str) -> CallStart:
    if direction == "outbound":
        return CallStart(call_id=call_id, direction="outbound", appointment_id="apt_00417")
    return CallStart(call_id=call_id, direction="inbound", caller_number="0912345600")


def _said(action: BotAction) -> str:
    return strip_diacritics(normalize_text(action.utterance))


def test_garbage_the_model_rejects_is_a_failed_understanding(monkeypatch):
    bot, gateway = _bot(monkeypatch, REPLIES["no_name"])
    bot.start_call(_start("inbound", "garbage-no-name"))
    action = bot.handle_turn("garbage-no-name", CallerInput(turn=1, text="trời hôm nay đẹp quá"))
    assert action.utterance == t.ASK_NAME_AGAIN
    context = bot.sessions.store.get_session("garbage-no-name").context
    assert context["claimed_name"] is None
    assert context["failed_understandings"] == 1
    assert gateway.calls == 1


@pytest.mark.parametrize(
    "direction, reason", [("outbound", "IDENTITY_FAILED"), ("inbound", "PATIENT_NOT_FOUND")]
)
def test_garbage_the_model_names_is_matched_and_transferred(monkeypatch, direction, reason):
    bot, _ = _bot(monkeypatch, named("Trần Thế Gian"))
    call_id = f"garbage-{direction}"
    actions = [bot.start_call(_start(direction, call_id))]
    actions.append(bot.handle_turn(call_id, CallerInput(turn=1, text="Trần Thế Gian")))
    context = bot.sessions.store.get_session(call_id).context
    assert context == {}  # Ended sessions discard identifying data.

    final = actions[-1]
    assert (final.state, final.outcome, final.transfer_reason) == ("ENDED", "TRANSFERRED", reason)
    # §1.1.2: không câu nào trước xác minh đọc lại tên đã nghe
    assert all("tran the gian" not in _said(action) for action in actions)


@pytest.mark.parametrize(
    "transcript",
    ["dạ Lê Na ạ", "Lê Na", "trần thế gian"],
)
def test_without_a_model_an_unmatched_rule_name_transfers_immediately(monkeypatch, transcript):
    bot, _ = _bot(monkeypatch, None)
    bot.start_call(_start("inbound", "rules-only"))
    action = bot.handle_turn("rules-only", CallerInput(turn=1, text=transcript))
    assert action.outcome == "TRANSFERRED"
    assert action.transfer_reason == "PATIENT_NOT_FOUND"
    assert bot.sessions.store.get_session("rules-only").context == {}
