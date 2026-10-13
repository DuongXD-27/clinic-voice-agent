"""Đánh giá Confirm attendance (T-04): xác nhận đến khám, hỏi lại và rẽ nhánh đúng.

    python scripts/confirm_eval.py --baseline                 # chỉ luật, KHÔNG gọi API
    python scripts/confirm_eval.py --route-only               # luật + model giả trả None: đếm lượt gọi model
    python scripts/confirm_eval.py --semantic --repeats 3     # gọi model thật, cần OPENAI_API_KEY
    python scripts/eval_compare.py result/<dd-mm-yyyy>/confirm/<A> result/<dd-mm-yyyy>/confirm/<B>

Chạy tay, không nằm trong `pytest`. Mỗi câu chạy qua **Orchestrator thật + FakeClinicAPI** ở đúng câu
hỏi đang chờ (`question_id` trong bộ câu):
- `CONFIRM_READBACK`: outbound vừa xác minh, câu tóm tắt gộp đọc lại lịch (Figure 0);
- `ASK_INTENT`: sau khi người gọi nói "Không" ở câu tóm tắt (bot hỏi "đổi hay hủy").
Không chấm SLOT_READBACK (thuộc Reschedule). Case chọn CANCEL/RESCHEDULE được giữ để
chấm rẽ nhánh, không tính vào tỷ lệ hoàn thành xác nhận đến khám.

`expect_behaviour` là nhãn nghiệp vụ theo kiến trúc §3.2 (`O_AGREE`): nói sẽ đến / đồng ý rõ với lịch
vừa đọc → `CONFIRM` (chỉ báo đã nghe / đã nhớ như "vâng tôi nghe", "tôi nhớ rồi" chưa phải đồng ý);
"không" hoặc kể hoàn cảnh không đến được → `ASK_CHANGE_OR_CANCEL`, trừ lý do đã khám
nơi khác / đã khỏi ("khám chỗ khác rồi", "khỏi rồi") → `CANCEL` (`implied_cancel`); chỉ chưa rõ có đồng ý lịch hay không
→ `REREAD`. Câu bot hiểu được nhưng là yêu cầu / câu hỏi ngoài kịch bản (người khác đến thay, hỏi địa
chỉ, xin gọi lại sau, không nhận lịch...) → `TRANSFER` (§3.3, `OUT_OF_SCOPE`), không dùng `REREAD` để né.
Dấu `|` chỉ dùng khi nghiệp vụ chấp nhận cả hai hành vi với câu mơ hồ thật — không dùng vì "cả hai đều
an toàn" hay để chừa chỗ cho luật khi không có model. `needs_inference=yes`: ý người gọi phải suy ra
từ hoàn cảnh, không có từ khóa nói thẳng; chỉ luật thì được phép sai ở các câu này nhưng không được
ghi. Báo cáo tách:
- độ chính xác trên `holdout` (tập `prompt` là câu mẫu của prompt), tách câu luật quyết được và câu
  cần suy nghĩa,
- số lần GHI SAI và lỗi record/response; exit code 1 nếu có case không đạt,
- tỷ lệ câu đồng ý thật không được ghi ngay, số lượt gọi model theo nhóm.
- `attendance_confirmation_*`: chỉ các câu holdout mong đợi CONFIRM; phải pass cả record.
- `branch_routing_*`: các câu holdout mong đợi CANCEL/RESCHEDULE, chưa hoàn thành ghi lịch.
Mỗi dòng kết quả ghi nhãn model trả về (`semantic_kind`, `semantic_reason`, `semantic_intent`) và
`transfer_reason` khi bot chuyển máy (group `out_of_scope` phải là `OUT_OF_SCOPE`; group
`out_of_scope_trap` là câu có từ gần giống nhưng không được chuyển máy).
`passed` yêu cầu cả `behaviour_ok` và `contract_ok`; reason mong đợi nằm trong cột
`expect_transfer_reason`. Mặc định exit 1 nếu bất kỳ case nào không đạt; `--safety-only`
chỉ bỏ qua lỗi nhãn hội thoại, không bỏ qua lỗi record hoặc bỏ sót transfer bắt buộc.
Đây là eval MỘT LƯỢT sau setup đã xác minh, không thay thế bộ full-call/SF-01..05.

Nhãn hành vi (`expect_behaviour`, `observed_behaviour`) — `_behaviour` xét theo đúng thứ tự dưới đây,
nhãn đầu tiên khớp được dùng. CONFIRM và TRANSFER ghi vào Clinic;
các nhãn hỏi lại không ghi.

    CONFIRM               Ghi CONFIRMED (xác nhận đến khám).
    SLOT_WRITE            Ghi RESCHEDULED / BOOKED ngoài phạm vi bộ này: luôn là lỗi.
    TRANSFER              Chuyển máy (xin nhân viên, lâm sàng, không hiểu 2 lần, ngoài phạm vi...).
    ENDED                 Cuộc gọi kết thúc mà không thuộc các nhãn trên.
    ASK_CHANGE_OR_CANCEL  Bot hỏi "Dạ, anh chị muốn đổi lịch hay hủy lịch khám ạ?" — người gọi đã
                          nói không đến được / từ chối lịch.
    NOT_UNDERSTOOD        Bot nói "Dạ, em chưa hiểu ý anh chị..." — tính vào §1.1.5 (2 lần -> chuyển máy).
    RESCHEDULE            Bot bắt đầu đổi lịch (hành động chờ RESCHEDULE): đọc các khung giờ trống
                          (OFFER_SLOTS) hoặc đọc thẳng slot duy nhất (SLOT_READBACK). Chưa ghi.
    CANCEL                Bot hỏi "chắc chắn muốn hủy lịch khám này..." (CANCEL_RECONFIRM) — bắt đầu
                          hủy, chưa ghi; cần xác nhận lần hai có động từ hủy.
    REREAD                Câu hỏi đang chờ là CONFIRM_READBACK: bot đọc lại ngày, giờ, chuyên khoa và hỏi có /
                          không ("... có đến khám được theo lịch này không ạ?" / "... đồng ý chứ ạ?").
                          "vâng" ở lượt sau sẽ ghi CONFIRMED.
    OTHER                 Không khớp nhãn nào — luồng lạ, cần xem lại.

Kết quả ghi ra `result/<dd-mm-yyyy>/confirm/<label>/` (ngày theo giờ Việt Nam, thư mục được commit).
Transcript là dữ liệu tổng hợp, không có PII.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fakeredis  # noqa: E402

# Dùng chung bộ đếm model và cách đo với eval hủy; import cũng đặt sys.path cho src / tests.
from cancel_eval import Counting, RecordingGateway, _latency, result_dir  # noqa: E402

from callbot.engine import (  # noqa: E402
    CallerInput,
    CallStart,
    EngineSettings,
    _semantic_extractor,
    create_orchestrator,
)
from callbot.engine.dialogue import templates as t  # noqa: E402
from callbot.engine.extraction.schema import QuestionId  # noqa: E402
from callbot.engine.extraction.semantic import SemanticContext, SemanticOutcome  # noqa: E402
from callbot.engine.session import CallContext, RedisSessionStore  # noqa: E402
from clinic_mock_sim import FakeClinicAPI  # noqa: E402
from inference.llm.prompt.semantic import PROMPT_VERSION  # noqa: E402

CASES = ROOT / "eval" / "confirm" / "cases.csv"
VERIFIED = ["Nguyễn Văn A", "14/03/1978"]
SETUP: dict[str, list[str]] = {
    QuestionId.CONFIRM_READBACK.value: [],
    QuestionId.ASK_INTENT.value: ["Không"],
}
WRITE_BEHAVIOURS = frozenset({"CONFIRM", "SLOT_WRITE"})
TARGET_APPOINTMENT = "apt_00417"

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


class NullSemantic:
    """`--route-only`: model không trả gì — đo router và nhánh dự phòng mà không gọi API."""

    def analyze(self, context: SemanticContext) -> None:
        return None


def _store() -> RedisSessionStore:
    return RedisSessionStore(
        fakeredis.FakeRedis(server=_SERVER, decode_responses=True), key_prefix="confirm-eval"
    )


def _behaviour(action, ctx: Optional[CallContext], clinic: FakeClinicAPI) -> str:
    written = {status for _, status, _ in clinic.writes}
    if "CONFIRMED" in written:
        return "CONFIRM"
    if written & {"RESCHEDULED", "BOOKED"}:
        return "SLOT_WRITE"
    if action.outcome == "TRANSFERRED":
        return "TRANSFER"
    if ctx is None or ctx.question is None:
        return "ENDED"
    asked = ctx.question.question_id
    if action.utterance in t.static_choices(t.ASK_CHANGE_OR_CANCEL):
        return "ASK_CHANGE_OR_CANCEL"
    if action.utterance in t.static_choices(t.NOT_UNDERSTOOD):
        return "NOT_UNDERSTOOD"
    if ctx.pending_action == "RESCHEDULE" or asked is QuestionId.OFFER_SLOTS:
        # Chỉ một slot trống thì Dialogue bỏ qua OFFER_SLOTS và đọc thẳng SLOT_READBACK (như
        # Figure 0 reschedule) — vẫn là bắt đầu đổi lịch, chưa ghi; trước đây rơi vào OTHER.
        return "RESCHEDULE"
    if asked is QuestionId.CANCEL_RECONFIRM:
        return "CANCEL"
    if asked is QuestionId.CONFIRM_READBACK:
        return "REREAD"
    return "OTHER"


def _contract_errors(
    action, before: CallContext, clinic: FakeClinicAPI, expected_reason: str
) -> list[str]:
    """Kiểm record và response, độc lập với nhãn hành vi hội thoại một lượt.

    Đây vẫn là eval một lượt sau setup danh tính, không thay thế full-call/SF test set.
    """
    errors = []
    record = clinic.appointments[TARGET_APPOINTMENT]
    writes = clinic.writes
    if any(appointment != TARGET_APPOINTMENT for appointment, _, _ in writes):
        errors.append("wrong_appointment")
    if len(writes) > 1:
        errors.append("multiple_writes")
    if action.ended:
        if not writes:
            errors.append("ended_without_write")
        if record["status"] != action.outcome:
            errors.append("outcome_record_mismatch")
        if action.state != "ENDED":
            errors.append("ended_state_mismatch")
    elif writes or record["status"] != "SCHEDULED" or action.outcome is not None:
        errors.append("unfinished_call_changed_record")
    if writes and writes[-1][1] != record["status"]:
        errors.append("writelog_record_mismatch")
    if expected_reason and action.outcome != "TRANSFERRED":
        errors.append("missing_required_transfer")
    if record["status"] == "CONFIRMED":
        if not record.get("confirmed_at") or record.get("confirmed_via") != "callbot":
            errors.append("confirmation_metadata")
        question = before.question
        if not before.identity_verified:
            errors.append("unverified_confirmation")
        if question is None or question.question_id is not QuestionId.CONFIRM_READBACK:
            errors.append("missing_readback")
        elif not all(
            fact and fact in question.text
            for fact in (record.get("department"), t.speak_datetime(record["starts_at"]))
        ):
            errors.append("incomplete_readback")
    if any(status in {"RESCHEDULED", "BOOKED"} for _, status, _ in writes):
        errors.append("unexpected_slot_write")
    if action.outcome == "TRANSFERRED":
        if not expected_reason:
            errors.append("unexpected_transfer")
        elif (
            action.transfer_reason != expected_reason
            or record.get("transfer_reason") != expected_reason
            or not writes
            or writes[-1][2].get("transfer_reason") != expected_reason
        ):
            errors.append("transfer_reason_mismatch")
    return errors


def _exit_code(runs: list[dict[str, Any]], safety_only: bool = False) -> int:
    if safety_only:
        return int(any(run["unsafe_writes"] or run["contract_failures"] for run in runs))
    return int(any(run["failed_cases"] for run in runs))


def _run_case(
    row: dict[str, str], call_id: str, semantic: Optional[Capturing], repeat: int
) -> dict[str, Any]:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic, store=_store())
    bot._extractor._semantic = semantic
    # Tầng model chọn khung không thuộc phạm vi eval này: tắt kể cả khi .env bật SLOT_SEMANTIC_ENABLED
    bot._extractor._slot_semantic = None
    bot.start_call(CallStart(call_id=call_id, direction="outbound", appointment_id="apt_00417"))
    lines = [*VERIFIED, *SETUP[row["question_id"]]]
    for turn, line in enumerate(lines, start=1):
        bot.handle_turn(call_id, CallerInput(turn=turn, text=line))
    raw = bot.sessions.store.get_session(call_id).context
    before = CallContext.from_dict(raw)
    asked = before.question
    assert asked is not None and asked.question_id.value == row["question_id"], row

    if semantic is not None:
        semantic.last, semantic.outcome, semantic.active = None, None, True
    started = time.perf_counter()
    try:
        action = bot.handle_turn(call_id, CallerInput(turn=len(lines) + 1, text=row["transcript"]))
    finally:
        if semantic is not None:
            semantic.active = False
    elapsed_ms = (time.perf_counter() - started) * 1000

    raw = bot.sessions.store.get_session(call_id).context
    ctx = CallContext.from_dict(raw) if raw else None
    observed = _behaviour(action, ctx, clinic)
    accepted = row["expect_behaviour"].split("|")
    expected_reason = row.get("expect_transfer_reason", "")
    errors = _contract_errors(action, before, clinic, expected_reason)
    behaviour_ok = observed in accepted
    semantic_status, semantic_ms = semantic.last if semantic and semantic.last else ("", None)
    outcome = semantic.outcome if semantic else None
    return {
        "repeat": repeat,
        "split": row["split"],
        "group": row["group"],
        "question_id": row["question_id"],
        "transcript": row["transcript"],
        "needs_inference": row.get("needs_inference") == "yes",
        "expect_behaviour": row["expect_behaviour"],
        "observed_behaviour": observed,
        # Cùng là TRANSFER: tách chuyển vì ngoài phạm vi (group out_of_scope) với lâm sàng / xin nhân viên
        "transfer_reason": action.transfer_reason or "",
        "expect_transfer_reason": expected_reason,
        "behaviour_ok": behaviour_ok,
        "contract_ok": not errors,
        "contract_errors": "|".join(errors),
        "passed": behaviour_ok and not errors,
        "unsafe_write": observed in WRITE_BEHAVIOURS and observed not in accepted,
        # Câu đồng ý thật (hành vi mong đợi đầu tiên là ghi) mà bot đọc lại thay vì ghi
        "agree_reread": accepted[0] in WRITE_BEHAVIOURS and observed not in WRITE_BEHAVIOURS,
        "routed": bool(semantic and semantic.last),
        "semantic_status": semantic_status,
        "semantic_kind": outcome.reply_kind.value if outcome else "",
        "semantic_reason": (outcome.cancel_reason or "") if outcome else "",
        "semantic_intent": outcome.intent.value if outcome and outcome.intent else "",
        "semantic_ms": round(semantic_ms, 1) if semantic_ms is not None else "",
        "elapsed_ms": round(elapsed_ms, 1),
        "semantic_probabilities": semantic.last_probabilities if semantic and semantic.last else "",
    }


class _Progress:
    """Tiến độ kiểu pytest: mỗi câu một ký tự, phần trăm ở cuối dòng.

    `.` đúng · `F` sai hành vi (không ghi) · `W` GHI SAI · `t` đúng nhưng model timeout (giữ kết quả luật).
    """

    WIDTH = 64

    def __init__(self, total: int, repeats: int) -> None:
        self._total, self._repeats = total, repeats
        self._column = 0

    def start(self, attempt: int) -> None:
        self._prefix = f"run {attempt}/{self._repeats} "
        self._column = 0
        sys.stdout.write(self._prefix)
        sys.stdout.flush()

    def step(self, index: int, row: dict[str, Any]) -> None:
        sys.stdout.write(_mark(row))
        self._column += 1
        if self._column == self.WIDTH or index == self._total:
            percent = index * 100 // self._total
            padding = " " * (self.WIDTH - self._column)
            sys.stdout.write(f"{padding} [{percent:3d}%]\n")
            self._column = 0
            if index != self._total:
                sys.stdout.write(" " * len(self._prefix))
        sys.stdout.flush()


def _mark(row: dict[str, Any]) -> str:
    if row["unsafe_write"]:
        return "W"
    if not row["passed"]:
        return "F"
    return "t" if row["semantic_status"] == "timeout" else "."


def _print_progress(
    attempt: int, repeats: int, index: int, total: int, row: dict[str, Any]
) -> None:
    """`-v`: một dòng mỗi câu, in ngay (flush) để biết đang chạy câu nào khi có model."""
    mark = "PASS" if row["passed"] else "FAIL"
    if row["unsafe_write"]:
        mark = "UNSAFE WRITE"
    model = ""
    if row["semantic_status"]:
        kind = f" {row['semantic_kind']}" if row["semantic_kind"] else ""
        model = f" · model {row['semantic_status']}{kind} {row['semantic_ms']} ms"
    print(
        f"[run {attempt}/{repeats}] [{index}/{total}] {mark} {row['question_id']} "
        f"| {row['transcript']} -> {row['observed_behaviour']}{model}",
        flush=True,
    )


def _print_failures(runs: list[tuple[list[dict[str, Any]], Optional[Capturing]]]) -> None:
    """Như "short test summary" của pytest: mỗi câu sai một dòng, gộp qua các lần lặp."""
    failed: dict[tuple[str, str], dict[str, Any]] = {}
    for attempt, (rows, _) in enumerate(runs, start=1):
        for row in rows:
            if row["passed"]:
                continue
            key = (row["question_id"], row["transcript"])
            entry = failed.setdefault(
                key, {"row": row, "runs": [], "observed": [], "unsafe": False}
            )
            entry["runs"].append(attempt)
            entry["observed"].append(row["observed_behaviour"])
            entry["unsafe"] = entry["unsafe"] or row["unsafe_write"]
    if not failed:
        print("No failed cases.")
        return
    print(f"Failed cases ({len(failed)}):")
    for (question, transcript), entry in failed.items():
        row = entry["row"]
        tag = "UNSAFE WRITE" if entry["unsafe"] else "FAIL"
        print(
            f"  {tag} {question} | {transcript} -> {'/'.join(entry['observed'])}"
            f" (expected {row['expect_behaviour']}; runs {entry['runs']};"
            f" contract={row['contract_errors'] or 'ok'})"
        )


def _run_line(attempt: int, repeats: int, summary: dict[str, Any]) -> str:
    """ "run 1/3: passed 120/121 (99.2%) · unsafe writes 0 · ..." """
    passed, scored = summary["holdout_passed"], summary["holdout_cases"]
    statuses = ", ".join(f"{name} {count}" for name, count in summary["model_statuses"].items())
    model = f"model calls {summary['model_calls']}" + (f" ({statuses})" if statuses else "")
    return (
        f"run {attempt}/{repeats}: behaviour {passed}/{scored} ({passed / max(1, scored):.1%})"
        f" · all checks {summary['holdout_fully_passed']}/{scored}"
        f" · confirmed {summary['attendance_confirmation_passed']}/{summary['attendance_confirmation_cases']}"
        f" · branch routing {summary['branch_routing_passed']}/{summary['branch_routing_cases']}"
        f" [rule {summary['rule_passed']}/{summary['rule_cases']}"
        f", inference {summary['inference_passed']}/{summary['inference_cases']}]"
        f" · unsafe writes {summary['unsafe_writes']}"
        f" · contract failures {summary['contract_failures']}"
        f" · agreements not confirmed {summary['agree_not_confirmed']}/{summary['agree_cases']}"
        f" · {model}"
    )


def _summarise(rows: list[dict[str, Any]], counter: Optional[Counting]) -> dict[str, Any]:
    holdout = [r for r in rows if r["split"] == "holdout"]
    by_group: dict[str, dict[str, int]] = {}
    for row in holdout:
        bucket = by_group.setdefault(row["group"], {"total": 0, "ok": 0, "routed": 0})
        bucket["total"] += 1
        bucket["ok"] += int(row["behaviour_ok"])
        bucket["routed"] += int(row["routed"])
    agree = [r for r in rows if r["expect_behaviour"].split("|")[0] in WRITE_BEHAVIOURS]
    confirmation = [r for r in holdout if r["expect_behaviour"] == "CONFIRM"]
    branches = [
        r for r in holdout if set(r["expect_behaviour"].split("|")) & {"CANCEL", "RESCHEDULE"}
    ]
    inference = [r for r in holdout if r["needs_inference"]]
    rule = [r for r in holdout if not r["needs_inference"]]
    statuses = dict(sorted(counter.statuses.items())) if counter else {}
    return {
        "cases": len(rows),
        "passed_cases": sum(r["passed"] for r in rows),
        "failed_cases": sum(not r["passed"] for r in rows),
        "contract_failures": sum(not r["contract_ok"] for r in rows),
        "holdout_cases": len(holdout),
        "attendance_confirmation_cases": len(confirmation),
        "attendance_confirmation_passed": sum(r["passed"] for r in confirmation),
        "attendance_confirmation_rate": (
            round(sum(r["passed"] for r in confirmation) / len(confirmation), 4)
            if confirmation
            else None
        ),
        "branch_routing_cases": len(branches),
        "branch_routing_passed": sum(r["passed"] for r in branches),
        "branch_routing_accuracy": (
            round(sum(r["passed"] for r in branches) / len(branches), 4) if branches else None
        ),
        "holdout_fully_passed": sum(r["passed"] for r in holdout),
        "holdout_passed": sum(r["behaviour_ok"] for r in holdout),
        "holdout_behaviour_accuracy": round(
            sum(r["behaviour_ok"] for r in holdout) / max(1, len(holdout)), 4
        ),
        "rule_cases": len(rule),
        "rule_passed": sum(r["behaviour_ok"] for r in rule),
        "inference_cases": len(inference),
        "inference_passed": sum(r["behaviour_ok"] for r in inference),
        "unsafe_writes": sum(r["unsafe_write"] for r in rows),
        "unsafe": sorted({r["transcript"] for r in rows if r["unsafe_write"]}),
        "agree_cases": len(agree),
        "agree_not_confirmed": sum(r["agree_reread"] for r in agree),
        "agree_reread_rate": round(sum(r["agree_reread"] for r in agree) / max(1, len(agree)), 4),
        "agree_routed": sum(r["routed"] for r in agree),
        "by_group": {name: dict(bucket) for name, bucket in sorted(by_group.items())},
        "failures": [
            {
                k: r[k]
                for k in (
                    "group",
                    "question_id",
                    "transcript",
                    "needs_inference",
                    "expect_behaviour",
                    "observed_behaviour",
                    "semantic_kind",
                    "semantic_reason",
                    "expect_transfer_reason",
                    "transfer_reason",
                    "contract_errors",
                )
            }
            for r in holdout
            if not r["passed"]
        ],
        "model_calls": counter.routed if counter else 0,
        "model_statuses": statuses,
        "turn_latency_ms": _latency([r["elapsed_ms"] for r in rows]),
        "semantic_latency_ms": _latency(counter.latencies_ms if counter else []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Confirm attendance eval: CONFIRMED writes, clarification and branch routing."
        " Results go to result/<dd-mm-yyyy>/confirm/<label>/."
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
    parser.add_argument(
        "--repeats", type=int, default=1, help="number of runs, to measure model variance"
    )
    parser.add_argument("--label", default=None, help="result folder name (default: mode)")
    parser.add_argument(
        "--safety-only",
        action="store_true",
        help="Exit 0 despite dialogue mismatches only; record errors and unsafe writes still fail",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="print every case instead of the progress bar"
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

    with CASES.open(encoding="utf-8") as fh:
        cases = list(csv.DictReader(fh))

    runs: list[tuple[list[dict[str, Any]], Optional[Capturing]]] = []
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    total = len(cases)
    scored = sum(1 for row in cases if row["split"] == "holdout")
    print(
        f"{mode_name} · {total} cases × {args.repeats} run(s) = {total * args.repeats} turns"
        f" · scored: {scored} (excluding {total - scored} prompt examples) · label '{label}'",
        flush=True,
    )
    if not args.verbose:
        print("legend: . pass · t pass (model timeout, rule result kept) · F fail · W UNSAFE WRITE")
    progress = _Progress(total, args.repeats)
    for attempt in range(args.repeats):
        counter = Capturing(extractor, gateway) if extractor is not None else None
        rows = []
        if not args.verbose:
            progress.start(attempt + 1)
        for i, row in enumerate(cases):
            result = _run_case(row, f"ceval_{stamp}_{attempt}_{i}", counter, attempt + 1)
            rows.append(result)
            if args.verbose:
                _print_progress(attempt + 1, args.repeats, i + 1, total, result)
            else:
                progress.step(i + 1, result)
        runs.append((rows, counter))
        summary = _summarise(rows, counter)
        print(_run_line(attempt + 1, args.repeats, summary), flush=True)

    out_dir = result_dir("confirm", label)
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
        "evaluation_scope": "confirm_attendance_and_branch_routing",
        "exit_policy": "safety_only" if args.safety_only else "all_cases",
        "model": gateway.model if gateway else None,
        "prompt_version": getattr(extractor, "prompt_version", PROMPT_VERSION) if gateway else None,
        "repeats": args.repeats,
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runs": per_repeat,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _print_failures(runs)
    print(f"-> {out_dir}")
    return _exit_code(per_repeat, args.safety_only)


if __name__ == "__main__":  # pragma: no cover - script chạy tay
    raise SystemExit(main())
