"""Nâng AGREE ở câu xác nhận hủy bằng tầng ngữ nghĩa có kiểm chứng.

Evidence `docs/evidence/t05-cancel-dialogue.md`, đợt 3. An toàn không dựa vào model: model đối
kháng ở đây thử MỌI đoạn con chứa động từ hủy làm `reply_span` với `CONFIRM_ACTION`.
"""

import csv
import hashlib
import json
from datetime import datetime
from typing import Any, Optional

import pytest
from scripts.cancel_eval import CASES, cancel_spans

from callbot.engine import EngineSettings, _semantic_extractor, create_orchestrator
from callbot.engine.extraction import agreement
from callbot.engine.extraction.agreement import (
    UnclearCause,
    cancel_unclear_cause,
    extract_agreement,
)
from callbot.engine.extraction.cancel_promotion import (
    _CAUSAL,
    _CONCLUDING,
    _POLITE,
    _REASON_LINKS,
    _SUBORDINATORS,
    cancel_promotion_verified,
    promotion_rejection,
)
from callbot.engine.extraction.cancel_reason import _PHRASES as REASON_PHRASES
from callbot.engine.extraction.extractor import InformationExtractor, _keep_cancel_threshold
from callbot.engine.extraction.schema import (
    VN_TZ,
    Agreement,
    ClinicalLevel,
    ExtractionResult,
    Field,
    Intent,
    Provenance,
    QuestionId,
    TurnContext,
)
from callbot.engine.extraction.semantic import (
    ReplyKind,
    RuleCandidates,
    SemanticContext,
    SemanticOutcome,
    SemanticReading,
)
from callbot.engine.extraction.text import clean, compile_phrases, normalize, strip_diacritics
from clinic_mock_sim import FakeClinicAPI
from inference.llm.prompt.semantic import (
    PROMPT_VERSION,
    PROMPT_VERSION_CANCEL_CONFIRM,
    PROMPT_VERSION_LUNA,
    PROMPT_VERSION_LUNA_V7,
    PROMPT_VERSION_LUNA_V8,
    PROMPT_VERSION_LUNA_V9,
    build_messages,
)
from tests.engine.extraction.test_agreement import (
    REVIEW_NOT_CONFIRMATIONS,
    SF05_TRANSCRIPTS,
    UNEXPLAINED_CANCEL_VERB,
)

CANCEL = QuestionId.CANCEL_RECONFIRM
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=VN_TZ)

# (câu, span model hợp lý) — được nâng khi model đồng ý
PROMOTABLE = [
    ("Thôi thì hủy giúp tôi vậy", "hủy giúp tôi"),
    ("dạ thôi thì hủy luôn cho chị", "hủy luôn cho chị"),
    ("thế thì hủy giúp em", "hủy giúp em"),
    ("vậy thì hủy lịch giúp tôi", "hủy lịch giúp tôi"),
    ("hủy lịch vì hôm ấy tôi bận", "hủy lịch"),
    ("Hủy giúp em nhé, dạo này tôi kẹt việc", "hủy giúp em nhé"),
    ("tôi bận nên hủy lịch giúp tôi", "hủy lịch giúp tôi"),
    ("dạo này tôi bận nên hủy lịch giúp tôi", "hủy lịch giúp tôi"),
    ("dạo này tôi bận, hủy lịch giúp tôi", "hủy lịch giúp tôi"),
    ("tôi khám chỗ khác rồi nên hủy giúp tôi", "hủy giúp tôi"),
    ("hủy giúp em nhé bởi vì dạo này tôi hết tiền", "hủy giúp em nhé"),
    # không dấu
    ("thoi thi huy giup toi vay", "huy giup toi"),
    ("huy lich vi hom ay toi ket viec", "huy lich"),
]

# Mỗi câu bị chặn với MỌI span; nhóm theo thành phần của ngữ pháp (plan §3.1–3.2)
NOT_PROMOTABLE = [
    # review P1: phần ngoài span không được giải thích
    "tôi phản đối hủy lịch",
    "Hủy thì tiếc lắm",
    # R1: lý do trước không có dấu ngắt
    "dạo này tôi bận hủy lịch",
    "dao nay toi ket viec huy lich",
    # R2: từ nối không liền span / không có lý do trước từ nối
    "tôi bận nên vợ tôi hủy lịch",
    "tôi bận nên đã hủy lịch",
    "nên hủy lịch giúp tôi",
    # R3: lý do sau không từ nối, không dấu ngắt
    "hủy lịch hôm ấy tôi bận",
    "hủy giúp tôi dạo này tôi kẹt việc",
    # B3: hai lý do, lý do bị phủ định, không có mã, có động từ hành động, hai mệnh đề lý do
    "hủy giúp tôi vì bận mà cũng đắt quá",
    "hủy giúp tôi vì tôi không bận",
    "hủy giúp tôi vì vợ tôi bảo",
    "vì tôi bận việc hủy lịch khác, hủy giúp tôi",
    "hủy giúp tôi vì tôi phải đổi lịch khác",
    "tôi bận nên hủy giúp tôi vì hết tiền",
    # B2 "thôi thì": chỉ khi mở câu và liền nhau
    "thôi hủy đi",
    "thôi, hủy đi",
    "thôi thì thôi",
    "thôi thì không hủy nữa",
    "thôi thì để tôi nghĩ",
    "thôi thì hủy à",
    "hủy đi thôi thì",
    "thôi. thì hủy đi",
    "tôi thôi thì hủy đi",
    # không thuộc ngữ pháp (plan §3.1)
    "hôm qua tôi đã hủy lịch",
    "nếu phải trả phí thì hủy",
    "Tôi xác nhận lịch hủy",
    "lịch hủy đi",
    "có hủy lịch",
    "Tôi có hủy lịch",
]


def _eval_negatives() -> list[str]:
    with CASES.open(encoding="utf-8", newline="") as source:
        return [
            row["transcript"]
            for row in csv.DictReader(source)
            if row["question_id"] == CANCEL.value and row["expect_behaviour"] != "CANCEL"
        ]


# Tập âm tính của model đối kháng (plan bước 1)
ADVERSARIAL_NEGATIVES = sorted(
    {
        *SF05_TRANSCRIPTS,
        *UNEXPLAINED_CANCEL_VERB,
        *REVIEW_NOT_CONFIRMATIONS,
        # AC-2 (`test_cancel_dialogue.test_answers_below_the_cancel_threshold_never_write`, mâu thuẫn)
        "vâng",
        "chắc là hủy",
        "thôi hủy đi",
        "dung huy",
        "Không, hủy đi",
        "Đừng. Hủy đi.",
        "khong, huy di",
        *_eval_negatives(),
        *NOT_PROMOTABLE,
    }
)


# --- Ngữ pháp và ranh giới -------------------------------------------------------------------


@pytest.mark.parametrize("transcript, span", PROMOTABLE)
def test_grammar_accepts_a_confirmation_with_a_benign_remainder(transcript: str, span: str) -> None:
    assert cancel_unclear_cause(transcript) is UnclearCause.LEFTOVER
    assert promotion_rejection(transcript, span) is None


@pytest.mark.parametrize("transcript", NOT_PROMOTABLE)
def test_grammar_rejects_every_span_outside_the_benign_grammar(transcript: str) -> None:
    accepted = [s for s in cancel_spans(transcript) if cancel_promotion_verified(transcript, s)]
    assert accepted == []


@pytest.mark.parametrize(
    "blocked, accepted",
    [
        # R1: dấu ngắt là ranh giới
        ("dạo này tôi bận hủy lịch", "dạo này tôi bận, hủy lịch giúp tôi"),
        # R2: có lý do trước từ nối, và từ nối liền span
        ("nên hủy lịch giúp tôi", "tôi bận nên hủy lịch giúp tôi"),
        ("tôi bận nên vợ tôi hủy lịch", "tôi bận nên hủy lịch giúp tôi"),
        ("tôi bận nên đã hủy lịch", "tôi bận nên hủy lịch giúp tôi"),
        # R3: từ nối hoặc dấu ngắt mở mệnh đề lý do
        ("hủy lịch hôm ấy tôi bận", "hủy lịch vì hôm ấy tôi bận"),
        ("hủy giúp tôi dạo này tôi kẹt việc", "hủy giúp tôi, dạo này tôi kẹt việc"),
    ],
)
def test_the_clause_boundary_is_decided_by_the_rule(blocked: str, accepted: str) -> None:
    assert not any(cancel_promotion_verified(blocked, s) for s in cancel_spans(blocked))
    assert any(cancel_promotion_verified(accepted, s) for s in cancel_spans(accepted))


def test_a_span_that_is_not_itself_a_confirmation_is_rejected() -> None:
    transcript = "Thôi thì hủy giúp tôi vậy"
    assert promotion_rejection(transcript, "thôi thì hủy giúp tôi vậy") == "clause"
    assert promotion_rejection(transcript, "giúp tôi") == "clause"  # không có động từ hủy
    assert promotion_rejection(transcript, "hủy giúp tôi luôn") == "span"  # không có trong câu
    assert promotion_rejection(transcript, None) == "span"


def test_only_a_leftover_cause_can_be_promoted() -> None:
    assert cancel_unclear_cause("hủy luôn không") is UnclearCause.TAG_QUESTION
    assert cancel_unclear_cause("hủy đi nhưng để tôi nghĩ lại") is UnclearCause.CONTRAST
    assert cancel_unclear_cause("Em hủy lịch tôi rồi?") is UnclearCause.QUESTION
    assert cancel_unclear_cause("Không, hủy đi") is UnclearCause.CLAUSE_SPLIT
    assert cancel_unclear_cause("chắc là hủy") is UnclearCause.HEDGE
    assert cancel_unclear_cause("hủy đi") is None  # luật đã AGREE
    assert promotion_rejection("hủy luôn không", "hủy luôn") == "cause"
    # "à" sau động từ là hỏi lại: luật xếp LEFTOVER, ngữ pháp ④ chặn
    assert cancel_unclear_cause("Hủy à, tôi bận quá") is UnclearCause.LEFTOVER
    assert promotion_rejection("Hủy à, tôi bận quá", "hủy") == "remainder"


# --- Tính chất cấu trúc ------------------------------------------------------------------------


def _vocabulary() -> frozenset[str]:
    """Bộ kiểm độc lập, viết đơn giản: mọi từ có thể xuất hiện trong ngữ pháp B1–B3."""
    words: set[str] = set()
    for forms in (_POLITE, _CONCLUDING, _CAUSAL, _SUBORDINATORS):
        for form in forms:
            words.update(w for phrase in form for w in phrase)
    for phrases in (_REASON_LINKS, *REASON_PHRASES.values()):
        for phrase, _ in phrases.both:
            words.update(phrase.split())
    for name in ("_CANCEL_ADDRESS", "_CANCEL_PARTICLES", "_CANCEL_LEAD", "_CANCEL_AFFIRM"):
        value = getattr(agreement, name)
        items = value if isinstance(value, frozenset) else {p for p, _ in value.both}
        words.update(w for item in items for w in item.split())
    return frozenset(words | {strip_diacritics(w) for w in words})


@pytest.mark.parametrize(
    "transcript", [t for t, _ in PROMOTABLE] + ADVERSARIAL_NEGATIVES + NOT_PROMOTABLE
)
def test_every_accepted_span_leaves_only_grammar_words(transcript: str) -> None:
    """Tính chất của hàm (không phải bằng chứng cho mọi câu): nâng được thì mọi từ ngoài span đều
    thuộc từ vựng của ngữ pháp."""
    vocabulary = _vocabulary()
    for span in cancel_spans(transcript):
        if not cancel_promotion_verified(transcript, span):
            continue
        words, target = clean(transcript).split(), clean(span).split()
        start = next(i for i in range(len(words)) if words[i : i + len(target)] == target)
        remainder = words[:start] + words[start + len(target) :]
        assert set(remainder) <= vocabulary, (transcript, span, set(remainder) - vocabulary)


# --- Model đối kháng -------------------------------------------------------------------------


@pytest.mark.parametrize("transcript", ADVERSARIAL_NEGATIVES)
def test_an_adversarial_model_cannot_promote_a_negative(transcript: str) -> None:
    """Model trả CONFIRM_ACTION với MỌI đoạn con chứa động từ hủy: không đoạn nào được AGREE."""
    for span in cancel_spans(transcript) or [normalize(transcript)]:
        extractor = InformationExtractor(
            semantic=_Replying(SemanticOutcome(ReplyKind.CONFIRM_ACTION, span)),
            cancel_semantic_confirm=True,
        )
        result = extractor.extract(_turn_context(), transcript)
        assert result.agreement.value is not Agreement.AGREE, (transcript, span)


# --- Đường luật không đổi khi tắt flag / model không dùng được ---------------------------------

REASON_SENTENCES = [
    "hủy lịch vì hôm ấy tôi bận",
    "Hủy giúp em nhé, dạo này tôi kẹt việc",
    "tôi bận nên hủy lịch giúp tôi",
]


@pytest.mark.parametrize("transcript", REASON_SENTENCES)
def test_new_reason_sentences_stay_unclear_on_the_rule_path(transcript: str) -> None:
    assert extract_agreement(transcript, CANCEL).value is Agreement.UNCLEAR


@pytest.mark.parametrize("transcript", REASON_SENTENCES + ["Thôi thì hủy giúp tôi vậy"])
@pytest.mark.parametrize(
    "semantic, enabled",
    [
        (None, True),
        ("exception", True),
        ("none", True),
        ("ambiguous", True),
        ("confirm", False),  # flag tắt: model đồng ý cũng không nâng
    ],
    ids=["off_model", "exception", "none", "ambiguous", "flag_off"],
)
def test_the_rule_path_is_unchanged_without_a_usable_model(
    transcript: str, semantic: Optional[str], enabled: bool
) -> None:
    replies = {
        None: None,
        "exception": _Replying(error=True),
        "none": _Replying(),
        "ambiguous": _Replying(SemanticOutcome(ReplyKind.AMBIGUOUS, "hủy")),
        "confirm": _Replying(SemanticOutcome(ReplyKind.CONFIRM_ACTION, "hủy")),
    }
    extractor = InformationExtractor(semantic=replies[semantic], cancel_semantic_confirm=enabled)
    assert extractor.extract(_turn_context(), transcript).agreement.value is Agreement.UNCLEAR


def test_the_shared_reason_links_are_unchanged() -> None:
    """`_REASON_LINKS` của luật toàn câu giữ nguyên như mốc 516d3d5; tầng nâng dùng tập riêng."""
    baseline = compile_phrases(
        ["vì", "bởi vì", "tại vì", "do", "tại", "bởi", "hôm đó", "ngày đó", "quá", "lắm"],
        unaccented_exclude=["do", "tại", "quá", "lắm"],
    )
    for form in ("accented", "unaccented"):
        current = [p for p, _ in getattr(agreement._REASON_LINKS, form)]
        assert current == [p for p, _ in getattr(baseline, form)]


# --- Chốt ở extractor ------------------------------------------------------------------------


@pytest.mark.parametrize("transcript, span", PROMOTABLE)
def test_the_gate_keeps_a_verified_promotion(transcript: str, span: str) -> None:
    extractor = InformationExtractor(
        semantic=_Replying(SemanticOutcome(ReplyKind.CONFIRM_ACTION, span)),
        cancel_semantic_confirm=True,
    )
    result = extractor.extract(_turn_context(), transcript)
    assert result.agreement.value is Agreement.AGREE
    assert result.agreement.provenance is Provenance.FALLBACK
    assert result.agreement.span == normalize(span)


def _promoted(transcript: str, span: str, **changes: Any) -> ExtractionResult:
    skipped = Field.skipped()
    base: dict[str, Any] = dict(
        turn=4,
        question_id=CANCEL,
        transcript=transcript,
        full_name=skipped,
        dob=skipped,
        intent=Field.nothing(Intent.NONE),
        clinical=Field.nothing(ClinicalLevel.NONE),
        agreement=Field(Agreement.AGREE, Provenance.FALLBACK, span=normalize(span)),
        slot_choice=skipped,
        cancel_reason=Field.nothing("UNSPECIFIED"),
        line_signal=skipped,
    )
    return ExtractionResult(**{**base, **changes})


GATE_TRANSCRIPT, GATE_SPAN = PROMOTABLE[0]
RULE = Field(Agreement.UNCLEAR, Provenance.EXACT, span=clean(GATE_TRANSCRIPT))
CONFIRM = SemanticOutcome(ReplyKind.CONFIRM_ACTION, normalize(GATE_SPAN))


@pytest.mark.parametrize(
    "outcome, ctx, changes",
    [
        (None, {}, {}),
        (SemanticOutcome(ReplyKind.AMBIGUOUS, normalize(GATE_SPAN)), {}, {}),
        (SemanticOutcome(ReplyKind.QUESTION, normalize(GATE_SPAN)), {}, {}),
        (SemanticOutcome(ReplyKind.CONFIRM_ACTION, "hủy giúp"), {}, {}),  # span lệch agreement
        (CONFIRM, {"question_turn": 2}, {}),  # câu hỏi không ở lượt ngay trước
        (CONFIRM, {"question_turn": None}, {}),
        (CONFIRM, {"question_id": QuestionId.ASK_INTENT}, {}),
        (CONFIRM, {}, {"intent": Field(Intent.RESCHEDULE, Provenance.FALLBACK, span="x")}),
        (CONFIRM, {}, {"intent": Field(Intent.OUT_OF_SCOPE, Provenance.FALLBACK, span="x")}),
        (CONFIRM, {}, {"clinical": Field(ClinicalLevel.MENTION, Provenance.FALLBACK, span="x")}),
        (
            CONFIRM,
            {},
            {"clinical": Field(ClinicalLevel.ADVICE_REQUEST, Provenance.FALLBACK, span="x")},
        ),
    ],
    ids=[
        "no_outcome",
        "ambiguous",
        "question",
        "span_mismatch",
        "stale_question",
        "no_question",
        "other_question",
        "reschedule_after_merge",
        "out_of_scope_after_merge",
        "clinical_mention_after_merge",
        "clinical_advice_after_merge",
    ],
)
def test_the_gate_rechecks_every_condition_itself(
    outcome: Optional[SemanticOutcome], ctx: dict[str, Any], changes: dict[str, Any]
) -> None:
    result = _promoted(GATE_TRANSCRIPT, GATE_SPAN, **changes)
    kept = _keep_cancel_threshold(
        RULE, result, _turn_context(**ctx), outcome, promotion_enabled=True
    )
    assert kept.agreement.value is Agreement.UNCLEAR


@pytest.mark.parametrize("other", [Intent.RESCHEDULE, Intent.OUT_OF_SCOPE])
def test_a_rejected_promotion_keeps_another_need_the_rule_read(other: Intent) -> None:
    """ "hủy đi, à thôi đổi sang tuần sau": CONFIRM_ACTION bị bác không được đè RESCHEDULE thành hủy."""
    result = _promoted(GATE_TRANSCRIPT, GATE_SPAN, intent=Field(other, Provenance.EXACT, span="x"))
    kept = _keep_cancel_threshold(RULE, result, _turn_context(), CONFIRM, promotion_enabled=True)
    assert kept.intent.value is other


def test_a_rejected_promotion_is_still_a_cancel_intent() -> None:
    kept = _keep_cancel_threshold(
        RULE,
        _promoted(GATE_TRANSCRIPT, GATE_SPAN),
        _turn_context(question_turn=2),
        CONFIRM,
        promotion_enabled=True,
    )
    assert kept.intent.value is Intent.CANCEL


def test_the_gate_drops_a_promotion_when_the_flag_is_off() -> None:
    kept = _keep_cancel_threshold(
        RULE,
        _promoted(GATE_TRANSCRIPT, GATE_SPAN),
        _turn_context(),
        CONFIRM,
        promotion_enabled=False,
    )
    assert kept.agreement.value is Agreement.UNCLEAR
    kept = _keep_cancel_threshold(
        RULE,
        _promoted(GATE_TRANSCRIPT, GATE_SPAN),
        _turn_context(),
        CONFIRM,
        promotion_enabled=True,
    )
    assert kept.agreement.value is Agreement.AGREE


@pytest.mark.parametrize("transcript", SF05_TRANSCRIPTS)
def test_a_merge_that_always_promotes_still_cannot_cancel_sf05(
    monkeypatch, transcript: str
) -> None:
    """Bảng quyền bị đổi sai sau này (luôn nâng) thì chốt vẫn tự kiểm chứng và hạ UNCLEAR."""
    import callbot.engine.extraction.extractor as extractor_module

    def promoting(result, outcome, route_reason, allowed, **_kwargs):
        return extractor_module.replace(
            result, agreement=Field(Agreement.AGREE, Provenance.FALLBACK, span=outcome.reply_span)
        )

    monkeypatch.setattr(extractor_module, "merge_semantic", promoting)
    for span in cancel_spans(transcript):
        extractor = InformationExtractor(
            semantic=_Replying(SemanticOutcome(ReplyKind.CONFIRM_ACTION, span)),
            cancel_semantic_confirm=True,
        )
        assert extractor.extract(_turn_context(), transcript).agreement.value is Agreement.UNCLEAR


# --- Helpers ---------------------------------------------------------------------------------


class _Replying:
    def __init__(self, outcome: Optional[SemanticOutcome] = None, error: bool = False) -> None:
        self._outcome, self._error = outcome, error

    def analyze(self, context: SemanticContext) -> Optional[SemanticOutcome]:
        if self._error:
            raise RuntimeError("provider down")
        return self._outcome


def _turn_context(**changes: Any) -> TurnContext:
    base = dict(
        turn=4,
        question_id=CANCEL,
        direction="outbound",
        now=NOW,
        pending_action="CANCEL",
        question_turn=3,
    )
    return TurnContext(**{**base, **changes})


# --- Prompt theo flag (plan bước 4, bước 6) -----------------------------------------------------

# sha256 của messages semantic_v5 cho ngữ cảnh dưới đây, tính trên mã mốc 516d3d5
V5_BASELINE_SHA256 = "7241a25f9906c11d74b947a67e34b1eb35176de9c31760aba0ce4677b9d9b721"


def _prompt_context() -> SemanticContext:
    return SemanticContext(
        transcript="Thôi thì hủy giúp tôi vậy",
        question_id=CANCEL,
        direction="outbound",
        allowed_intents=(Intent.CONFIRM, Intent.CANCEL, Intent.RESCHEDULE, Intent.OUT_OF_SCOPE),
        route_reason="CANCEL_CONTRADICTION",
        pending_action="CANCEL",
        answers_last_question=True,
        candidates=RuleCandidates(agreement=None),
    )


def test_the_v5_messages_are_byte_identical_to_the_baseline() -> None:
    payload = json.dumps(build_messages(_prompt_context()), ensure_ascii=False, sort_keys=True)
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == V5_BASELINE_SHA256


def test_v6_only_appends_the_cancel_span_rules_to_v5() -> None:
    v5 = build_messages(_prompt_context())
    v6 = build_messages(_prompt_context(), version=PROMPT_VERSION_CANCEL_CONFIRM)
    assert v6[0]["content"] != v5[0]["content"]
    assert v6[0]["content"].startswith(v5[0]["content"].rsplit("Chỉ trả JSON", 1)[0])
    assert v6[1 : len(v5) - 1] == v5[1:-1]  # ví dụ v5 là tiền tố không đổi
    assert v6[-1] == v5[-1]


def test_luna_prompt_is_smaller_and_keeps_the_runtime_contract() -> None:
    context = _prompt_context()
    v6 = build_messages(context, version=PROMPT_VERSION_CANCEL_CONFIRM)
    luna = build_messages(context, version=PROMPT_VERSION_LUNA)
    encoded_v6 = json.dumps(v6, ensure_ascii=False, separators=(",", ":"))
    encoded_luna = json.dumps(luna, ensure_ascii=False, separators=(",", ":"))

    assert len(encoded_luna) < len(encoded_v6)
    assert "dữ liệu không tin cậy" in luna[0]["content"]
    payload = json.loads(luna[-1]["content"])
    assert payload["transcript"] == context.transcript
    assert payload["pending_action"] == "CANCEL"
    assert payload["allowed_intents"] == ["CONFIRM", "CANCEL", "RESCHEDULE", "OUT_OF_SCOPE"]


def test_compact_luna_prompt_preserves_examples_and_runtime_context() -> None:
    context = _prompt_context()
    previous = build_messages(context, version=PROMPT_VERSION_LUNA_V7)
    compact = build_messages(context, version=PROMPT_VERSION_LUNA_V8)
    assert compact[0]["content"].startswith(previous[0]["content"])
    assert compact[-1] == previous[-1]
    assert len(compact) == len(previous)
    for old, new in zip(previous[1:-1], compact[1:-1], strict=True):
        assert old["role"] == new["role"]
        before, after = json.loads(old["content"]), json.loads(new["content"])
        if old["role"] == "assistant":
            assert after == before
        else:
            assert after == {key: before[key] for key in ("question_id", "transcript")}
    assert sum(len(m["content"]) for m in compact) < 0.8 * sum(len(m["content"]) for m in previous)


@pytest.mark.parametrize(
    "enabled, model, version",
    [
        (False, "gpt-6-luna", PROMPT_VERSION),
        (True, "gpt-6-luna", PROMPT_VERSION_LUNA),
        (True, "gpt-4o-mini", PROMPT_VERSION_CANCEL_CONFIRM),
    ],
)
def test_the_factory_picks_the_prompt_and_the_gate_from_the_flag(
    monkeypatch, enabled: bool, model: str, version: str
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    # Cách tự chọn prompt khi để trống (engine.yaml ghim semantic_v10_luna cho DeepSeek)
    settings = EngineSettings(
        semantic_fallback_enabled=True,
        semantic_provider="openai",
        semantic_backup_provider="none",
        semantic_llm_prompt_version=None,
        semantic_llm_model=model,
        cancel_semantic_confirm_enabled=enabled,
    )
    extractor = _semantic_extractor(settings)
    assert extractor is not None and extractor.prompt_version == version
    bot = create_orchestrator(FakeClinicAPI(), settings=settings, store=_memory_store())
    assert bot._extractor._cancel_semantic_confirm is enabled


def _memory_store():
    import fakeredis

    from callbot.engine.session import RedisSessionStore

    return RedisSessionStore(fakeredis.FakeRedis(decode_responses=True), key_prefix="promo")


def test_v9_prompt_extends_v8_without_changing_it() -> None:
    from inference.llm.prompt.semantic import LUNA_V9_RULES

    context = _prompt_context()
    v8 = build_messages(context, version=PROMPT_VERSION_LUNA_V8)
    v9 = build_messages(context, version=PROMPT_VERSION_LUNA_V9)
    assert LUNA_V9_RULES in v9[0]["content"] and LUNA_V9_RULES not in v8[0]["content"]
    assert v9[1 : len(v8) - 1] == v8[1:-1]  # ví dụ v8 giữ nguyên, v9 chỉ thêm
    assert v9[-1] == v8[-1]


def test_v10_prompt_is_two_messages_with_the_examples_inside_the_cached_system() -> None:
    from inference.llm.prompt.semantic import LUNA_V10_EXAMPLES

    context = _prompt_context()
    v9 = build_messages(context, version=PROMPT_VERSION_LUNA_V9)
    v10 = build_messages(context, version=PROMPT_VERSION_LUNA)
    # Prompt caching GPT-6 chỉ đặt breakpoint ngầm cuối developer message đầu và cuối user message
    # cuối: ví dụ phải nằm trong system mới được cache khi transcript đổi.
    assert [m["role"] for m in v10] == ["system", "user"]
    assert v10[-1] == v9[-1]  # ngữ cảnh lượt hiện tại giữ nguyên contract
    system = v10[0]["content"]
    for _, transcript, reading in LUNA_V10_EXAMPLES:
        compact = json.dumps(json.loads(reading), ensure_ascii=False, separators=(",", ":"))
        assert transcript in system and compact in system
        SemanticReading.model_validate_json(reading)  # ví dụ đúng schema runtime
    assert "title" not in SemanticReading.model_json_schema()


def test_v10_examples_do_not_repeat_scored_eval_cases() -> None:
    """Ví dụ trong prompt không được là câu holdout / new của eval, nếu không eval đo câu đã thấy."""
    import csv
    from pathlib import Path

    from inference.llm.prompt.semantic import LUNA_V10_EXAMPLES

    root = Path(__file__).resolve().parents[3]
    scored: set[str] = set()
    for name in ("cancel", "confirm"):
        with (root / "eval" / name / "cases.csv").open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row["split"] != "prompt":
                    scored.add(strip_diacritics(clean(row["transcript"])))
    for _, transcript, _ in LUNA_V10_EXAMPLES:
        assert strip_diacritics(clean(transcript)) not in scored, transcript
