"""Tầng model cho 4 câu hỏi chọn khung — plan `docs/plans/t10-slot-semantic-jev-2026-10-12.md`.

Phần không phụ thuộc provider: khi nào gọi model (`route_slot_semantic`), kiểm kết quả
(`ground_slot_reading`), bảng ưu tiên (`resolve_slot_act`, §4.9) và chọn provider (`SlotSemanticReader`,
§4.11: Jev chính; Luna khi câu không dấu hoặc Jev lỗi dịch vụ).

Ranh giới như tầng ngữ nghĩa hiện có: model chỉ thấy transcript, mục đích câu hỏi, hành động đang chờ
và SỐ khung trên trang — không thấy giờ khung, giờ lịch hẹn, hồ sơ (C3). Model không trả `slot_id`:
`PICK n` là thứ tự trên trang, `TIME` là đoạn nguyên văn để luật tự tra trên `GET /slots`. Không nhãn
nào mở khóa lệnh ghi (C2): Dialogue chỉ đọc câu chốt / hỏi lại / tra khung.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum
from time import monotonic
from typing import Any, Optional, Protocol

from callbot.engine.extraction.agreement import (
    changes_mind,
    explicit_slot_pick,
    gives_up_if_unavailable,
    gives_up_slot_change,
    is_bare_da,
    is_hesitation_only,
    mentions_busy,
    rechooses,
)
from callbot.engine.extraction.model_budget import hand_over_model, record_model
from callbot.engine.extraction.schema import (
    Agreement,
    ClinicalLevel,
    ExtractionResult,
    Field,
    Intent,
    Provenance,
    QuestionId,
    SlotAct,
    SlotChoice,
    SlotCriteria,
    TurnContext,
)
from callbot.engine.extraction.semantic_failover import SERVICE_FAILURES
from callbot.engine.extraction.semantic_router import _SETTLED
from callbot.engine.extraction.slot_choice import extract_slot_choice
from callbot.engine.extraction.text import clean, is_unaccented, normalize
from callbot.engine.types import Direction, PendingAction

logger = logging.getLogger(__name__)

SLOT_QUESTIONS = frozenset(
    {
        QuestionId.OFFER_SLOTS,
        QuestionId.SLOT_READBACK,
        QuestionId.SLOT_REFUSE_CHOICE,
        QuestionId.ASK_SLOT_PREFERENCE,
    }
)

# Trần thời gian của route chọn khung (owner 12-10, plan §4.11): request Jev 1,5 s; đường dự phòng Luna
# tổng ≤ 4 s từ đầu lượt, chỉ gọi khi còn ≥ 1,5 s. Vẫn dưới 8 s / lượt của contract §4.1.2.
SLOT_JEV_TIMEOUT_S = 1.5
SLOT_TURN_BUDGET_S = 4.0
SLOT_BACKUP_MIN_REMAINING_S = 1.5


class SlotRouteReason(str, Enum):
    # Luật không có đường đi: câu còn nội dung mà luật sẽ trả "em chưa hiểu"
    SLOT_UNRESOLVED = "SLOT_UNRESOLVED"
    # Câu chốt / câu A/B: có tín hiệu có/không nhưng luật hạ UNCLEAR vì còn nội dung khác
    SLOT_HEDGED_ANSWER = "SLOT_HEDGED_ANSWER"
    # Từ chối kèm nội dung không có khung / giờ ("không được, tôi không khám nữa, xóa lịch giúp tôi")
    SLOT_REFUSAL_WITH_CONTENT = "SLOT_REFUSAL_WITH_CONTENT"


# Nhãn được hỏi ở từng câu, option an toàn nhất đứng đầu (Jev nghiêng về option đầu — evidence 10-10).
_ACTS: dict[QuestionId, tuple[str, ...]] = {
    QuestionId.OFFER_SLOTS: (
        "AMBIGUOUS",
        "PICK",
        "TIME",
        "MORE",
        "ANY",
        "REFUSE",
        "KEEP_OLD",
        "CANCEL",
        "OUT_OF_SCOPE",
        "QUESTION",
    ),
    QuestionId.SLOT_READBACK: (
        "AMBIGUOUS",
        "CONFIRM",
        "REFUSE",
        "PICK",
        "TIME",
        "MORE",
        "KEEP_OLD",
        "CANCEL",
        "OUT_OF_SCOPE",
        "QUESTION",
    ),
    QuestionId.SLOT_REFUSE_CHOICE: (
        "AMBIGUOUS",
        "MORE",
        "KEEP_OLD",
        "TIME",
        "PICK",
        "ANY",
        "CANCEL",
        "OUT_OF_SCOPE",
        "QUESTION",
    ),
    QuestionId.ASK_SLOT_PREFERENCE: (
        "AMBIGUOUS",
        "TIME",
        "ANY",
        "KEEP_OLD",
        "CANCEL",
        "OUT_OF_SCOPE",
        "QUESTION",
    ),
}
ALL_ACTS = (
    "AMBIGUOUS",
    "PICK",
    "TIME",
    "MORE",
    "ANY",
    "REFUSE",
    "KEEP_OLD",
    "CONFIRM",
    "CANCEL",
    "OUT_OF_SCOPE",
    "QUESTION",
)

_TRANSFER_CLINICAL = frozenset({ClinicalLevel.EMERGENCY, ClinicalLevel.ADVICE_REQUEST})
_POLICY_INTENTS = frozenset(
    {Intent.REQUEST_HUMAN, Intent.NOT_PATIENT, Intent.OUT_OF_SCOPE, Intent.REPEAT_REQUEST}
)
# Câu chọn khung luật đã đọc chắc trọn câu: không gọi model (C1, mentor qc-rs-02..08)
_SLOT_SETTLED = _SETTLED | frozenset(
    clean(u)
    for u in (
        "khung 1",
        "khung 2",
        "khung một",
        "khung hai",
        "khung khác",
        "giờ khác",
        "thôi không đổi nữa",
        "giữ lịch cũ",
    )
)
# Từ không mang nội dung: câu chỉ gồm các từ này thì luật hỏi lại / A/B là đúng, model không thêm gì
_FILLERS = frozenset(
    clean(w)
    for w in (
        "không",
        "chưa",
        "được",
        "đâu",
        "thôi",
        "đi",
        "ạ",
        "à",
        "ừ",
        "ờ",
        "dạ",
        "vâng",
        "em",
        "chị",
        "anh",
        "ơi",
        "nhé",
        "nha",
        "nhá",
        "nhỉ",
        "mà",
        "thì",
        "rồi",
        "cơ",
        "luôn",
        "vậy",
        "thế",
    )
)


def route_slot_semantic(
    *, question_id: Optional[QuestionId], result: ExtractionResult
) -> Optional[SlotRouteReason]:
    """`None` = giữ chỉ-luật. Gọi sau khi luật của lượt đã chạy xong (plan §4.1).

    Chỉ route câu luật KHÔNG có đường đi chắc: chọn rõ, tiêu chí thời gian, MORE / ANY, loại trừ, bỏ
    đổi lịch, báo bận, "đổi ý", đồng ý ở câu chốt đều giữ luật — nhờ vậy 7 case mentor không bao giờ
    gọi model (C1). Câu không dấu route như câu có dấu; chỉ đổi provider (§4.11).
    """
    if question_id not in SLOT_QUESTIONS:
        return None
    transcript = result.transcript
    text = clean(transcript)
    if not text or text in _SLOT_SETTLED:
        return None
    if result.clinical.value in _TRANSFER_CLINICAL or result.intent.value in _POLICY_INTENTS:
        return None
    if result.intent.value not in (None, Intent.NONE):
        return None
    if is_bare_da(transcript) or is_hesitation_only(transcript):
        return None
    if (
        gives_up_if_unavailable(transcript)
        or gives_up_slot_change(transcript)
        or changes_mind(transcript)
        or rechooses(transcript)
        or mentions_busy(transcript)
    ):
        return None
    choice = result.slot_choice.value
    if choice is not None and (
        choice.kind != "NO_MATCH" or not choice.criteria.empty or choice.excluded_ids
    ):
        return None
    if not _has_content(text):
        return None
    if question_id is QuestionId.OFFER_SLOTS and explicit_slot_pick(transcript):
        # Chỉ có lời đồng ý ("đồng ý đổi", "được, đổi giúp tôi"): luật đọc câu chốt khung sớm nhất (B5)
        return None
    agreement = result.agreement.value if result.agreement.found else None
    if agreement is Agreement.AGREE:
        # Câu chốt đồng ý rõ (qc-rs-02, 04..07): luật ghi, model không được xen vào
        return None
    if agreement is Agreement.REFUSE:
        return SlotRouteReason.SLOT_REFUSAL_WITH_CONTENT
    if agreement is Agreement.UNCLEAR and question_id in (
        QuestionId.SLOT_READBACK,
        QuestionId.SLOT_REFUSE_CHOICE,
    ):
        return SlotRouteReason.SLOT_HEDGED_ANSWER
    return SlotRouteReason.SLOT_UNRESOLVED


def _has_content(text: str) -> bool:
    return any(word not in _FILLERS for word in text.split())


# --- Kết quả provider ------------------------------------------------------------------------


@dataclass(frozen=True)
class SlotSemanticContext:
    """Đúng những gì được phép gửi model (C3): không giờ khung, không giờ lịch hẹn, không hồ sơ."""

    transcript: str
    question_id: QuestionId
    direction: Direction
    route_reason: str
    pending_action: Optional[PendingAction] = None
    page_size: int = 0
    answers_last_question: bool = True

    @property
    def acts(self) -> tuple[str, ...]:
        acts = _ACTS[self.question_id]
        if self.direction == "inbound":
            # Đặt lịch: không có lịch để hủy — lời hủy là việc ngoài kịch bản, như luật hiện có
            acts = tuple(act for act in acts if act != "CANCEL")
        if self.page_size < 1:
            acts = tuple(act for act in acts if act != "PICK")
        return acts

    @property
    def intents(self) -> tuple[str, ...]:
        return ("OUT_OF_SCOPE", "CANCEL") if self.direction == "outbound" else ("OUT_OF_SCOPE",)


@dataclass(frozen=True)
class SlotReading:
    """Kết quả một provider đã đổi về dạng chung. `confident`: nhãn hành động qua ngưỡng của provider
    (Jev: xác suất ≥ `semantic_jev_min_confidence`; Luna không có xác suất nên luôn True — các cổng
    không dựa xác suất ở `resolve_slot_act` vẫn áp)."""

    act: str
    confident: bool
    decides_now: bool
    pick: Optional[int] = None
    wanted_span: Optional[str] = None
    intent: Optional[str] = None
    clinical: Optional[str] = None
    clinical_span: Optional[str] = None


class SlotSemanticExtractor(Protocol):
    last_status: Optional[str]

    def analyze(self, context: SlotSemanticContext) -> Optional[SlotReading]: ...


def ground_slot_reading(
    reading: SlotReading, context: SlotSemanticContext
) -> Optional[SlotReading]:
    """Kiểm sau model (plan §4.4). `None` = không dùng được gì, lượt giữ kết quả luật (C5)."""
    if reading.act not in context.acts:
        return None
    if reading.intent is not None and reading.intent not in context.intents:
        return None
    if reading.act == "PICK" and (
        reading.pick is None or not 1 <= reading.pick <= context.page_size
    ):
        return None
    wanted = None
    if reading.act == "TIME":
        wanted = grounded(reading.wanted_span, context.transcript)
        if wanted is None:
            return None
    clinical_span = None
    if reading.clinical is not None:
        if reading.clinical not in {level.value for level in ClinicalLevel}:
            return None
        clinical_span = grounded(reading.clinical_span, context.transcript)
        if clinical_span is None:
            return None
    return SlotReading(
        act=reading.act,
        confident=reading.confident,
        decides_now=reading.decides_now,
        pick=reading.pick if reading.act == "PICK" else None,
        wanted_span=wanted,
        intent=reading.intent,
        clinical=reading.clinical,
        clinical_span=clinical_span,
    )


def grounded(span: Optional[str], transcript: str) -> Optional[str]:
    """Span là một đoạn liền mạch có thật của transcript (so trên bản chuẩn hóa còn dấu câu)."""
    if not span or any(marker in span for marker in (" + ", "...", "…")):
        return None
    candidate = normalize(span)
    return candidate if candidate and candidate in normalize(transcript) else None


def resolve_slot_act(reading: SlotReading, context: SlotSemanticContext) -> SlotAct:
    """Ma trận ưu tiên (plan §4.9): nhãn hành động chỉ đi khi chắc; nhãn kéo về hỏi lại không cần chắc.

    `KEEP_OLD` của model luôn thành câu A/B (`KEEP_OLD_UNSURE`): kết thúc đổi lịch chỉ khi khách nói
    rõ bằng cụm luật nhận ra — và câu như vậy luật đã xử lý, không route tới đây (§1.1.5 không đoán).
    """
    act = reading.act
    if reading.clinical in (ClinicalLevel.EMERGENCY.value, ClinicalLevel.ADVICE_REQUEST.value):
        return SlotAct.UNCLEAR  # Policy chuyển CLINICAL_QUESTION theo `clinical`
    if reading.intent == "OUT_OF_SCOPE" and act in ("OUT_OF_SCOPE", "QUESTION"):
        return SlotAct.OUT_OF_SCOPE
    if context.direction == "outbound" and (
        reading.intent == "CANCEL"
        or (act == "CANCEL" and reading.confident and reading.decides_now)
    ):
        return SlotAct.CANCEL
    if act == "KEEP_OLD":
        return SlotAct.KEEP_OLD_UNSURE
    if act == "REFUSE":
        return SlotAct.REFUSE
    if act == "CONFIRM":
        return (
            SlotAct.CONFIRM if context.question_id is QuestionId.SLOT_READBACK else SlotAct.UNCLEAR
        )
    if act in ("PICK", "TIME", "MORE", "ANY") and reading.confident and reading.decides_now:
        return SlotAct(act)
    return SlotAct.UNCLEAR


# --- Chọn provider (plan §4.11) ----------------------------------------------------------------


class SlotSemanticReader:
    """Jev chính; Luna khi câu không dấu (bỏ qua Jev) hoặc khi Jev lỗi dịch vụ và lượt còn đủ giờ.

    Jev đã trả lời (kể cả AMBIGUOUS hay bị loại khi kiểm) là kết quả của lượt: gọi thêm Luna lúc đó
    là hỏi tới khi vừa ý, không phải dự phòng.
    """

    def __init__(
        self,
        primary: Optional[Any],
        backup: Optional[Any],
        *,
        budget_s: float = SLOT_TURN_BUDGET_S,
        min_backup_s: float = SLOT_BACKUP_MIN_REMAINING_S,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if primary is None and backup is None:
            raise ValueError("cần ít nhất một provider")
        self.primary = primary
        self.backup = backup
        self.budget_s = budget_s
        self._min_backup_s = min_backup_s
        self._clock = clock
        # Lượt gần nhất: provider đã trả kết quả và lý do (cho trace / eval), không có nội dung câu
        self.last_provider: Optional[str] = None
        self.last_reason: Optional[str] = None
        self.last_status: Optional[str] = None

    @property
    def _gateway(self) -> Any:
        return (self.primary or self.backup)._gateway

    def analyze(self, context: SlotSemanticContext) -> Optional[SlotReading]:
        self.last_provider = self.last_reason = None
        unaccented = is_unaccented(clean(context.transcript))
        if self.backup is not None and (unaccented or self.primary is None):
            record_model(self.backup._gateway.model, self.backup._gateway.provider_name)
            return self._run(
                self.backup, "luna", "unaccented" if unaccented else "primary_missing", context
            )
        assert self.primary is not None
        started = self._clock()
        try:
            reading = self.primary.analyze(context)
            failed = self.primary.last_status in SERVICE_FAILURES
        except Exception:  # noqa: BLE001 — lỗi provider chính không được thành lỗi lượt
            reading, failed = None, True
        self.last_status = self.primary.last_status
        if not failed:
            self.last_provider = "jev"
            return reading
        remaining = self.budget_s - (self._clock() - started)
        if self.backup is None or remaining < self._min_backup_s:
            logger.info(
                "Slot semantic failover: skipped",
                extra={"slot_failover": "skipped", "slot_remaining_s": round(remaining, 3)},
            )
            return None
        hand_over_model(self.backup._gateway.model, self.backup._gateway.provider_name)
        return self._run(self.backup, "luna", "failover", context)

    def _run(
        self, adapter: Any, name: str, reason: str, context: SlotSemanticContext
    ) -> Optional[SlotReading]:
        self.last_provider, self.last_reason = name, reason
        try:
            reading = adapter.analyze(context)
        finally:
            self.last_status = adapter.last_status
        return reading


# --- Hợp nhất vào kết quả IE (plan §4.5) --------------------------------------------------------

SLOT_ROUTE_VALUES = frozenset(reason.value for reason in SlotRouteReason)


def slot_semantic_context(
    ctx: TurnContext, result: ExtractionResult, route: SlotRouteReason
) -> SlotSemanticContext:
    assert ctx.question_id is not None
    return SlotSemanticContext(
        transcript=result.transcript,
        question_id=ctx.question_id,
        direction=ctx.direction,
        route_reason=route.value,
        pending_action=ctx.pending_action,
        page_size=len(ctx.presented_slot_ids),
        answers_last_question=ctx.question_turn is None or ctx.question_turn == ctx.turn - 1,
    )


def merge_slot_semantic(
    result: ExtractionResult,
    reading: Optional[SlotReading],
    context: SlotSemanticContext,
    ctx: TurnContext,
) -> ExtractionResult:
    """Lượt có kết quả model: thay cả bộ trường chọn khung (không giữ kết quả luật để nhánh luật đọc
    lại), mọi giá trị mang `Provenance.FALLBACK`, không bao giờ còn AGREE (C2). `slot_id` chỉ do code
    dò trên khung đã đọc / `GET /slots`, không bao giờ do model chọn.

    `reading is None` (model lỗi / bị loại): chỉ đánh dấu route; `extract()` giữ kết quả luật (C5).
    """
    base = replace(result, model_route=context.route_reason)
    if reading is None:
        return base
    act = resolve_slot_act(reading, context)
    whole = normalize(result.transcript)
    agreement = result.agreement
    if agreement.value is Agreement.AGREE:
        agreement = Field(Agreement.UNCLEAR, Provenance.FALLBACK, whole)
    intent = result.intent
    if act is SlotAct.OUT_OF_SCOPE:
        intent = Field(Intent.OUT_OF_SCOPE, Provenance.FALLBACK, whole)
    elif act is SlotAct.CANCEL:
        intent = Field(Intent.CANCEL, Provenance.FALLBACK, whole)
    clinical = result.clinical
    if reading.clinical is not None and reading.clinical_span is not None:
        clinical = Field(
            ClinicalLevel(reading.clinical), Provenance.FALLBACK, reading.clinical_span
        )
    slot_choice: Field[SlotChoice] = Field.nothing()
    slot_request = result.slot_request
    if act is SlotAct.PICK:
        presented = list(ctx.presented_slot_ids)
        if reading.pick is not None and reading.pick <= len(presented):
            picked = presented[reading.pick - 1]
            slot_choice = Field(
                SlotChoice("MATCH", (picked,), SlotCriteria(ordinal=reading.pick)),
                Provenance.FALLBACK,
                whole,
            )
        else:
            act = SlotAct.UNCLEAR
    elif act is SlotAct.TIME:
        assert reading.wanted_span is not None
        read = extract_slot_choice(reading.wanted_span, ctx.slots, ctx.presented_slot_ids, ctx.now)
        choice = read.value
        if choice is None or (choice.kind == "NO_MATCH" and choice.criteria.empty):
            act = SlotAct.UNCLEAR
        else:
            slot_choice = Field(choice, Provenance.FALLBACK, reading.wanted_span)
            slot_request = reading.wanted_span
    return replace(
        base,
        slot_act=act,
        agreement=agreement,
        intent=intent,
        clinical=clinical,
        slot_choice=slot_choice,
        slot_request=slot_request,
    )
