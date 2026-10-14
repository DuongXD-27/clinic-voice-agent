"""Đánh giá chọn khung khi đổi lịch / đặt lịch (T-10, plan §3.8.3).

    python scripts/reschedule_eval.py --baseline                 # chỉ luật, KHÔNG gọi API
    python scripts/reschedule_eval.py --route-only               # luật + model giả trả None: đếm lượt gọi model
    python scripts/reschedule_eval.py --semantic --repeats 3     # gọi model thật, cần OPENAI_API_KEY
    python scripts/eval_compare.py result/<dd-mm-yyyy>/reschedule/<A> result/<dd-mm-yyyy>/reschedule/<B>

Chạy tay, không nằm trong `pytest`. Mỗi câu chạy qua **Orchestrator thật + `FakeClinicAPI.mentor_mock()`**
(dữ liệu như Clinic Mock deploy: Ngô Huy Hoàn `apt_00418` 8 giờ sáng 15/10, 11 khung trống 14–21/10),
đồng hồ cố định **thứ Ba 29/09/2026 10:00** để ngày tương đối có đáp án cố định. Ngữ cảnh dựng theo
(`direction`, `question_id`, `page_size`) — bảng `SETUP`:

    outbound OFFER_SLOTS 2          "Tôi muốn đổi lịch"            -> trang [14/10 15:00, 15/10 10:30]
    outbound OFFER_SLOTS 2-trang2   + "khung khác"                  -> trang [15/10 15:30, 16/10 9:00]
    outbound OFFER_SLOTS 2-mo-ho    + "khung khác" + "3 giờ chiều"  -> trang mơ hồ [14/10 15:00, 21/10 15:00]
    outbound SLOT_READBACK 1        "đổi sang ngày 14 tháng 10"    -> câu có/không khung duy nhất 14/10 15:00
    outbound SLOT_READBACK 2        + "khung nào cũng được"         -> câu chốt 14/10 15:00, trang 2 khung
    outbound SLOT_REFUSE_CHOICE 2   + "không"                       -> "nghe khung khác hay giữ lịch cũ"
    outbound ASK_SLOT_PREFERENCE 1  14/10 + "không"                 -> hết khung, hỏi ngày khác (vòng 1)
    inbound  OFFER_SLOTS / SLOT_READBACK 2: như trên với "Tôi muốn đặt lịch" (BOOK, SĐT 0967769004)

Nhãn hành vi (`expect`, `observed`) — `_observe` xét theo thứ tự dưới đây:

    WRITE           Ghi RESCHEDULED / BOOKED.
    TRANSFER:<lý do> Chuyển máy, kèm transfer_reason.
    SWITCH:CANCEL   Rời nhánh đổi lịch sang hỏi xác nhận hủy (chưa ghi).
    KEEP_OLD        Bỏ đặt lịch (inbound): không còn hành động chờ. Bỏ đổi lịch (outbound) thì giữ lịch cũ và
                    chuyển máy PATIENT_REQUEST (qc-rs-08), nhãn TRANSFER:PATIENT_REQUEST.
    BACK_TO_APPOINTMENT  Outbound, "tôi đổi ý": bỏ đổi lịch, không ghi, quay lại câu hỏi lịch cũ (B15).
    NOT_UNDERSTOOD  "Dạ, em chưa hiểu ý anh chị..." — tính §1.1.5.
    ASK_DATE        Hỏi lại ngày kèm lý do (đã qua / không tồn tại / quá rộng / trùng hôm nay) — R-30.
    REFUSE_CHOICE   Hỏi "nghe khung khác / đổi ngày khác hay giữ lịch cũ" — không đoán (Q-4).
    ASK_DAY         Hỏi "muốn đổi sang ngày nào" (chưa có ngày).
    NEW_TIME        Tra theo thời gian khách vừa nêu (vòng mới, báo kín, hoặc "chưa thấy khung giờ đó").
                    Nhãn mong đợi ghi kèm ngày / buổi: `NEW_TIME:19/10`, `NEW_TIME:20/10 chiều`,
                    `NEW_TIME:12-18/10`, `NEW_TIME:01/10|02/10`, `NEW_TIME:sáng`. Báo kín thì so ngày kín;
                    còn lại mọi khung đọc ra phải thuộc ngày / buổi đó. Đọc câu chốt một khung ngoài trang
                    khớp thời gian đó (PICK_SLOT) cũng tính.
    ANY             Đọc lại từ khung sớm nhất, không tiêu chí ("ngày nào cũng được").
    PICK:<n>        Đọc câu chốt khung thứ n của trang vừa đọc. Đổi lịch chốt luôn khi chọn khung (ghi
                    ngay, không đọc lại): ghi đúng khung thứ n từ câu đọc khung cũng là PICK:<n>.
    PICK_SLOT       Đọc câu chốt (hoặc, khi đổi lịch, ghi) một khung không nằm trong trang vừa đọc.
    MORE            Đọc khung chưa đọc (trang kế), không lặp khung vừa đọc / vừa từ chối.
    REREAD_YESNO    Hỏi lại câu có/không của đúng khung đang chốt, không ghi.
    ASK_WHICH       Trang mơ hồ không thu hẹp được: hỏi lại chọn khung nào trong đúng trang đó (B1).
    REREAD_PAGE     Đọc lại đúng trang vừa đọc (kể cả từ câu chốt quay lại trang, "chọn lại" — B16).
    AMBIGUOUS       Đọc một trang khác chồng lên trang cũ (khớp nhiều khung).
    OTHER           Không khớp nhãn nào.

Dấu `|` trong `expect`: chấp nhận nhiều hành vi với câu mơ hồ thật. `needs_inference=yes`: ý phải suy
ra từ hoàn cảnh; chỉ luật thì được phép sai, nhưng không được ghi. Báo cáo tách độ đúng `holdout`
theo câu luật quyết được / cần suy nghĩa, theo nhóm; đếm GHI SAI (ghi khi nhãn không phải WRITE) và
GHI NHẦM KHUNG. Exit 1 nếu có ca không đạt (`--safety-only`: chỉ khi ghi sai / nhầm khung).

Kết quả ghi ra `result/<dd-mm-yyyy>/reschedule/<label>/`. Transcript là dữ liệu tổng hợp, không có PII.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fakeredis  # noqa: E402

# Dùng chung bộ đếm model và cách đo với eval hủy; import cũng đặt sys.path cho src.
from cancel_eval import Counting, RecordingGateway, _latency, result_dir  # noqa: E402

from callbot.engine import (  # noqa: E402
    CallerInput,
    CallStart,
    EngineSettings,
    _semantic_extractor,
    _slot_semantic_reader,
    create_orchestrator,
)
from callbot.engine.dialogue import templates as t  # noqa: E402
from callbot.engine.extraction.schema import VN_TZ, QuestionId  # noqa: E402
from callbot.engine.extraction.semantic import SemanticContext, SemanticOutcome  # noqa: E402
from callbot.engine.session import CallContext, RedisSessionStore  # noqa: E402
from callbot.engine.session.fsm import DIRECT_PICK_QUESTION_FOR  # noqa: E402
from clinic_mock_sim import FakeClinicAPI  # noqa: E402

CASES = ROOT / "eval" / "reschedule" / "cases.csv"
# Câu hỏi mà chọn rõ một khung vừa đọc là ghi đổi lịch luôn (R-29 v2.1), không đọc lại câu chốt
SLOT_PICK_QUESTIONS = frozenset(DIRECT_PICK_QUESTION_FOR.values())
NOW = datetime(2026, 9, 29, 10, 0, tzinfo=VN_TZ)  # thứ Ba
APPOINTMENT = "apt_00418"
PHONE = "0967769004"
VERIFIED = ["Ngô Huy Hoàn", "16 tháng 5 năm 2004"]
SETUP: dict[tuple[str, str, str], list[str]] = {
    ("outbound", "OFFER_SLOTS", "2"): ["Tôi muốn đổi lịch"],
    ("outbound", "OFFER_SLOTS", "2-trang2"): ["Tôi muốn đổi lịch", "khung khác"],
    ("outbound", "OFFER_SLOTS", "2-mo-ho"): ["Tôi muốn đổi lịch", "khung khác", "3 giờ chiều"],
    ("outbound", "SLOT_READBACK", "1"): ["đổi sang ngày 14 tháng 10"],
    ("outbound", "SLOT_READBACK", "2"): ["Tôi muốn đổi lịch", "khung nào cũng được"],
    ("outbound", "SLOT_REFUSE_CHOICE", "2"): ["Tôi muốn đổi lịch", "không"],
    ("outbound", "ASK_SLOT_PREFERENCE", "1"): ["đổi sang ngày 14 tháng 10", "không"],
    ("inbound", "OFFER_SLOTS", "2"): ["Tôi muốn đặt lịch"],
    ("inbound", "SLOT_READBACK", "2"): ["Tôi muốn đặt lịch", "khung 1"],
}
# Câu hỏi lại ngày của `t.ask_date_again` (R-30), so trên chữ thường: câu thoại chuẩn hoá 08/10 viết hoa
# "Hôm nay là", hỏi "ngày nào cụ thể"
_DATE_REASK = ("đã qua rồi", "không có trong lịch", "cụ thể", "hôm nay là")
_FULL_DAY = re.compile(r"ngày (\d{1,2}) tháng (\d{1,2}) đã kín lịch")
_PERIODS = {"sáng": range(0, 12), "chiều": range(12, 18), "tối": range(18, 24)}

_SERVER = fakeredis.FakeServer()


@dataclass
class Capturing(Counting):
    """Như `Counting`, giữ thêm kết quả model của lượt đang chấm để ghi vào báo cáo."""

    outcome: Optional[SemanticOutcome] = None

    def analyze(self, context: SemanticContext) -> Optional[SemanticOutcome]:
        outcome = super().analyze(context)
        if self.active:
            self.outcome = outcome
        return outcome


@dataclass
class SlotCounting:
    """Bọc tầng chọn khung (plan Jev §4.11): ghi route, provider, trạng thái, độ trễ của lượt được chấm."""

    inner: Any
    active: bool = False
    last: Optional[dict[str, Any]] = None

    @property
    def budget_s(self) -> float:
        return self.inner.budget_s

    @property
    def _gateway(self) -> Any:
        return getattr(self.inner, "_gateway", None)

    def analyze(self, context: Any) -> Any:
        started = time.perf_counter()
        try:
            reading = self.inner.analyze(context)
            status = getattr(self.inner, "last_status", None) or ("accepted" if reading else "none")
        except Exception:  # noqa: BLE001 — adapter thật không ném; vẫn ghi lại
            reading, status = None, "exception"
        if self.active:
            self.last = {
                "slot_route": context.route_reason,
                "slot_provider": getattr(self.inner, "last_provider", None) or "",
                "slot_reason": getattr(self.inner, "last_reason", None) or "",
                "slot_status": status,
                "slot_act": reading.act if reading is not None else "",
                "slot_ms": round((time.perf_counter() - started) * 1000, 1),
                # Jev: xác suất từng câu hỏi (calibration); Luna không có
                "slot_probs": json.dumps(
                    getattr(getattr(self.inner, "primary", None), "last_probabilities", None)
                    if getattr(self.inner, "last_provider", None) == "jev"
                    else None
                ),
            }
        return reading


class NullSlot:
    """`--route-only`: tầng chọn khung không trả gì — chỉ đếm route."""

    budget_s = 4.0
    last_status = "none"

    def analyze(self, context: Any) -> None:
        return None


class NullSemantic:
    """`--route-only`: model không trả gì — đo router và nhánh dự phòng mà không gọi API."""

    def analyze(self, context: SemanticContext) -> None:
        return None


def _store() -> RedisSessionStore:
    return RedisSessionStore(
        fakeredis.FakeRedis(server=_SERVER, decode_responses=True), key_prefix="reschedule-eval"
    )


def _context(bot, call_id: str) -> Optional[CallContext]:
    session = bot.sessions.store.get_session(call_id)
    return CallContext.from_dict(session.context) if session and session.context else None


# --- Quan sát -----------------------------------------------------------------------------------


@dataclass
class Observed:
    label: str
    dates: tuple[str, ...] = ()  # dd/mm của các khung đọc ra / khung đang chốt
    hours: tuple[int, ...] = ()
    full_day: str = ""  # dd/mm ngày bot báo "đã kín lịch"


def _slot_times(ctx: CallContext, slot_ids: list[str]) -> tuple[tuple[str, ...], tuple[int, ...]]:
    moments = []
    for slot_id in slot_ids:
        slot = ctx.find_slot(slot_id)
        if slot is not None:
            moments.append(datetime.fromisoformat(slot["starts_at"]).astimezone(VN_TZ))
    return tuple(f"{m.day:02d}/{m.month:02d}" for m in moments), tuple(m.hour for m in moments)


def _observe(action, before: CallContext, after: Optional[CallContext], clinic: FakeClinicAPI):
    rescheduled = [w[2].get("new_slot_id") for w in clinic.writes if w[1] == "RESCHEDULED"]
    was = before.question.question_id if before.question else None
    if rescheduled and was in SLOT_PICK_QUESTIONS:
        # Đổi lịch chốt luôn khi chọn khung vừa đọc: chấm theo khung được ghi, như câu chốt khung đó
        dates, hours = _slot_times(before, rescheduled[:1])
        if rescheduled[0] in before.presented_slot_ids:
            index = before.presented_slot_ids.index(rescheduled[0]) + 1
            return Observed(f"PICK:{index}", dates, hours)
        return Observed("PICK_SLOT", dates, hours)
    if any(status in ("RESCHEDULED", "BOOKED") for _, status, _ in clinic.writes):
        return Observed("WRITE")
    if action.outcome == "TRANSFERRED":
        return Observed(f"TRANSFER:{action.transfer_reason}")
    if after is None or action.ended:
        return Observed("ENDED")
    if after.pending_action == "CANCEL":
        return Observed("SWITCH:CANCEL")
    if after.pending_action is None:
        if after.question is not None and after.question.question_id is QuestionId.CONFIRM_READBACK:
            return Observed("BACK_TO_APPOINTMENT")
        return Observed("KEEP_OLD")
    utterance = action.utterance
    if utterance in t.static_choices(t.NOT_UNDERSTOOD):
        return Observed("NOT_UNDERSTOOD")
    asked = after.question.question_id if after.question else None
    if asked is QuestionId.ASK_SLOT_PREFERENCE:
        if any(marker in utterance.lower() for marker in _DATE_REASK):
            return Observed("ASK_DATE")
        if utterance in t.SLOT_EXHAUSTED.values():
            return Observed("REFUSE_CHOICE")
        return Observed("ASK_DAY")
    if asked is QuestionId.SLOT_REFUSE_CHOICE:
        return Observed("REFUSE_CHOICE")

    shown = list(after.presented_slot_ids)
    if asked is QuestionId.SLOT_READBACK and after.selected_slot_id:
        shown = [after.selected_slot_id]
    dates, hours = _slot_times(after, shown)
    full = _FULL_DAY.search(utterance)
    full_day = f"{int(full.group(1)):02d}/{int(full.group(2)):02d}" if full else ""
    new_request = (
        after.slot_round > before.slot_round or bool(full) or utterance.startswith(t.SLOT_NO_MATCH)
    )
    if new_request:
        label = (
            "NEW_TIME"
            if after.slot_request or full or utterance.startswith(t.SLOT_NO_MATCH)
            else "ANY"
        )
        return Observed(label, dates, hours, full_day)

    if asked is QuestionId.SLOT_READBACK:
        selected = after.selected_slot_id
        if was is QuestionId.SLOT_READBACK and selected == before.selected_slot_id:
            return Observed("REREAD_YESNO")
        # Câu chốt khung (mọi biến thể của `t.slot_readback`), không phải câu có/không khung duy nhất
        if selected in before.presented_slot_ids and utterance.endswith("Anh chị đồng ý không ạ?"):
            return Observed(f"PICK:{before.presented_slot_ids.index(selected) + 1}", dates, hours)
        if "còn trống" in utterance:  # đọc khung duy nhất còn lại, chưa đọc trước đó
            return Observed("MORE", dates, hours)
        return Observed("PICK_SLOT", dates, hours)
    if asked is QuestionId.OFFER_SLOTS:
        previous = list(before.presented_slot_ids)
        if was is QuestionId.SLOT_READBACK and shown == previous:
            # Từ câu chốt quay lại đúng trang khách đang chọn ("tôi muốn chọn lại", B16)
            return Observed("REREAD_PAGE", dates, hours)
        if was is QuestionId.SLOT_READBACK:
            return Observed(
                "MORE" if before.selected_slot_id not in shown else "OTHER", dates, hours
            )
        if shown == previous and utterance.startswith(t.SLOT_AMBIGUOUS_AGAIN + "anh chị chọn"):
            return Observed("ASK_WHICH", dates, hours)
        if shown == previous:
            return Observed("REREAD_PAGE", dates, hours)
        if set(shown) & set(previous):
            return Observed("AMBIGUOUS", dates, hours)
        return Observed("MORE", dates, hours)
    return Observed("OTHER", dates, hours)


def _in_spec(day: str, spec: str) -> bool:
    """`19/10`, `12-18/10`, `01/10|02/10`."""
    for option in spec.split("|"):
        if "-" in option:
            first, rest = option.split("-", 1)
            last_day, month = rest.split("/")
            low, high = f"{int(first):02d}/{month}", f"{int(last_day):02d}/{month}"
            if day[3:] == month and low <= day <= high:
                return True
        elif day == option:
            return True
    return False


def _matches(expected: str, seen: Observed) -> bool:
    if not expected.startswith("NEW_TIME"):
        return seen.label == expected
    if seen.label not in ("NEW_TIME", "PICK_SLOT"):
        return False
    words = expected.split(":", 1)[1].split()
    period = next((w for w in words if w in _PERIODS), None)
    days = next((w for w in words if w not in _PERIODS), None)
    if seen.full_day:
        return days is None or _in_spec(seen.full_day, days)
    if not seen.dates:
        return False
    if days is not None and not all(_in_spec(day, days) for day in seen.dates):
        return False
    return period is None or all(hour in _PERIODS[period] for hour in seen.hours)


def _accepted(expect: str, seen: Observed) -> bool:
    # "|" giữa các nhãn; riêng NEW_TIME dùng "|" giữa các ngày trong cùng một nhãn
    if expect.startswith("NEW_TIME"):
        return _matches(expect, seen)
    return any(_matches(option, seen) for option in expect.split("|"))


# --- Chạy một câu --------------------------------------------------------------------------------


def _run_case(
    row: dict[str, str],
    call_id: str,
    semantic: Optional[Capturing],
    repeat: int,
    slot: Optional[SlotCounting] = None,
) -> dict[str, Any]:
    clinic = FakeClinicAPI.mentor_mock()
    # Bước xác minh chỉ là dựng ngữ cảnh: không gọi model điền tên (luật xác minh được bệnh nhân demo)
    bot = create_orchestrator(
        clinic, settings=EngineSettings(name_fallback_provider="none"), store=_store()
    )
    bot.sessions._clock = lambda: NOW
    bot._extractor._semantic = semantic
    bot._extractor._slot_semantic = slot
    if row["direction"] == "inbound":
        start = CallStart(call_id=call_id, direction="inbound", caller_number=PHONE)
    else:
        start = CallStart(call_id=call_id, direction="outbound", appointment_id=APPOINTMENT)
    bot.start_call(start)
    lines = [*VERIFIED, *SETUP[(row["direction"], row["question_id"], row["page_size"])]]
    for turn, line in enumerate(lines, start=1):
        bot.handle_turn(call_id, CallerInput(turn=turn, text=line))
    before = _context(bot, call_id)
    assert before is not None and before.question is not None, row
    assert before.question.question_id.value == row["question_id"], (row, before.question)

    if semantic is not None:
        semantic.last, semantic.outcome, semantic.active = None, None, True
    if slot is not None:
        slot.last, slot.active = None, True
    started = time.perf_counter()
    try:
        action = bot.handle_turn(call_id, CallerInput(turn=len(lines) + 1, text=row["transcript"]))
    finally:
        if semantic is not None:
            semantic.active = False
        if slot is not None:
            slot.active = False
    elapsed_ms = (time.perf_counter() - started) * 1000

    after = _context(bot, call_id)
    seen = _observe(action, before, after, clinic)
    behaviour_ok = _accepted(row["expect"], seen)
    slot_writes = [w for w in clinic.writes if w[1] in ("RESCHEDULED", "BOOKED")]
    # Đổi lịch chốt luôn khi chọn khung vừa đọc: ghi đúng khung mong đợi (PICK đúng) là an toàn
    pick_write = (
        before.question.question_id in SLOT_PICK_QUESTIONS
        and behaviour_ok
        and seen.label.startswith("PICK")
    )
    wrong_slot = not pick_write and any(
        (body.get("new_slot_id") or body.get("slot_id")) != before.selected_slot_id
        for _, _, body in slot_writes
    )
    unsafe = bool(slot_writes) and not pick_write and "WRITE" not in row["expect"].split("|")
    semantic_status, semantic_ms = semantic.last if semantic and semantic.last else ("", None)
    outcome = semantic.outcome if semantic else None
    return {
        "repeat": repeat,
        "id": row["id"],
        "split": row["split"],
        "group": row["group"],
        "direction": row["direction"],
        "question_id": row["question_id"],
        "transcript": row["transcript"],
        "needs_inference": row.get("needs_inference") == "yes",
        "expect": row["expect"],
        "observed": seen.label,
        "observed_dates": " ".join(seen.dates),
        "observed_full_day": seen.full_day,
        "transfer_reason": action.transfer_reason or "",
        "utterance": action.utterance,
        "behaviour_ok": behaviour_ok,
        "unsafe_write": unsafe,
        "wrong_slot_write": wrong_slot,
        "passed": behaviour_ok and not unsafe and not wrong_slot,
        "routed": bool(semantic and semantic.last),
        "semantic_status": semantic_status,
        "semantic_kind": outcome.reply_kind.value if outcome else "",
        "semantic_ms": round(semantic_ms, 1) if semantic_ms is not None else "",
        **(
            slot.last
            if slot is not None and slot.last
            else dict.fromkeys(
                (
                    "slot_route",
                    "slot_provider",
                    "slot_reason",
                    "slot_status",
                    "slot_act",
                    "slot_ms",
                    "slot_probs",
                ),
                "",
            )
        ),
        "elapsed_ms": round(elapsed_ms, 1),
    }


# --- Báo cáo -------------------------------------------------------------------------------------


def _summarise(rows: list[dict[str, Any]], counter: Optional[Counting]) -> dict[str, Any]:
    holdout = [r for r in rows if r["split"] == "holdout"]
    rule = [r for r in holdout if not r["needs_inference"]]
    inference = [r for r in holdout if r["needs_inference"]]
    by_group: dict[str, dict[str, int]] = {}
    for row in holdout:
        bucket = by_group.setdefault(row["group"], {"total": 0, "ok": 0, "routed": 0})
        bucket["total"] += 1
        bucket["ok"] += int(row["passed"])
        bucket["routed"] += int(row["routed"])
    return {
        "cases": len(rows),
        "failed_cases": sum(not r["passed"] for r in rows),
        "holdout_cases": len(holdout),
        "holdout_passed": sum(r["passed"] for r in holdout),
        "holdout_accuracy": round(sum(r["passed"] for r in holdout) / max(1, len(holdout)), 4),
        "rule_cases": len(rule),
        "rule_passed": sum(r["passed"] for r in rule),
        "inference_cases": len(inference),
        "inference_passed": sum(r["passed"] for r in inference),
        "unsafe_writes": sum(r["unsafe_write"] for r in rows),
        "wrong_slot_writes": sum(r["wrong_slot_write"] for r in rows),
        "not_understood": sum(r["observed"] == "NOT_UNDERSTOOD" for r in holdout),
        "by_group": {name: dict(bucket) for name, bucket in sorted(by_group.items())},
        "model_calls": counter.routed if counter else 0,
        "slot_calls": sum(bool(r["slot_route"]) for r in rows),
        "slot_routes": dict(Counter(r["slot_route"] for r in rows if r["slot_route"])),
        "slot_providers": dict(
            Counter(f"{r['slot_provider']}:{r['slot_reason']}" for r in rows if r["slot_route"])
        ),
        "slot_statuses": dict(Counter(r["slot_status"] for r in rows if r["slot_route"])),
        "slot_latency_ms": _latency([r["slot_ms"] for r in rows if r["slot_ms"] != ""]),
        "model_statuses": dict(sorted(counter.statuses.items())) if counter else {},
        "turn_latency_ms": _latency([r["elapsed_ms"] for r in rows]),
        "failures": [
            {
                k: r[k]
                for k in (
                    "id",
                    "group",
                    "question_id",
                    "transcript",
                    "needs_inference",
                    "expect",
                    "observed",
                    "observed_dates",
                    "observed_full_day",
                    "utterance",
                )
            }
            for r in rows
            if not r["passed"]
        ],
    }


def _mark(row: dict[str, Any]) -> str:
    if row["unsafe_write"] or row["wrong_slot_write"]:
        return "W"
    return "." if row["passed"] else "F"


def _run_line(attempt: int, repeats: int, s: dict[str, Any]) -> str:
    return (
        f"run {attempt}/{repeats}: holdout {s['holdout_passed']}/{s['holdout_cases']}"
        f" ({s['holdout_accuracy']:.1%})"
        f" [rule {s['rule_passed']}/{s['rule_cases']}, inference {s['inference_passed']}/{s['inference_cases']}]"
        f" · unsafe writes {s['unsafe_writes']} · wrong-slot writes {s['wrong_slot_writes']}"
        f" · not understood {s['not_understood']} · model calls {s['model_calls']}"
        f" · slot calls {s['slot_calls']} {s['slot_providers'] or ''}"
    )


def _print_failures(rows: list[dict[str, Any]]) -> None:
    failed = [r for r in rows if not r["passed"]]
    if not failed:
        print("No failed cases.")
        return
    print(f"Failed cases ({len(failed)}):")
    for r in failed:
        tag = "UNSAFE WRITE" if r["unsafe_write"] or r["wrong_slot_write"] else "FAIL"
        extra = (
            f" [{r['observed_full_day'] or r['observed_dates']}]"
            if r["observed_dates"] or r["observed_full_day"]
            else ""
        )
        split = "" if r["split"] == "holdout" else " (prompt)"
        print(
            f"  {tag} {r['id']}{split} {r['question_id']} | {r['transcript']} -> {r['observed']}{extra}"
            f" (expected {r['expect']})"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reschedule / booking slot-choice eval. Results go to"
        " result/<dd-mm-yyyy>/reschedule/<label>/."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--baseline", action="store_true", help="rules only, no API calls")
    mode.add_argument(
        "--route-only", action="store_true", help="rules + a model stub returning None"
    )
    mode.add_argument("--semantic", action="store_true", help="rules + real model")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument(
        "--cases", type=Path, default=CASES, help="CSV ca chấm (mặc định eval/reschedule/cases.csv)"
    )
    parser.add_argument("--label", default=None, help="result folder name (default: mode)")
    parser.add_argument(
        "--no-slot-layer",
        action="store_true",
        help="không bật tầng model chọn khung (so sánh với tầng ngữ nghĩa cũ)",
    )
    parser.add_argument(
        "--safety-only", action="store_true", help="exit 1 only on unsafe / wrong-slot writes"
    )
    args = parser.parse_args()

    mode_name = "semantic" if args.semantic else "route-only" if args.route_only else "baseline"
    label = args.label or mode_name
    extractor: Any = None
    gateway = None
    if args.semantic:
        extractor = _semantic_extractor(EngineSettings(semantic_fallback_enabled=True))
        if extractor is None:
            print("Cannot build the semantic layer: check .env settings.", file=sys.stderr)
            return 2
        gateway = RecordingGateway(extractor._gateway)
        extractor._gateway = gateway
    elif args.route_only:
        extractor = NullSemantic()
    slot_inner: Any = None
    if args.semantic and not args.no_slot_layer:
        slot_inner = _slot_semantic_reader(EngineSettings(slot_semantic_enabled=True))
        if slot_inner is None:
            print("Cannot build the slot layer: check TYPESAFE / OpenAI keys.", file=sys.stderr)
            return 2
    elif args.route_only and not args.no_slot_layer:
        slot_inner = NullSlot()

    with args.cases.open(encoding="utf-8") as fh:
        cases = list(csv.DictReader(fh))
    scored = sum(1 for row in cases if row["split"] == "holdout")
    print(
        f"{mode_name} · {len(cases)} cases × {args.repeats} run(s) · scored {scored} holdout"
        f" · today {NOW:%a %d/%m/%Y} · label '{label}'"
    )
    print("legend: . pass · F fail · W UNSAFE / WRONG-SLOT WRITE")
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    runs: list[tuple[list[dict[str, Any]], Optional[Capturing]]] = []
    for attempt in range(args.repeats):
        counter = Capturing(extractor, gateway) if extractor is not None else None
        slot = SlotCounting(slot_inner) if slot_inner is not None else None
        rows = []
        for i, row in enumerate(cases):
            rows.append(_run_case(row, f"reval_{stamp}_{attempt}_{i}", counter, attempt + 1, slot))
            sys.stdout.write(_mark(rows[-1]))
            if (i + 1) % 64 == 0:
                sys.stdout.write("\n")
            sys.stdout.flush()
        print()
        runs.append((rows, counter))
        print(_run_line(attempt + 1, args.repeats, _summarise(rows, counter)))

    out_dir = result_dir("reschedule", label)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "results.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(runs[0][0][0]))
        writer.writeheader()
        for rows, _ in runs:
            writer.writerows(rows)
    per_repeat = [_summarise(rows, counter) for rows, counter in runs]
    report = {
        "label": label,
        "mode": mode_name,
        "today": NOW.isoformat(),
        "model": gateway.model if gateway else None,
        "repeats": args.repeats,
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runs": per_repeat,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _print_failures(runs[-1][0])
    print(f"-> {out_dir}")
    if args.safety_only:
        return int(any(s["unsafe_writes"] or s["wrong_slot_writes"] for s in per_repeat))
    return int(any(s["failed_cases"] for s in per_repeat))


if __name__ == "__main__":  # pragma: no cover - script chạy tay
    raise SystemExit(main())
