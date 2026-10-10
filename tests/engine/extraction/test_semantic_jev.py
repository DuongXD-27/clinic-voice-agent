"""Tầng ngữ nghĩa bằng Jev (TypeSafe System One) — KHÔNG gọi mạng; client giả / httpx MockTransport."""

import json
from typing import Any, Optional

import httpx
import pytest

from callbot.engine import _semantic_extractor
from callbot.engine.extraction.schema import Intent, QuestionId
from callbot.engine.extraction.semantic import ReplyKind, RuleCandidates, SemanticContext
from callbot.engine.extraction.semantic_jev import (
    NONE,
    JevSemanticExtractor,
    build_questions,
    build_state,
    span_candidates,
)
from callbot.engine.settings import EngineSettings
from inference.llm.config import TypeSafeConfig
from inference.llm.typesafe import (
    ChoiceAnswer,
    ChoiceQuestion,
    NoulAnswer,
    NoulQuestion,
    SystemOneReply,
    TypeSafeClient,
)

OUTBOUND = (Intent.CONFIRM, Intent.CANCEL, Intent.RESCHEDULE, Intent.OUT_OF_SCOPE)


def _context(transcript: str, **changes: Any) -> SemanticContext:
    base: dict[str, Any] = dict(
        transcript=transcript,
        question_id=QuestionId.CANCEL_RECONFIRM,
        direction="outbound",
        allowed_intents=OUTBOUND,
        route_reason="CANCEL_LEFTOVER",
        pending_action="CANCEL",
    )
    return SemanticContext(**{**base, **changes})


def _answer(choice: str, confidence: float = 0.95) -> ChoiceAnswer:
    return ChoiceAnswer(type="choice", choice=choice, confidence=confidence, probabilities={})


def _noul(probability: float) -> NoulAnswer:
    return NoulAnswer(type="noul", noul=probability)


class FakeClient:
    provider_name = "typesafe"
    model = "jev-test"

    def __init__(self, reply: SystemOneReply) -> None:
        self.reply = reply
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    def evaluate(self, state: Any, questions: dict[str, Any]) -> SystemOneReply:
        self.calls.append((state, questions))
        return self.reply


def _extractor(answers: dict[str, ChoiceAnswer], status: str = "completed"):
    client = FakeClient(SystemOneReply(status, answers))  # type: ignore[arg-type]
    return JevSemanticExtractor(client, max_input_chars=1500, min_confidence=0.6), client  # type: ignore[arg-type]


def _span(candidates: list[str], text: str) -> str:
    return f"c{candidates.index(text)}"


# --- Ứng viên span --------------------------------------------------------------------------


def test_candidates_are_contiguous_pieces_with_the_last_clause_first() -> None:
    context = _context("hủy lịch vì hôm ấy tôi bận")
    candidates = span_candidates(context)
    assert candidates[-1] == "hủy lịch vì hôm ấy tôi bận"
    assert candidates[0] == "hôm ấy tôi bận"
    assert "hủy lịch" in candidates
    assert all(c in context.transcript for c in candidates)


def test_candidates_trim_leading_connectors_and_trailing_particles_but_keep_di() -> None:
    assert "hủy giúp tôi" in span_candidates(_context("thôi thì hủy giúp tôi vậy"))
    candidates = span_candidates(_context("hủy đi em"))
    assert "hủy đi" in candidates and "hủy" not in candidates


def test_rule_span_is_offered_so_cancel_promotion_can_match() -> None:
    context = _context(
        "ừ thì cứ hủy lịch giúp tôi", candidates=RuleCandidates(agreement_span="hủy lịch")
    )
    assert "hủy lịch" in span_candidates(context)


def test_single_piece_transcript_asks_no_span_question() -> None:
    context = _context("vâng")
    questions = build_questions(context, span_candidates(context))
    assert not any(name.endswith("_span") for name in questions)


# --- Câu hỏi và state ------------------------------------------------------------------------


def test_state_has_no_rule_hints_and_safest_option_first() -> None:
    context = _context("không, hủy đi", candidates=RuleCandidates(intent=Intent.CANCEL))
    state = build_state(context)
    assert "rule_hints_untrusted" not in state and "candidates" not in state
    questions = build_questions(context, span_candidates(context))
    assert next(iter(questions["reply_kind"].criteria)) == "AMBIGUOUS"
    assert next(iter(questions["intent"].criteria)) == NONE
    assert set(questions["intent"].criteria) == {NONE, *(i.value for i in OUTBOUND)}


def test_no_allowed_intents_means_no_intent_question() -> None:
    context = _context("không, hủy đi", allowed_intents=())
    questions = build_questions(context, span_candidates(context))
    assert "intent" not in questions and "intent_span" not in questions


# --- Đổi câu trả lời thành outcome -----------------------------------------------------------


def test_confirm_with_span_is_accepted() -> None:
    context = _context("thôi thì hủy giúp tôi vậy")
    candidates = span_candidates(context)
    extractor, _ = _extractor(
        {
            "reply_kind": _answer("CONFIRM_ACTION"),
            "intent": _answer("CANCEL"),
            "cancel_reason": _answer(NONE),
            "clinical": _answer(NONE),
            "reply_span": _answer(_span(candidates, "hủy giúp tôi")),
            "intent_span": _answer(_span(candidates, "hủy giúp tôi")),
            "reason_span": _answer("c0"),
            "clinical_span": _answer("c0"),
        }
    )
    outcome = extractor.analyze(context)
    assert outcome is not None
    assert (outcome.reply_kind, outcome.reply_span) == (ReplyKind.CONFIRM_ACTION, "hủy giúp tôi")
    assert outcome.intent is Intent.CANCEL


def test_low_confidence_confirm_becomes_ambiguous() -> None:
    context = _context("thôi thì hủy giúp tôi vậy")
    candidates = span_candidates(context)
    extractor, _ = _extractor(
        {
            "reply_kind": _answer("CONFIRM_ACTION", confidence=0.4),
            "intent": _answer(NONE),
            "cancel_reason": _answer(NONE),
            "clinical": _answer(NONE),
            "reply_span": _answer(_span(candidates, "hủy giúp tôi")),
            "intent_span": _answer("c0"),
            "reason_span": _answer("c0"),
            "clinical_span": _answer("c0"),
        }
    )
    outcome = extractor.analyze(context)
    assert outcome is not None and outcome.reply_kind is ReplyKind.AMBIGUOUS
    assert outcome.reply_span is None


def test_span_questions_are_speculative_without_a_none_option() -> None:
    """NONE ở câu span hút xác suất và làm rơi DECLINE_ACTION đúng (eval cancel 10-10)."""
    context = _context("thôi thì hủy giúp tôi vậy")
    candidates = span_candidates(context)
    questions = build_questions(context, candidates)
    for name in ("reply_span", "intent_span", "reason_span", "clinical_span"):
        assert NONE not in questions[name].criteria
        assert len(questions[name].criteria) == len(candidates)


@pytest.mark.parametrize(
    ("answer", "expected"),
    [("PATIENT_UNAVAILABLE", "PATIENT_UNAVAILABLE"), (NONE, "UNSPECIFIED")],
)
def test_reason_code_is_argmax_and_none_becomes_unspecified(answer: str, expected: str) -> None:
    """Mã lý do không mở khóa ghi: lấy argmax kể cả khi phân phối dàn trải."""
    context = _context("con tôi ốm nên tôi phải trông cháu")
    candidates = span_candidates(context)
    extractor, _ = _extractor(
        {
            "reply_kind": _answer("INFORM_REASON"),
            "intent": _answer(NONE),
            "cancel_reason": _answer(answer, confidence=0.3),
            "clinical": _answer(NONE),
            "reply_span": _answer("c0"),
            "intent_span": _answer("c0"),
            "reason_span": _answer(_span(candidates, "tôi phải trông cháu")),
            "clinical_span": _answer("c0"),
        }
    )
    outcome = extractor.analyze(context)
    assert outcome is not None and outcome.reply_kind is ReplyKind.INFORM_REASON
    assert (outcome.cancel_reason, outcome.reason_span) == (expected, "tôi phải trông cháu")


def test_out_of_scope_needs_a_request_or_question() -> None:
    """ "Để tôi hỏi vợ rồi gọi lại": câu mơ hồ không được kéo theo chuyển máy."""
    context = _context("để tôi hỏi nhà tôi rồi báo lại em")
    extractor, _ = _extractor(
        {
            "reply_kind": _answer("AMBIGUOUS"),
            "intent": _answer("OUT_OF_SCOPE"),
            "cancel_reason": _answer(NONE),
            "clinical": _answer(NONE),
            "reply_span": _answer("c0"),
            "intent_span": _answer("c0"),
            "reason_span": _answer("c0"),
            "clinical_span": _answer("c0"),
        }
    )
    outcome = extractor.analyze(context)
    assert outcome is not None and outcome.intent is None


def test_gate_uses_the_chosen_option_probability() -> None:
    context = _context("hủy xong đặt lại được chứ")
    answer = ChoiceAnswer(
        type="choice",
        choice="CHANGE_INTENT",
        confidence=0.2,
        probabilities={"CHANGE_INTENT": 0.7, "QUESTION": 0.3},
    )
    extractor, _ = _extractor(
        {
            "reply_kind": answer,
            "intent": _answer("RESCHEDULE"),
            "cancel_reason": _answer(NONE),
            "clinical": _answer(NONE),
            "reply_span": _answer("c0"),
            "intent_span": _answer("c0"),
            "reason_span": _answer("c0"),
            "clinical_span": _answer("c0"),
        }
    )
    outcome = extractor.analyze(context)
    assert outcome is not None and outcome.reply_kind is ReplyKind.CHANGE_INTENT


def test_low_confidence_change_intent_becomes_ambiguous() -> None:
    context = _context("hủy xong đặt lại được chứ", allowed_intents=OUTBOUND)
    extractor, _ = _extractor(
        {
            "reply_kind": _answer("CHANGE_INTENT", confidence=0.5),
            "intent": _answer("RESCHEDULE"),
            "cancel_reason": _answer(NONE),
            "clinical": _answer(NONE),
        }
    )
    outcome = extractor.analyze(context)
    assert outcome is not None and outcome.reply_kind is ReplyKind.AMBIGUOUS


def _readback(
    transcript: str,
    *,
    kind: str = "AMBIGUOUS",
    intent: str = NONE,
    reason: str = NONE,
    cannot_attend: float = 0.0,
    will_attend: float = 0.0,
    wants_other_time: float = 0.0,
):
    context = _context(transcript, question_id=QuestionId.CONFIRM_READBACK, pending_action=None)
    extractor, client = _extractor(
        {
            "reply_kind": _answer(kind),
            "intent": _answer(intent),
            "cancel_reason": _answer(reason),
            "clinical": _answer(NONE),
            "cannot_attend": _noul(cannot_attend),
            "will_attend": _noul(will_attend),
            "wants_other_time": _noul(wants_other_time),
            **{f"{n}_span": _answer("c0") for n in ("reply", "intent", "reason", "clinical")},
        }
    )
    return extractor.analyze(context), client


def test_attendance_nouls_are_asked_only_at_readback_and_ask_intent() -> None:
    readback = _context("hôm đó tôi rảnh", question_id=QuestionId.CONFIRM_READBACK)
    ask_intent = _context("hôm đó tôi rảnh", question_id=QuestionId.ASK_INTENT)
    cancel = _context("hôm đó tôi rảnh")
    for context, expected in ((readback, True), (ask_intent, True), (cancel, False)):
        questions = build_questions(context, span_candidates(context))
        assert ("cannot_attend" in questions) is expected
        assert ("wants_other_time" in questions) is expected


@pytest.mark.parametrize("kind", ["CONFIRM_ACTION", "DECLINE_ACTION", "AMBIGUOUS"])
def test_will_attend_is_change_intent_confirm(kind: str) -> None:
    """Hợp đồng nhãn LLM: "tôi vẫn đến" ở câu đọc lịch là CHANGE_INTENT + CONFIRM."""
    outcome, _ = _readback("không đổi gì cả, tôi đến", kind=kind, will_attend=0.9)
    assert outcome is not None
    assert (outcome.reply_kind, outcome.intent) == (ReplyKind.CHANGE_INTENT, Intent.CONFIRM)


def test_obstacle_wins_over_agreement() -> None:
    """ "Dạ được, mà hôm đó tôi phải ...": có trở ngại thì không phải sẽ đến."""
    outcome, _ = _readback(
        "dạ được, mà hôm đó tôi phải đi đám",
        kind="CONFIRM_ACTION",
        intent="CONFIRM",
        cannot_attend=0.8,
        will_attend=0.6,
    )
    assert outcome is not None and outcome.reply_kind is ReplyKind.INFORM_REASON
    assert outcome.intent is None


def test_cannot_attend_without_a_code_is_patient_unavailable() -> None:
    outcome, _ = _readback("đúng rồi, không qua được", kind="INFORM_REASON", cannot_attend=0.9)
    assert outcome is not None
    assert (outcome.reply_kind, outcome.cancel_reason) == (
        ReplyKind.INFORM_REASON,
        "PATIENT_UNAVAILABLE",
    )


def test_reason_without_cannot_attend_is_ambiguous() -> None:
    """ "Tôi được nghỉ hôm đó mà": Choice nói lý do nhưng Noul không thấy trở ngại -> hỏi lại."""
    outcome, _ = _readback(
        "tôi được nghỉ hôm đó mà", kind="INFORM_REASON", reason="PATIENT_UNAVAILABLE"
    )
    assert outcome is not None and outcome.reply_kind is ReplyKind.AMBIGUOUS
    assert outcome.cancel_reason is None


def test_other_time_request_is_reschedule_even_as_a_question() -> None:
    outcome, _ = _readback("dời sang thứ bảy được không em", kind="QUESTION", wants_other_time=0.8)
    assert outcome is not None
    assert (outcome.reply_kind, outcome.intent) == (ReplyKind.CHANGE_INTENT, Intent.RESCHEDULE)


def test_explicit_cancel_wins_over_attendance_nouls() -> None:
    outcome, _ = _readback(
        "không đi được, bỏ lịch đó đi",
        kind="DECLINE_ACTION",
        intent="CANCEL",
        cannot_attend=0.9,
    )
    assert outcome is not None
    assert (outcome.reply_kind, outcome.intent) == (ReplyKind.CHANGE_INTENT, Intent.CANCEL)


def test_probabilities_are_kept_for_eval_without_spans() -> None:
    extractor, _ = _extractor(
        {
            "reply_kind": _answer("AMBIGUOUS"),
            "intent": _answer(NONE),
            "cancel_reason": _answer(NONE),
            "clinical": _answer(NONE),
        }
    )
    extractor.analyze(_context("vâng"))
    assert extractor.last_probabilities is not None
    assert set(extractor.last_probabilities) == {
        "reply_kind",
        "intent",
        "cancel_reason",
        "clinical",
    }


def test_unaccented_transcript_gets_a_note() -> None:
    assert "transcript_note" in build_state(_context("giu lich giup toi"))
    assert "transcript_note" not in build_state(_context("giữ lịch giúp tôi"))


def test_low_confidence_clinical_is_kept() -> None:
    """Bỏ nhãn lâm sàng vì model không chắc là lệch về bỏ sót (SF-04)."""
    context = _context("vâng", question_id=QuestionId.CONFIRM_READBACK, pending_action=None)
    extractor, _ = _extractor(
        {
            "reply_kind": _answer("AMBIGUOUS"),
            "intent": _answer(NONE),
            "cancel_reason": _answer(NONE),
            "clinical": _answer("ADVICE_REQUEST", confidence=0.3),
        }
    )
    outcome = extractor.analyze(context)
    assert outcome is not None and outcome.clinical is not None
    assert outcome.clinical_span == "vâng"


@pytest.mark.parametrize("status", ["timeout", "http_error", "invalid_response"])
def test_provider_failure_returns_none(status: str) -> None:
    extractor, _ = _extractor({}, status=status)
    assert extractor.analyze(_context("không, hủy đi")) is None


def test_too_long_input_is_not_sent() -> None:
    extractor, client = _extractor({})
    extractor._max_input_chars = 5
    assert extractor.analyze(_context("không, hủy đi")) is None
    assert client.calls == []


# --- Client HTTP -----------------------------------------------------------------------------


@pytest.fixture
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test")


def _client(handler) -> TypeSafeClient:
    config = TypeSafeConfig(timeout_s=2.0)
    return TypeSafeClient(
        config, client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )


QUESTION = {"kind": ChoiceQuestion("pick", {"A": None, "B": "second"})}


def test_client_sends_one_request_and_parses_answers(_key: None) -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer ts-test"
        body = {
            "model": "jev-1.13.0",
            "answers": {
                "kind": {
                    "type": "choice",
                    "choice": "B",
                    "confidence": 0.8,
                    "probabilities": {"A": 0.2, "B": 0.8},
                }
            },
            "usage": {"input_tokens": 10, "output_tokens": 0},
        }
        return httpx.Response(200, json=body)

    reply = _client(handler).evaluate({"transcript": "x"}, QUESTION)
    assert reply.status == "completed"
    assert reply.answers["kind"].choice == "B"
    assert (reply.prompt_tokens, reply.completion_tokens, reply.actual_model) == (
        10,
        0,
        "jev-1.13.0",
    )
    assert seen[0]["questions"]["kind"] == {
        "type": "choice",
        "instructions": "pick",
        "criteria": {"A": None, "B": "second"},
    }


def test_client_rejects_answer_outside_the_criteria(_key: None) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        answer = {"type": "choice", "choice": "C", "confidence": 1, "probabilities": {}}
        return httpx.Response(200, json={"answers": {"kind": answer}})

    assert _client(handler).evaluate("x", QUESTION).status == "invalid_response"


def test_client_parses_noul_answers(_key: None) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)["questions"]["yes"]
        assert sent == {
            "type": "noul",
            "instructions": "is it?",
            "criteria": {"true": "yes means"},
        }
        return httpx.Response(200, json={"answers": {"yes": {"type": "noul", "noul": 0.7}}})

    reply = _client(handler).evaluate("x", {"yes": NoulQuestion("is it?", true="yes means")})
    assert reply.status == "completed"
    assert isinstance(reply.answers["yes"], NoulAnswer) and reply.answers["yes"].noul == 0.7


def test_client_rejects_wrong_answer_type(_key: None) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"answers": {"kind": {"type": "noul", "noul": 0.7}}})

    assert _client(handler).evaluate("x", QUESTION).status == "invalid_response"


def test_client_reports_http_error(_key: None) -> None:
    reply = _client(lambda request: httpx.Response(429)).evaluate("x", QUESTION)
    assert (reply.status, reply.http_status) == ("http_error", 429)


# --- Factory ---------------------------------------------------------------------------------


def _settings(**changes: Any) -> EngineSettings:
    return EngineSettings(
        semantic_fallback_enabled=True, semantic_fallback_provider="jev", **changes
    )


def test_factory_builds_jev_extractor(_key: None) -> None:
    extractor: Optional[Any] = _semantic_extractor(_settings())
    assert isinstance(extractor, JevSemanticExtractor)
    assert extractor._gateway.provider_name == "typesafe"


def test_factory_without_key_runs_rules_only() -> None:
    assert _semantic_extractor(_settings()) is None
