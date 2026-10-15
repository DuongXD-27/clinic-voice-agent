"""Đánh giá No answer (UNREACHABLE, §1.1.7): hộp thư, im lặng, tín hiệu tổng đài, và case bẫy người thật.

    python scripts/no_answer_eval.py --baseline                 # chỉ luật, KHÔNG gọi API
    python scripts/no_answer_eval.py --semantic --repeats 3     # gọi model thật, cần OPENAI_API_KEY
    python scripts/no_answer_eval.py --baseline --groups voicemail_asr,human_trap -v

Chạy tay, không nằm trong `pytest`. Khác confirm / cancel (chấm MỘT lượt), No answer là kịch bản
NHIỀU lượt: mỗi case chạy **Orchestrator thật + FakeClinicAPI** tới câu hỏi `question_id` (lời dựng
sẵn giống `tests/engine/test_silence_line_signal.py`), rồi phát lần lượt các lượt trong cột `turns`
(phân tách ` | `; `<silence>` là lượt `silence_ms > 0`, Phụ lục A;
`<phone_status:NO_ANSWER>` / `<phone_status:LINE_BUSY>` là sự kiện trạng thái giả lập,
chỉ dùng trong scope `telephony` outbound và gửi qua PhoneStatusAdapter).
Dừng ngay khi bot kết thúc cuộc gọi,
như harness. Chấm theo record và writelog (§2.1), không theo câu nói.

Căn cứ contract rev 1.1:
- §1.1.7 / Bảng 2: outbound không nghe máy, hộp thư, máy bận hoặc 3 lượt im lặng liên tiếp → gọi
  `POST /appointments/{id}/unreachable` với `unreachable_reason`; mock tăng `attempt_count`; KHÔNG để lại
  chi tiết lịch trên hộp thư. Inbound 3 lượt im lặng → `TRANSFERRED/NOT_UNDERSTOOD`, không tạo lịch.
  Lượt im lặng không phải lần không hiểu (§1.1.5).
- §4.2.5 / Phụ lục A: trên đường chấm điểm chỉ có `SILENCE` (qua `silence_ms`) và `VOICEMAIL` (qua clip
  lời chào hộp thư). `NO_ANSWER` / `LINE_BUSY` chỉ gặp ở cuộc gọi thật tuần 6 → group `operator_live`,
  tách riêng trong báo cáo. Cùng `Idempotency-Key` không được tăng `attempt_count` hai lần.
- §2.3: `ended: true` thì `outcome` phải là một trong 7 trạng thái.

Nhãn mong đợi (`expect_outcome` + `expect_reason`):

    UNREACHABLE      Ghi UNREACHABLE với đúng reason, kết thúc ở lượt `end_turn` (trống = lượt cuối).
    TRANSFERRED      Chuyển máy với đúng reason (inbound: harness không chấm reason, §2.1; eval vẫn so).
    RECONCILE        Ghi /unreachable chưa rõ kết quả: phiên bị khóa để đối soát, không báo UNREACHABLE.
    CONTINUE         Chưa kết thúc sau mọi lượt, không có lệnh ghi.
    NOT_UNREACHABLE  Case bẫy người thật: bất kỳ kết quả nào trừ UNREACHABLE (luồng sau đó thuộc eval
                     khác). Đánh dấu nhầm người thật là UNREACHABLE làm hỏng case và tăng attempt_count.
    <trạng thái khác> Ví dụ CONFIRMED: người bệnh quay lại sau vài lượt im lặng.

Kiểm record / response (`contract_errors`, độc lập với nhãn):
    wrong_appointment, multiple_writes, outcome_record_mismatch, ended_without_write,
    unfinished_call_changed_record, invalid_outcome (§2.3), reason_record_mismatch,
    attempt_count (UNREACHABLE: đúng +1; còn lại: không đổi), unreachable_key_changed (§4.2.5),
    inbound_write / inbound_unreachable, disclosure_unverified (chi tiết lịch nói ra khi chưa xác minh:
    SF-03, gồm cả hộp thư), missing_required_transfer.
Body `/unreachable` chỉ có `unreachable_reason` được khóa ở `test_clinic_mock_client.py`, không chấm ở đây.

`split`: `dev` là câu mẫu; `regression` gồm các biến thể và ca đã dùng để phát triển.
Chỉ dùng `holdout` cho dữ liệu mới chưa xem/chỉnh luật theo nó; corpus hiện không còn holdout.
`label_status=REVIEW` giữ nhãn dự kiến nhưng không chấm PASS/FAIL; vẫn kiểm lỗi record.
`scope` tách http, telephony và recovery (chính sách phục hồi nội bộ, không phải outcome HTTP).
Báo cáo tách: nhận hộp thư, báo
nhầm UNREACHABLE với người thật (false positive — nặng nhất), đúng status nhưng sai reason, im lặng
theo hướng gọi, lỗi record. Exit code 1 nếu có case không đạt; `--safety-only` chỉ fail khi có lỗi
record, lộ lịch hoặc báo nhầm UNREACHABLE.

Kết quả ghi ra `result/<dd-mm-yyyy>/no_answer/<label>/` (ngày theo giờ Việt Nam).
Transcript là dữ liệu tổng hợp, không có PII.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from copy import deepcopy
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
    PhoneStatus,
    ReconciliationRequired,
    _semantic_extractor,
    create_orchestrator,
)
from callbot.engine.session import CallContext, RedisSessionStore  # noqa: E402
from callbot.engine.tools.clinic_gateway import WRITE_MAX_SENDS  # noqa: E402
from callbot.transports.phone import PhoneStatusAdapter  # noqa: E402
from clinic_mock_sim import FakeClinicAPI, clinic_error  # noqa: E402
from inference.llm.prompt.semantic import PROMPT_VERSION  # noqa: E402

CASES = ROOT / "eval" / "no_answer" / "cases.csv"
TARGET_APPOINTMENT = "apt_00417"
INBOUND_NUMBER = "0912345600"
SILENCE_TOKEN = "<silence>"
SILENCE_MS = 2000
NAME, DOB = "Nguyễn Văn A", "14/03/1978"
# Chi tiết lịch apt_00417 không được nói khi chưa xác minh, kể cả với hộp thư (§1.1.7, SF-03)
APPOINTMENT_FACTS = ("14 tháng 10", "9 giờ", "Nội tổng quát", "tại bệnh viện")
STATUSES = frozenset(
    {"CONFIRMED", "CANCELLED", "RESCHEDULED", "TRANSFERRED", "UNREACHABLE", "BOOKED", "SCHEDULED"}
)

# Lời người gọi để tới câu hỏi đang chờ — giống test_silence_line_signal.py
SETUP: dict[str, dict[str, list[str]]] = {
    "outbound": {
        "ASK_NAME": [],
        "ASK_DOB": [NAME],
        "CONFIRM_READBACK": [NAME, DOB],
        "ASK_INTENT": [NAME, DOB, "không"],
        "OFFER_SLOTS": [NAME, DOB, "tôi muốn đổi lịch"],
        # Chọn khung là chốt đổi lịch luôn; "nào cũng được" để bot chọn nên vẫn đọc lại hỏi đồng ý
        "SLOT_READBACK": [NAME, DOB, "tôi muốn đổi lịch", "khung nào cũng được"],
        "CANCEL_RECONFIRM": [NAME, DOB, "tôi muốn hủy lịch"],
    },
    "inbound": {
        "ASK_NAME": [],
        "ASK_DOB": [NAME],
        "ASK_INTENT": [NAME, DOB],
        "OFFER_SLOTS": [NAME, DOB, "tôi muốn đặt lịch khám"],
        "SLOT_READBACK": [NAME, DOB, "tôi muốn đặt lịch khám", "khung 1"],
    },
}

# Lỗi Mock xếp hàng trước lệnh /unreachable (§4.2.5)
FAULTS: dict[str, list[dict[str, Any]]] = {
    "": [],
    "conflict_once": [{"error": clinic_error(409, "VERSION_CONFLICT")}],
    "conflict_twice": [
        {"error": clinic_error(409, "VERSION_CONFLICT")},
        {"error": clinic_error(409, "VERSION_CONFLICT")},
    ],
    "invalid_state": [{"error": clinic_error(409, "INVALID_STATE_TRANSITION")}],
    # Mock đã ghi nhưng mọi lần gửi lại (T-12) đều timeout: vẫn chưa rõ kết quả
    "outcome_unknown": [{"outcome_unknown": True, "apply_first": True}]
    + [{"outcome_unknown": True}] * (WRITE_MAX_SENDS - 1),
}

_SERVER = fakeredis.FakeServer()


class NullSemantic:
    def analyze(self, context: Any) -> None:
        return None


def _store() -> RedisSessionStore:
    return RedisSessionStore(
        fakeredis.FakeRedis(server=_SERVER, decode_responses=True), key_prefix="no-answer-eval"
    )


def parse_turns(cell: str) -> list[Optional[str | PhoneStatus]]:
    """Phân biệt lời nói, im lặng và trạng thái điện thoại tường minh; không suy từ nhãn."""
    turns: list[Optional[str | PhoneStatus]] = []
    prefix = "<phone_status:"
    for part in (p.strip() for p in cell.split("|")):
        if part == SILENCE_TOKEN:
            turns.append(None)
        elif part.startswith(prefix):
            if not part.endswith(">"):
                raise ValueError("Phone status token must end with >")
            turns.append(PhoneStatus(part[len(prefix) : -1]))
        else:
            turns.append(part)
    return turns


def _caller(turn: int, line: Optional[str]) -> CallerInput:
    if line is None:
        return CallerInput(turn=turn, text=None, silence_ms=SILENCE_MS)
    return CallerInput(turn=turn, text=line)


def _context(bot, call_id: str) -> Optional[CallContext]:
    session = bot.sessions.store.get_session(call_id)
    raw = session.context if session is not None else None
    return CallContext.from_dict(raw) if raw else None


def _start(row: dict[str, str], call_id: str, semantic: Any):
    clinic = FakeClinicAPI()
    bot = create_orchestrator(
        clinic,
        settings=EngineSettings(
            name_fallback_provider="none",
            semantic_fallback_enabled=False,
            slot_semantic_enabled=False,
        ),
        store=_store(),
    )
    if row["direction"] == "outbound":
        call = CallStart(call_id=call_id, direction="outbound", appointment_id=TARGET_APPOINTMENT)
    else:
        call = CallStart(call_id=call_id, direction="inbound", caller_number=INBOUND_NUMBER)
    opening = bot.start_call(call)
    setup = SETUP[row["direction"]][row["question_id"]]
    for turn, line in enumerate(setup, start=1):
        bot.handle_turn(call_id, _caller(turn, line))
    ctx = _context(bot, call_id)
    asked = ctx.question.question_id.value if ctx and ctx.question else None
    assert asked == row["question_id"], (row, asked)
    # Setup uses rules only; only evaluated turns can invoke the injected semantic layer.
    bot._extractor._semantic = semantic
    # Lỗi Mock chỉ áp cho lượt được chấm, không làm hỏng phần dựng
    for fault in FAULTS[row.get("fault", "")]:
        clinic.fail_next("mark_unreachable", **fault)
    return bot, clinic, opening, len(setup)


def _observed(action, reconcile: bool) -> tuple[str, str]:
    if reconcile:
        return "RECONCILE", ""
    if action is None or not action.ended:
        return "CONTINUE", ""
    reason = action.unreachable_reason or action.transfer_reason or ""
    return action.outcome or "ENDED_WITHOUT_OUTCOME", reason


def _behaviour_ok(row: dict[str, str], outcome: str, reason: str, end_turn: Optional[int]) -> bool:
    expected = row["expect_outcome"]
    if expected == "NOT_UNREACHABLE":
        return outcome != "UNREACHABLE"
    if expected == "CONTINUE":
        return outcome == expected
    if outcome != expected or reason != row["expect_reason"]:
        return False
    return end_turn == _expected_end_turn(row)


def _expected_end_turn(row: dict[str, str]) -> int:
    return int(row["end_turn"]) if row.get("end_turn") else len(parse_turns(row["turns"]))


def _contract_errors(
    row: dict[str, str],
    action,
    reconcile: bool,
    clinic: FakeClinicAPI,
    attempts_before: int,
    spoken: list[tuple[str, bool]],
) -> list[str]:
    """Record, writelog và response — không phụ thuộc nhãn hội thoại."""
    errors = []
    writes = clinic.writes
    record = clinic.appointments.get(TARGET_APPOINTMENT, {})
    inbound = row["direction"] == "inbound"
    if any(appointment != TARGET_APPOINTMENT for appointment, _, _ in writes) and not inbound:
        errors.append("wrong_appointment")
    if len(writes) > 1:
        errors.append("multiple_writes")
    if inbound:
        if writes:
            errors.append("inbound_write")
        if action is not None and action.outcome == "UNREACHABLE":
            errors.append("inbound_unreachable")
    elif reconcile:
        # Mock có thể đã ghi (apply_first); bot không được báo gì cho tới khi đối soát
        pass
    elif action is not None and action.ended:
        if action.outcome not in STATUSES:
            errors.append("invalid_outcome")
        if not writes:
            errors.append("ended_without_write")
        if record.get("status") != action.outcome:
            errors.append("outcome_record_mismatch")
        if action.outcome == "UNREACHABLE" and (
            record.get("unreachable_reason") != action.unreachable_reason
            or writes[-1:]
            != [
                (
                    TARGET_APPOINTMENT,
                    "UNREACHABLE",
                    {"unreachable_reason": action.unreachable_reason},
                )
            ]
        ):
            errors.append("reason_record_mismatch")
        if (
            action.outcome == "TRANSFERRED"
            and record.get("transfer_reason") != action.transfer_reason
        ):
            errors.append("reason_record_mismatch")
    elif writes or record.get("status") != "SCHEDULED":
        errors.append("unfinished_call_changed_record")

    if not inbound and not reconcile:
        expected_attempts = attempts_before + int(record.get("status") == "UNREACHABLE")
        if record.get("attempt_count") != expected_attempts:
            errors.append("attempt_count")
    keys = {key for key, op in clinic.requests if op == "unreachable"}
    if len(keys) > 1:
        errors.append("unreachable_key_changed")
    if any(
        not verified and any(fact in utterance for fact in APPOINTMENT_FACTS)
        for utterance, verified in spoken
    ):
        errors.append("disclosure_unverified")
    if (
        row["expect_outcome"] == "TRANSFERRED"
        and not inbound
        and (action is None or action.outcome != "TRANSFERRED")
    ):
        errors.append("missing_required_transfer")
    return errors


def _reconciliation_errors(bot, clinic, call_id: str, turn: int) -> list[str]:
    """Không chỉ bắt exception: phải khóa phiên và chặn lượt kế tiếp trước mọi lệnh ghi."""
    errors = []
    if bot.sessions.store.find_blocked_turn(call_id) != turn:
        errors.append("reconciliation_not_locked")
    before = deepcopy((clinic.appointments, clinic.writes, clinic.requests))
    try:
        bot.handle_turn(call_id, _caller(turn + 1, None))
    except ReconciliationRequired:
        pass
    else:
        errors.append("reconciliation_next_turn_allowed")
    if (clinic.appointments, clinic.writes, clinic.requests) != before:
        errors.append("reconciliation_followup_changed_clinic")
    return errors


def _run_case(row: dict[str, str], call_id: str, semantic: Any, repeat: int) -> dict[str, Any]:
    turns = parse_turns(row["turns"])
    if any(isinstance(line, PhoneStatus) for line in turns):
        if row.get("scope") != "telephony" or row["direction"] != "outbound":
            raise ValueError("Phone status requires an outbound telephony case")
    bot, clinic, opening, done = _start(row, call_id, semantic)
    phone = PhoneStatusAdapter(bot)
    attempts_before = clinic.appointments.get(TARGET_APPOINTMENT, {}).get("attempt_count", 0)
    spoken = [(opening.utterance, False)]
    ctx = _context(bot, call_id)
    verified = bool(ctx and ctx.identity_verified)
    action, reconcile, end_turn = None, False, None
    elapsed: list[float] = []
    if semantic is not None:
        semantic.last = None
    for index, line in enumerate(turns, start=1):
        if semantic is not None:
            semantic.active = True
        started = time.perf_counter()
        try:
            action = (
                phone.handle_status(call_id, turn=done + index, status=line)
                if isinstance(line, PhoneStatus)
                else bot.handle_turn(call_id, _caller(done + index, line))
            )
        except ReconciliationRequired:
            reconcile, end_turn = True, index
            break
        finally:
            elapsed.append((time.perf_counter() - started) * 1000)
            if semantic is not None:
                semantic.active = False
        ctx = _context(bot, call_id)
        verified = bool(ctx.identity_verified) if ctx is not None else verified
        spoken.append((action.utterance, verified))
        if action.ended:
            end_turn = index
            break

    outcome, reason = _observed(action, reconcile)
    errors = _contract_errors(row, action, reconcile, clinic, attempts_before, spoken)
    recovery_errors = (
        _reconciliation_errors(bot, clinic, call_id, done + end_turn) if reconcile else []
    )
    behaviour_ok = _behaviour_ok(row, outcome, reason, end_turn)
    expected = row["expect_outcome"]
    review = row.get("label_status") == "REVIEW"
    passed = None if review else behaviour_ok and not errors and not recovery_errors
    return {
        "id": row.get("id", call_id),
        "scope": row.get("scope", "http"),
        "label_status": row.get("label_status", "CONFIRMED"),
        "status": "REVIEW" if review else "PASS" if passed else "FAIL",
        "repeat": repeat,
        "split": row["split"],
        "group": row["group"],
        "direction": row["direction"],
        "question_id": row["question_id"],
        "turns": row["turns"],
        "fault": row.get("fault", ""),
        "expect_outcome": expected,
        "expect_reason": row["expect_reason"],
        "expect_end_turn": _expected_end_turn(row)
        if expected not in {"CONTINUE", "NOT_UNREACHABLE"}
        else "",
        "observed_outcome": outcome,
        "observed_reason": reason,
        "end_turn": end_turn or "",
        "turns_played": len(elapsed),
        "record_status": clinic.appointments.get(TARGET_APPOINTMENT, {}).get("status", ""),
        "attempt_count": clinic.appointments.get(TARGET_APPOINTMENT, {}).get("attempt_count", ""),
        "writes": json.dumps(clinic.writes, ensure_ascii=False),
        "last_utterance": spoken[-1][0],
        "behaviour_ok": behaviour_ok,
        # Đúng status nhưng sai reason / lượt kết thúc: harness vẫn đọc được UNREACHABLE
        "status_ok": outcome == expected or (expected == "NOT_UNREACHABLE" and behaviour_ok),
        "contract_ok": not errors,
        "contract_errors": "|".join(errors),
        "recovery_errors": "|".join(recovery_errors),
        "passed": passed,
        # Người thật / cuộc gọi còn tiếp mà bot đánh dấu UNREACHABLE
        "false_unreachable": not review
        and expected in {"NOT_UNREACHABLE", "CONTINUE"}
        and outcome == "UNREACHABLE",
        "routed": bool(semantic and semantic.last),
        "elapsed_ms": round(max(elapsed), 1) if elapsed else 0.0,
        "note": row.get("note", ""),
    }


def _rate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [r for r in rows if r["label_status"] != "REVIEW"]
    passed = sum(r["passed"] for r in rows)
    return {
        "passed": passed,
        "total": len(rows),
        "rate": round(passed / len(rows), 4) if rows else None,
    }


def _summarise(rows: list[dict[str, Any]], counter: Optional[Counting]) -> dict[str, Any]:
    all_rows = rows
    review_rows = [r for r in rows if r["label_status"] == "REVIEW"]
    rows = [r for r in rows if r["label_status"] != "REVIEW"]
    holdout = [r for r in rows if r["split"] == "holdout"]
    voicemail = [
        r for r in rows if r["expect_reason"] == "VOICEMAIL" and r["direction"] == "outbound"
    ]
    by_group: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = by_group.setdefault(
            row["group"], {"total": 0, "passed": 0, "holdout": 0, "holdout_passed": 0}
        )
        bucket["total"] += 1
        bucket["passed"] += int(row["passed"])
        if row["split"] == "holdout":
            bucket["holdout"] += 1
            bucket["holdout_passed"] += int(row["passed"])
    return {
        "cases": len(all_rows),
        "scored_cases": len(rows),
        "review_cases": len(review_rows),
        "reviews": [
            {
                k: r[k]
                for k in (
                    "id",
                    "turns",
                    "expect_outcome",
                    "observed_outcome",
                    "contract_errors",
                    "recovery_errors",
                )
            }
            for r in review_rows
        ],
        "passed_cases": sum(r["passed"] for r in rows),
        "failed_cases": sum(not r["passed"] for r in rows),
        "holdout": _rate(holdout),
        "scored_path": _rate([r for r in rows if r["scope"] == "http"]),
        "operator_live": _rate([r for r in rows if r["scope"] == "telephony"]),
        "recovery": _rate([r for r in rows if r["scope"] == "recovery"]),
        "regression": _rate([r for r in rows if r["split"] == "regression"]),
        "voicemail_detected_holdout": _rate([r for r in voicemail if r["split"] == "holdout"]),
        "voicemail_detected_all": _rate(voicemail),
        "silence": _rate([r for r in rows if r["group"].startswith("silence")]),
        "human_trap": _rate([r for r in rows if r["expect_outcome"] == "NOT_UNREACHABLE"]),
        "false_unreachable": sum(r["false_unreachable"] for r in rows),
        "wrong_reason_right_status": sum(
            r["status_ok"] and not r["behaviour_ok"] and r["expect_outcome"] == "UNREACHABLE"
            for r in rows
        ),
        "behaviour_failures": sum(not r["behaviour_ok"] for r in rows),
        # Legacy key: only the implemented record/response checks, not full compliance.
        "contract_failures": sum(not r["contract_ok"] for r in all_rows),
        "record_check_failures": sum(not r["contract_ok"] for r in all_rows),
        "recovery_failures": sum(bool(r["recovery_errors"]) for r in all_rows),
        "disclosures": sum("disclosure_unverified" in r["contract_errors"] for r in all_rows),
        "contract_error_counts": dict(
            Counter(e for r in all_rows for e in r["contract_errors"].split("|") if e)
        ),
        "by_group": dict(sorted(by_group.items())),
        "failures": [
            {
                k: r[k]
                for k in (
                    "id",
                    "split",
                    "group",
                    "question_id",
                    "turns",
                    "fault",
                    "expect_outcome",
                    "expect_reason",
                    "observed_outcome",
                    "observed_reason",
                    "end_turn",
                    "contract_errors",
                    "recovery_errors",
                )
            }
            for r in all_rows
            if r["passed"] is False or not r["contract_ok"] or r["recovery_errors"]
        ],
        "model_calls": counter.routed if counter else 0,
        "model_statuses": dict(sorted(counter.statuses.items())) if counter else {},
        "turn_latency_ms": _latency([r["elapsed_ms"] for r in rows]),
        "semantic_latency_ms": _latency(counter.latencies_ms if counter else []),
    }


def _exit_code(runs: list[dict[str, Any]], safety_only: bool = False) -> int:
    if any(run["contract_failures"] or run["recovery_failures"] for run in runs):
        return 1
    if safety_only:
        return int(any(run["false_unreachable"] or run["contract_failures"] for run in runs))
    return int(any(run["failed_cases"] for run in runs))


def _mark(row: dict[str, Any]) -> str:
    """`.` đạt · `R` đúng status sai reason / lượt · `U` báo nhầm UNREACHABLE · `C` lỗi record · `F` sai."""
    if row["label_status"] == "REVIEW":
        return "?" if row["contract_ok"] and not row["recovery_errors"] else "C"
    if row["passed"]:
        return "."
    if row["false_unreachable"]:
        return "U"
    if not row["contract_ok"] or row["recovery_errors"]:
        return "C"
    return "R" if row["status_ok"] else "F"


def _run_line(attempt: int, repeats: int, s: dict[str, Any]) -> str:
    def frac(key: str) -> str:
        return f"{s[key]['passed']}/{s[key]['total']}"

    return (
        f"run {attempt}/{repeats}: passed {s['passed_cases']}/{s['scored_cases']}"
        f" · REVIEW {s['review_cases']} · regression {frac('regression')}"
        f" · holdout {frac('holdout')} · scored path {frac('scored_path')}"
        f" · voicemail holdout {frac('voicemail_detected_holdout')}"
        f" · silence {frac('silence')} · human traps {frac('human_trap')}"
        f" · operator (live) {frac('operator_live')}"
        f" · recovery {frac('recovery')}"
        f" · false UNREACHABLE {s['false_unreachable']}"
        f" · wrong reason {s['wrong_reason_right_status']}"
        f" · behaviour failures {s['behaviour_failures']}"
        f" · record check failures {s['record_check_failures']}"
        f" · recovery failures {s['recovery_failures']} · disclosures {s['disclosures']}"
        f" · model calls {s['model_calls']}"
    )


def _print_failures(runs: list[list[dict[str, Any]]]) -> None:
    failed: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for attempt, rows in enumerate(runs, start=1):
        for row in rows:
            if row["passed"] or (
                row["status"] == "REVIEW" and row["contract_ok"] and not row["recovery_errors"]
            ):
                continue
            key = (row["direction"], row["question_id"], row["turns"], row["fault"])
            entry = failed.setdefault(key, {"row": row, "runs": [], "observed": []})
            entry["runs"].append(attempt)
            entry["observed"].append(
                f"{row['observed_outcome']}/{row['observed_reason'] or '-'}@{row['end_turn'] or '-'}"
            )
    if not failed:
        print("No failed cases; REVIEW labels are excluded from scoring.")
        return
    print(f"Failed cases ({len(failed)}):")
    for (direction, question, turns, fault), entry in failed.items():
        row = entry["row"]
        expected = f"{row['expect_outcome']}/{row['expect_reason'] or '-'}"
        if row["expect_end_turn"]:
            expected += f"@{row['expect_end_turn']}"
        tag = _mark(row)
        print(
            f"  [{tag}] {row['group']} {direction} {question}{' ' + fault if fault else ''}"
            f" | {turns} -> {', '.join(entry['observed'])} (expected {expected};"
            f" runs {entry['runs']}; contract={row['contract_errors'] or 'ok'})"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="No answer eval (UNREACHABLE): voicemail, silence, operator signals, human traps."
        " Results go to result/<dd-mm-yyyy>/no_answer/<label>/."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--baseline", action="store_true", help="rules only, no API calls")
    mode.add_argument(
        "--route-only",
        action="store_true",
        help="rules + a model stub returning None: counts model calls, no API calls",
    )
    mode.add_argument(
        "--semantic", action="store_true", help="rules + real model (needs OPENAI_API_KEY)"
    )
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--label", default=None, help="result folder name (default: mode)")
    parser.add_argument("--groups", help="comma-separated groups; omit for every case")
    parser.add_argument(
        "--safety-only",
        action="store_true",
        help="Exit 0 despite dialogue mismatches; record errors, disclosures and false UNREACHABLE still fail",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="print every case")
    args = parser.parse_args()
    # Console Windows mặc định cp1252 không in được tiếng Việt
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    mode_name = "semantic" if args.semantic else "route-only" if args.route_only else "baseline"
    label = args.label or mode_name
    extractor: Any = None
    gateway = None
    if args.semantic:
        extractor = _semantic_extractor(
            EngineSettings(name_fallback_provider="none", semantic_fallback_enabled=True)
        )
        if extractor is None:
            print("Cannot build the semantic layer: check .env settings.", file=sys.stderr)
            return 2
        gateway = RecordingGateway(extractor._gateway)
        extractor._gateway = gateway
    elif args.route_only:
        extractor = NullSemantic()

    with CASES.open(encoding="utf-8", newline="") as fh:
        cases = list(csv.DictReader(fh))
    if args.groups:
        wanted = set(args.groups.split(","))
        cases = [row for row in cases if row["group"] in wanted]
    if not cases:
        parser.error("No matching cases")

    print(
        f"{mode_name} · {len(cases)} cases × {args.repeats} run(s) · label '{label}'"
        f" · scored path: SILENCE/VOICEMAIL only (§4.2.5)",
        flush=True,
    )
    if not args.verbose:
        print(
            "legend: . pass · ? REVIEW (unscored) · R right status, wrong reason/turn · F fail · U FALSE UNREACHABLE · C record error"
        )
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    runs: list[list[dict[str, Any]]] = []
    summaries = []
    for attempt in range(1, args.repeats + 1):
        counter = Counting(extractor, gateway) if extractor is not None else None
        rows = []
        if not args.verbose:
            sys.stdout.write(f"run {attempt}/{args.repeats} ")
        for i, row in enumerate(cases):
            result = _run_case(row, f"naeval_{stamp}_{attempt}_{i}", counter, attempt)
            rows.append(result)
            if args.verbose:
                print(
                    f"[{attempt}/{args.repeats}] [{i + 1}/{len(cases)}] {_mark(result)} {row['group']}"
                    f" {row['direction']} {row['question_id']} | {row['turns']}"
                    f" -> {result['observed_outcome']}/{result['observed_reason'] or '-'}"
                    f"@{result['end_turn'] or '-'}",
                    flush=True,
                )
            else:
                sys.stdout.write(_mark(result))
                sys.stdout.flush()
        if not args.verbose:
            sys.stdout.write("\n")
        runs.append(rows)
        summary = _summarise(rows, counter)
        summaries.append(summary)
        print(_run_line(attempt, args.repeats, summary), flush=True)

    out_dir = result_dir("no_answer", label)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "results.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(runs[0][0]))
        writer.writeheader()
        for rows in runs:
            writer.writerows(rows)
    report = {
        "label": label,
        "mode": mode_name,
        "evaluation_scope": "no_answer_unreachable",
        "limitations": "Synthetic text regression; not audio/harness certification. REVIEW excluded from accuracy; record checks still apply. Recovery expectations include internal policy. No claim of unseen-data accuracy.",
        "contract": "AIHR-PC-001 rev 1.1 §1.1.7, §2.2, §4.2.5, Appendix A",
        "exit_policy": "safety_only" if args.safety_only else "all_cases",
        "groups": sorted({row["group"] for row in cases}),
        "model": gateway.model if gateway else None,
        "prompt_version": getattr(extractor, "prompt_version", PROMPT_VERSION) if gateway else None,
        "repeats": args.repeats,
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runs": summaries,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _print_failures(runs)
    print(f"-> {out_dir}")
    return _exit_code(summaries, args.safety_only)


if __name__ == "__main__":  # pragma: no cover - script chạy tay
    raise SystemExit(main())
