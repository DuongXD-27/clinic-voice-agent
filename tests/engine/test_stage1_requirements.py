"""Acceptance tests for R-19/22/23/31/40/41, using the real core and no external services."""

import json
from dataclasses import replace
from datetime import datetime
from threading import Event
from time import monotonic

import pytest

from callbot.engine import CallerInput, CallStart, create_orchestrator
from callbot.engine.dialogue import templates as t
from callbot.engine.extraction import InformationExtractor, model_budget
from callbot.engine.extraction.agreement import confirmation_veto, extract_agreement
from callbot.engine.extraction.fallback import SlotFillingResult, SlotFillingStatus
from callbot.engine.extraction.full_name import introduces_oneself
from callbot.engine.extraction.identity import corrects_itself
from callbot.engine.extraction.schema import (
    VN_TZ,
    Agreement,
    Field,
    IdentityStatus,
    Provenance,
    QuestionId,
    TurnContext,
)
from callbot.engine.policy import output_guard
from callbot.engine.policy.guardrails import SevereFailureBlocked
from callbot.engine.policy.sources import SourceRegistry
from callbot.engine.policy.utterances import RENDERERS, bind_ledger, renderer
from callbot.engine.session.context import CallContext
from callbot.engine.types import BotAction
from callbot.engine.verification.identity import IdentityVerifier, MatchDetail
from callbot.engine.verification.names import NameMatch, compare_names
from clinic_mock_sim import FakeClinicAPI
from tests.engine.test_confirm_dialogue import _at_readback, _context
from tests.engine.test_output_guard_flow import _MemorySink, _tracer
from tests.engine.test_reschedule_dialogue import _at_read_back, _say

NOW = datetime(2026, 10, 2, tzinfo=VN_TZ)


def context(question=QuestionId.CANCEL_RECONFIRM):
    return TurnContext(
        turn=4,
        question_id=question,
        direction="outbound",
        now=NOW,
        pending_action="CANCEL",
        question_turn=3,
    )


@pytest.mark.parametrize(
    "left,right,expected",
    [
        ("NGUYỄN  Văn A", "Nguyễn Văn A", NameMatch.MATCH),
        ("Hoà Văn A", "Hòa Văn A", NameMatch.MATCH),
        ("Nguyển Văn A", "Nguyễn Văn A", NameMatch.SUSPICIOUS),
        ("Hà Văn A", "Hạ Văn A", NameMatch.SUSPICIOUS),
        ("Nguyễn Văn Sơn", "Nguyễn Văn Son", NameMatch.MISMATCH),
        ("Nguyễn Văn A", "Nguyễn Van A", NameMatch.MISMATCH),
        ("Đặng Văn A", "Dang Van A", NameMatch.MISMATCH),
        ("Văn A", "Nguyễn Văn A", NameMatch.MISMATCH),
        # Tên khai không có dấu nào (QC qc-stt-05, qc-w6-01): so trên bản bỏ hết dấu. Đánh đổi: các
        # tên chỉ khác dấu ("Lê Văn Hạ" / "Lê Văn Hà") không còn phân biệt được bằng tên, chỉ bằng
        # ngày sinh và quy tắc đúng một hồ sơ khớp.
        ("nguyen van a", "Nguyễn Văn A", NameMatch.MATCH),
        ("NGUYEN Van A", "Nguyễn Văn A", NameMatch.MATCH),
        ("Dang Van A", "Đặng Văn A", NameMatch.MATCH),
        ("le van ha", "Lê Văn Hạ", NameMatch.MATCH),
        ("nguyen van b", "Nguyễn Văn A", NameMatch.MISMATCH),
        ("van a", "Nguyễn Văn A", NameMatch.MISMATCH),
    ],
)
def test_name_matching_preserves_syllables_and_never_accepts_tone_differences(
    left, right, expected
):
    assert compare_names(left, right) is expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Tôi là Nguyễn Văn A", IdentityStatus.PRESENT),
        ("", IdentityStatus.ABSENT),
        ("Nguyễn Văn A hay Trần Văn B", IdentityStatus.MULTIPLE),
        ("hình như Nguyễn Văn A", IdentityStatus.UNCERTAIN),
    ],
)
def test_identity_extraction_has_four_states_with_verbatim_evidence(text, expected):
    result = InformationExtractor().extract(context(QuestionId.ASK_NAME), text)
    assert result.name_identity.status is expected
    if expected is IdentityStatus.PRESENT:
        assert result.name_identity.span in text
    else:
        assert result.name_identity.value is None and result.name_identity.span is None


def test_high_confidence_does_not_rescue_uncertain_identity():
    result = InformationExtractor().extract(
        replace(context(QuestionId.ASK_NAME), asr_confidence=1.0), "hình như Nguyễn Văn A"
    )
    assert result.name_identity.status is IdentityStatus.UNCERTAIN


@pytest.mark.parametrize(
    "text", ["14 hoặc 15/3/1978", "14/3/1978 hoặc 15/3/1978", "14/3/1978, 15/3/1978"]
)
def test_multiple_dob_values_are_never_compared(text):
    result = InformationExtractor().extract(context(QuestionId.ASK_DOB), text)
    assert result.dob_identity.status is IdentityStatus.MULTIPLE
    assert result.dob_identity.value is None


def test_low_confidence_is_an_additional_identity_signal():
    result = InformationExtractor().extract(
        replace(context(QuestionId.ASK_NAME), asr_confidence=0.2), "Nguyễn Văn A"
    )
    assert result.name_identity.status is IdentityStatus.UNCERTAIN


@pytest.mark.parametrize(
    "second,reason",
    [
        ("Nguyển Văn A", "IDENTITY_FAILED"),
        ("hình như Nguyễn Văn A", "NOT_UNDERSTOOD"),
        ("Nguyễn Văn B", "IDENTITY_FAILED"),
    ],
)
def test_name_retry_is_open_persisted_and_limited(second, reason):
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(CallStart("retry", "outbound", appointment_id="apt_00417"))
    first = bot.handle_turn("retry", CallerInput(1, text="hình như Nguyễn Văn A"))
    assert first.state == "AWAITING_IDENTITY"
    assert "nguy" not in first.utterance.lower()
    stored = _context(bot, "retry")
    assert stored.identity_retries == {"ASK_NAME": 1}
    assert stored.failed_understandings == 1
    second_action = bot.handle_turn("retry", CallerInput(2, text=second))
    if reason == "IDENTITY_FAILED":
        # Tên nghe rõ (lệch dấu hay sai hẳn): hỏi ngày sinh rồi mới đối chiếu (§1.1.2)
        assert not second_action.ended and second_action.state == "AWAITING_IDENTITY"
        second_action = bot.handle_turn("retry", CallerInput(3, text="14/03/1978"))
        assert second_action.utterance == t.IDENTITY_FAILED_TRANSFER
    assert second_action.ended and second_action.transfer_reason == reason
    assert all(write[1] == "TRANSFERRED" for write in clinic.writes)


def test_dob_before_name_counts_as_understood_and_keeps_the_name_retry():
    bot = create_orchestrator(FakeClinicAPI())
    bot.start_call(CallStart("dob_first", "outbound", appointment_id="apt_00417"))
    first = bot.handle_turn("dob_first", CallerInput(1, text="sinh ngày 14/3/1978"))
    assert first.utterance == t.ASK_NAME_AFTER_DOB
    stored = _context(bot, "dob_first")
    assert stored.identity_retries == {} and stored.failed_understandings == 0
    unclear = bot.handle_turn("dob_first", CallerInput(2, text="hình như Nguyễn Văn A"))
    assert not unclear.ended and unclear.utterance == t.ASK_NAME_AGAIN
    assert _context(bot, "dob_first").identity_retries == {"ASK_NAME": 1}
    verified = bot.handle_turn("dob_first", CallerInput(3, text="Nguyễn Văn A"))
    assert verified.state == "AWAITING_INTENT"


@pytest.mark.parametrize(
    "text,correction,introduction",
    [
        ("à nhầm, 14/3/1978", True, False),
        ("sửa lại là 14/3/1978", True, False),
        ("tôi là Nguyễn Văn A", False, True),
        ("toi la Nguyen Van A", False, True),  # ASR mất dấu
        ("nhắm mắt cũng nhớ, 14/3/1978", False, False),
        ("tối là tôi rảnh", False, False),
        ("Nhâm Văn A", False, False),
        ("a khong, 14/3/1978", False, False),  # "à" không có dạng không dấu: "A" là tên thật
    ],
)
def test_self_correction_cues_compare_with_diacritics(text, correction, introduction):
    assert corrects_itself(text) is correction
    assert introduces_oneself(text) is introduction


def test_trace_reason_prefers_the_closest_inbound_record():
    """Nhiều hồ sơ cùng số: lý do đại diện là hồ sơ gần khớp nhất, lệch dấu gần hơn sai hẳn tên."""
    details = [(MatchDetail.BOTH_MISMATCH, {}), (MatchDetail.NAME_SUSPICIOUS, {})]
    assert IdentityVerifier._representative(details) is MatchDetail.NAME_SUSPICIOUS
    details.append((MatchDetail.DOB_MISMATCH, {}))
    assert IdentityVerifier._representative(details) is MatchDetail.DOB_MISMATCH


def test_tone_mismatch_is_not_compared_before_dob_and_never_authenticates(monkeypatch):
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(CallStart("tone", "outbound", appointment_id="apt_00417"))
    results: list = []
    apply = bot._apply

    def spy(ctx: CallContext, action: BotAction) -> None:
        results.append(ctx.identity_result)
        apply(ctx, action)

    monkeypatch.setattr(bot, "_apply", spy)
    # Lệch dấu thanh không được hỏi lại ngay: hỏi lại sẽ cho biết tên gần đúng (§1.1.2)
    asked = bot.handle_turn("tone", CallerInput(1, text="Nguyển Văn A"))
    assert not asked.ended and "nguy" not in asked.utterance.lower()
    assert asked.utterance in t.static_choices(t.ASK_DOB)
    assert _context(bot, "tone").identity_retries == {}
    # R-22: ngày sinh đúng cũng không xác thực tên lệch dấu
    action = bot.handle_turn("tone", CallerInput(2, text="14/3/1978"))
    assert action.transfer_reason == "IDENTITY_FAILED"
    assert action.utterance == t.IDENTITY_FAILED_TRANSFER
    assert results == [None, "NAME_SUSPICIOUS"]
    assert all(write[1] == "TRANSFERRED" for write in clinic.writes)


def test_wrong_name_waits_for_dob_before_transferring_with_a_reason(monkeypatch):
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(CallStart("wrong", "outbound", appointment_id="apt_00417"))
    results: list = []
    apply = bot._apply

    def spy(ctx: CallContext, action: BotAction) -> None:
        # Phiên kết thúc bị purge sau commit: đọc lý do trên ctx ngay trước `_apply`
        results.append(ctx.identity_result)
        apply(ctx, action)

    monkeypatch.setattr(bot, "_apply", spy)
    asked = bot.handle_turn("wrong", CallerInput(1, text="Nguyễn Văn B"))
    assert not asked.ended and asked.state == "AWAITING_IDENTITY"
    assert _context(bot, "wrong").identity_retries == {}
    assert clinic.writes == []
    action = bot.handle_turn("wrong", CallerInput(2, text="14/03/1978"))
    assert action.transfer_reason == "IDENTITY_FAILED"
    assert action.utterance == t.IDENTITY_FAILED_TRANSFER
    assert "14 tháng 10" not in action.utterance
    assert results == [None, "NAME_MISMATCH"]


@pytest.mark.parametrize(
    "question", [QuestionId.CONFIRM_READBACK, QuestionId.CANCEL_RECONFIRM, QuestionId.SLOT_READBACK]
)
def test_bare_da_never_agrees(question):
    assert extract_agreement("dạ", question).value is Agreement.UNCLEAR


@pytest.mark.parametrize(
    "text", ["vâng, không", "đồng ý, chưa", "đồng ý, đừng", "đồng ý, à không", "vâng, tôi đổi ý"]
)
def test_conflicting_confirmation_reasks_without_business_writes(text):
    bot, clinic, _ = _at_readback("conflict")
    action = bot.handle_turn("conflict", CallerInput(3, text=text))
    assert not action.ended and "không ạ?" in action.utterance
    assert clinic.writes == []


class FailedSemantic:
    def __init__(self, raises=False):
        self.calls = 0
        self.raises = raises

    def analyze(self, ctx):
        self.calls += 1
        if self.raises:
            raise RuntimeError("provider failed")
        return None


@pytest.mark.parametrize("raises,status", [(False, "INVALID"), (True, "ERROR")])
def test_model_failure_cannot_fall_back_to_rule_cancel_confirmation(raises, status):
    model = FailedSemantic(raises)
    extraction = InformationExtractor(semantic=model).extract(
        context(), "tôi đồng ý hủy lịch, cảm ơn em"
    )
    assert model.calls == 1 and extraction.model_status == status
    assert extraction.agreement.value is not Agreement.AGREE
    bot, clinic, _ = _at_readback("model_error")
    bot.handle_turn("model_error", CallerInput(3, text="tôi muốn hủy lịch"))
    bot._extractor = InformationExtractor(semantic=model)
    action = bot.handle_turn("model_error", CallerInput(4, text="tôi đồng ý hủy lịch, cảm ơn em"))
    assert not action.ended and action.utterance == t.CANCEL_CONFLICT
    assert clinic.writes == []
    assert _context(bot, "model_error").failed_understandings == 1
    assert _context(bot, "model_error").business_write_blocked
    assert bot.handle_turn("model_error", CallerInput(5, text="hủy lịch")).outcome == "CANCELLED"


@pytest.mark.parametrize("answer", ["không, hủy đi", "không. Hủy lịch", "đồng ý, đừng hủy"])
def test_conflicting_cancel_keeps_pending_action_and_asks_yes_no(answer):
    bot, clinic, _ = _at_readback("cancel_conflict")
    bot.handle_turn("cancel_conflict", CallerInput(3, text="tôi muốn hủy lịch"))
    action = bot.handle_turn("cancel_conflict", CallerInput(4, text=answer))
    assert action.utterance == t.CANCEL_CONFLICT and clinic.writes == []
    assert _context(bot, "cancel_conflict").pending_action == "CANCEL"


def test_model_deadline_discards_late_agreement(monkeypatch):
    release = Event()
    completed = Event()
    monkeypatch.setattr(model_budget, "MODEL_TIMEOUT_S", 0.03)

    class SlowModel:
        def analyze(self, ctx):
            release.wait(0.5)
            completed.set()
            return object()

    started = monotonic()
    result = InformationExtractor(semantic=SlowModel()).extract(
        context(), "tôi đồng ý hủy lịch, cảm ơn em"
    )
    assert monotonic() - started < 0.2
    assert result.model_status == "TIMEOUT" and result.agreement.value is not Agreement.AGREE
    release.set()
    assert completed.wait(0.5)
    assert result.model_status == "TIMEOUT"


def test_name_and_semantic_share_one_model_operation():
    class NameModel:
        calls = 0

        def full_name(self, *args, **kwargs):
            self.calls += 1
            return SlotFillingResult(
                SlotFillingStatus.ACCEPTED,
                Field("nguyễn văn a", Provenance.FALLBACK, "nguyễn văn a"),
            )

    names, semantic = NameModel(), FailedSemantic()
    result = InformationExtractor(fallback=names, name_fallback=True, semantic=semantic).extract(
        context(QuestionId.ASK_NAME), "tôi là Nguyễn Văn A và tôi bị ho"
    )
    assert names.calls == 1 and semantic.calls == 0 and result.model_status == "OK"


@pytest.mark.parametrize("second", ["", "hình như 14/3/1978", "14 hoặc 15/3/1978"])
def test_dob_retry_is_limited_without_business_writes(second):
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic)
    bot.start_call(CallStart("dob_retry", "outbound", appointment_id="apt_00417"))
    bot.handle_turn("dob_retry", CallerInput(1, text="Nguyễn Văn A"))
    first = bot.handle_turn("dob_retry", CallerInput(2, text="hình như 14/3/1978"))
    assert first.utterance == t.ASK_DOB_AGAIN
    assert _context(bot, "dob_retry").identity_retries == {"ASK_DOB": 1}
    ended = bot.handle_turn("dob_retry", CallerInput(3, text=second))
    assert ended.transfer_reason == "NOT_UNDERSTOOD"
    assert all(write[1] == "TRANSFERRED" for write in clinic.writes)


def test_invalid_generic_model_label_blocks_the_whole_turn():
    class InvalidLabel:
        def intent(self, text, allowed):
            return Field("INVENTED", Provenance.FALLBACK, text)

    extraction = InformationExtractor(fallback=InvalidLabel()).extract(
        context(QuestionId.ASK_INTENT), "tùy em vậy"
    )
    assert extraction.model_status == "INVALID" and extraction.model_failed


@pytest.mark.parametrize("provider", ["chat", "gemini"])
def test_llm_transport_caps_connection_and_phase_timeouts(provider):
    from types import SimpleNamespace

    from inference.llm.providers._chat_completions import ChatCompletionsProvider
    from inference.llm.providers.gemini import GeminiProvider

    adapter = ChatCompletionsProvider if provider == "chat" else GeminiProvider
    configured = adapter(SimpleNamespace(timeout_s=25, connect_timeout_s=10))
    assert configured._timeout.connect == 1
    assert configured._timeout.read == 3
    assert configured._timeout.write == 3


def test_ie_model_trace_contains_metadata_only():
    sink = _MemorySink()
    tracer = _tracer(sink)
    with tracer.start_trace(call_id="trace", turn=4, component="TURN", operation="http.call_turn"):
        InformationExtractor(semantic=FailedSemantic()).extract(
            context(), "tôi đồng ý hủy lịch, cảm ơn em"
        )
    event = next(
        event
        for span in sink.spans
        for event in span.to_dict()["events"]
        if event["name"] == "ie.model"
    )
    assert event["attributes"]["model_result"] == "INVALID"
    assert set(event["attributes"]) == {"model", "latency_ms", "model_result"}
    assert "tôi đồng ý" not in json.dumps(
        [span.to_dict() for span in sink.spans], ensure_ascii=False
    )


class _HandedOverSemantic:
    """Provider chính lỗi, dự phòng nhận lượt (như FailoverSemanticExtractor) rồi không đọc ra gì."""

    def __init__(self):
        self._gateway = type(
            "Gateway", (), {"model": "typesafe-model", "provider_name": "typesafe"}
        )

    def analyze(self, ctx):
        model_budget.hand_over_model("openai-model", "openai")
        return None


def test_ie_model_trace_names_the_provider_that_answered():
    """Dự phòng trả lời thay provider chính: trace lưu cả hai nhãn provider (không PII)."""
    sink = _MemorySink()
    tracer = _tracer(sink)
    with tracer.start_trace(call_id="trace", turn=4, component="TURN", operation="http.call_turn"):
        InformationExtractor(semantic=_HandedOverSemantic()).extract(
            context(), "tôi đồng ý hủy lịch"
        )
    event = next(
        event
        for span in sink.spans
        for event in span.to_dict()["events"]
        if event["name"] == "ie.model"
    )
    attributes = event["attributes"]
    assert attributes["model"] == "openai-model"
    assert (attributes["provider_requested"], attributes["provider_actual"]) == (
        "typesafe",
        "openai",
    )


def guard_fixture(state="AWAITING_CONFIRMATION"):
    slot = {
        "slot_id": "slot_secret",
        "starts_at": "2026-10-14T10:00:00+07:00",
        "clinic_id": "cl_vinmec",
        "phone": "0912345600",
        "doctor_name": "Trần Văn Bác",
    }
    ctx = CallContext(
        CallStart("guard", "outbound", appointment_id="apt_00417"),
        NOW,
        state=state,
        turn=4,
        identity_step="VERIFIED",
        slots=[slot],
        selected_slot_id="slot_secret",
    )
    return ctx, slot, SourceRegistry([slot])


@pytest.mark.parametrize("key", ["phone", "doctor_name", "slot_id"])
def test_output_guard_rejects_forbidden_fields_even_from_registered_renderer(key):
    ctx, slot, sources = guard_fixture()
    template_id = "TEST_FORBIDDEN_" + key

    @renderer(template_id, discloses=True, sources={"slot": "SLOT"})
    def forbidden(ctx, slot):
        return f"Dạ, {slot[key]}."

    try:
        ledger = []
        with bind_ledger(ledger):
            text = forbidden(ctx, slot)
        action = BotAction(text, "AWAITING_CONFIRMATION")
        verdict = output_guard.check(
            output_guard.GuardInput(action, ctx, None, ledger, sources, None)
        )
        assert not verdict.ok
    finally:
        RENDERERS.pop(template_id)


def test_output_guard_allows_named_slot_ids_only_when_offering():
    ctx, slot, sources = guard_fixture("OFFERING_SLOTS")
    ctx.presented_slot_ids = [slot["slot_id"]]
    template_id = "TEST_SLOT_ID_OFFER"

    @renderer(
        template_id,
        discloses=True,
        sources={"slot": "SLOT"},
        disclosed_fields={"slot_id"},
        slot_scope="PRESENTED",
    )
    def offered(ctx, slot):
        return f"Dạ, khung {slot['slot_id']}."

    try:
        ledger = []
        with bind_ledger(ledger):
            text = offered(ctx, slot)
        action = BotAction(text, "OFFERING_SLOTS")
        assert output_guard.check(
            output_guard.GuardInput(action, ctx, None, ledger, sources, None)
        ).ok
        assert not output_guard.check(
            output_guard.GuardInput(
                replace(action, state="AWAITING_CONFIRMATION"), ctx, None, ledger, sources, None
            )
        ).ok
        assert not output_guard.check(
            output_guard.GuardInput(
                BotAction(
                    text, "ENDED", ended=True, outcome="UNREACHABLE", unreachable_reason="VOICEMAIL"
                ),
                ctx,
                None,
                ledger,
                sources,
                None,
            )
        ).ok
    finally:
        RENDERERS.pop(template_id)


def test_write_invariant_blocks_forged_model_confirmation():
    from callbot.engine.session.context import ActionEvidence

    bot, clinic, _ = _at_readback("forged")
    ctx = _context(bot, "forged")
    ctx.turn = 3
    ctx.set_pending("CONFIRM")
    ctx.add_evidence(
        ActionEvidence(
            "CONFIRMATION",
            "CONFIRM",
            None,
            3,
            QuestionId.CONFIRM_READBACK,
            2,
            "đồng ý, à không",
            "AGREE",
            "FALLBACK",
            "đồng ý",
        )
    )
    with pytest.raises(SevereFailureBlocked):
        bot._dialogue._gateway.confirm(ctx)
    assert clinic.writes == []


@pytest.mark.parametrize(
    "text",
    [
        "vâng, không vấn đề gì",
        "được, không sao",
        "vâng, không sao đâu",
        "dạ vâng, không có gì",
        "khong van de gi",
    ],
)
def test_affirmative_idioms_with_khong_confirm_at_readback(text):
    assert not confirmation_veto(text)
    bot, clinic, _ = _at_readback("idiom")
    action = bot.handle_turn("idiom", CallerInput(3, text=text))
    assert action.outcome == "CONFIRMED"
    assert [write[1] for write in clinic.writes] == ["CONFIRMED"]


def test_affirmative_idiom_with_khong_reschedules_at_slot_readback():
    clinic, bot = _at_read_back("idiom_slot")
    _say(bot, "idiom_slot", "được, không sao đâu")
    assert clinic.writes == [("apt_00418", "RESCHEDULED", {"new_slot_id": "slot_b502"})]


@pytest.mark.parametrize(
    "text",
    [
        "vâng, không",
        "đồng ý, à không",
        "tôi muốn hủy à không chỉ hỏi thôi",
        "tôi đổi ý",
        "không sao, nhưng không đi được",
        "vâng không sao, à không",
    ],
)
def test_negation_outside_affirmative_idioms_still_vetoes(text):
    assert confirmation_veto(text)
    for question in (QuestionId.CONFIRM_READBACK, QuestionId.SLOT_READBACK):
        assert extract_agreement(text, question).value is not Agreement.AGREE
