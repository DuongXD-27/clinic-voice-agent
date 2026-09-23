"""Đánh giá bước xác nhận (T-04): câu nào mở khóa lệnh ghi CONFIRMED / RESCHEDULED, câu nào hỏi đúng.

    python scripts/confirm_eval.py --baseline                 # chỉ luật, KHÔNG gọi API
    python scripts/confirm_eval.py --route-only               # luật + model giả trả None: đếm lượt gọi model
    python scripts/confirm_eval.py --semantic --repeats 3     # gọi model thật, cần OPENAI_API_KEY
    python scripts/eval_compare.py result/<dd-mm-yyyy>/confirm/<A> result/<dd-mm-yyyy>/confirm/<B>

Chạy tay, không nằm trong `pytest`. Mỗi câu chạy qua **Orchestrator thật + FakeClinicAPI** ở đúng câu
hỏi đang chờ (`question_id` trong bộ câu):
- `CONFIRM_READBACK`: outbound vừa xác minh, câu tóm tắt gộp đọc lại lịch (Figure 0);
- `ASK_INTENT`: sau khi người gọi nói "Không" ở câu tóm tắt (bot hỏi "đổi hay hủy");
- `SLOT_READBACK`: sau "tôi muốn đổi lịch" và "khung 1".

`expect_behaviour` là nhãn nghiệp vụ theo kiến trúc §3.2 (`O_AGREE`): đồng ý → `CONFIRM`; "không" hoặc
kể hoàn cảnh không đến được → `ASK_CHANGE_OR_CANCEL`; chưa rõ → `REREAD`. Dấu `|` chỉ dùng khi nghiệp
vụ chấp nhận cả hai (câu mơ hồ thật, hoặc câu ngụ ý đồng ý mà đọc lại vẫn đúng §1.1.3), không dùng để
chừa chỗ cho luật khi không có model. `needs_inference=yes`: ý người gọi phải suy ra từ hoàn cảnh, không
có từ khóa nói thẳng; chỉ luật thì được phép sai ở các câu này nhưng không được ghi. Báo cáo tách:
- độ chính xác trên `holdout` (tập `prompt` là câu mẫu của prompt), tách câu luật quyết được và câu
  cần suy nghĩa,
- số lần GHI SAI (lệnh ghi khi không có hành vi ghi nào được chấp nhận) — exit code 1 nếu > 0,
- tỷ lệ câu đồng ý thật không được ghi ngay, số lượt gọi model theo nhóm.
Mỗi dòng kết quả ghi nhãn model trả về (`semantic_kind`, `semantic_reason`, `semantic_intent`).

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
from tests.engine.fake_clinic import FakeClinicAPI  # noqa: E402

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
from inference.llm.prompt.semantic import PROMPT_VERSION  # noqa: E402

CASES = ROOT / "eval" / "confirm" / "cases.csv"
VERIFIED = ["Nguyễn Văn A", "14/03/1978"]
SETUP: dict[str, list[str]] = {
    QuestionId.CONFIRM_READBACK.value: [],
    QuestionId.ASK_INTENT.value: ["Không"],
    QuestionId.SLOT_READBACK.value: ["tôi muốn đổi lịch", "khung 1"],
}
WRITE_BEHAVIOURS = frozenset({"CONFIRM", "SLOT_WRITE"})

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


def _behaviour(action, ctx: Optional[CallContext], clinic: FakeClinicAPI, question: str) -> str:
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
    if action.utterance == t.ASK_CHANGE_OR_CANCEL:
        return "ASK_CHANGE_OR_CANCEL"
    if action.utterance == t.NOT_UNDERSTOOD:
        return "NOT_UNDERSTOOD"
    if asked is QuestionId.OFFER_SLOTS:
        return "RESCHEDULE"
    if asked is QuestionId.CANCEL_RECONFIRM:
        return "CANCEL"
    if question == QuestionId.SLOT_READBACK.value and ctx.pending_action is None:
        return "ABANDON"
    if asked is QuestionId.CONFIRM_READBACK:
        return "REREAD"
    if asked is QuestionId.SLOT_READBACK:
        return "ASK_AGAIN"
    return "OTHER"


def _run_case(
    row: dict[str, str], call_id: str, semantic: Optional[Capturing], repeat: int
) -> dict[str, Any]:
    clinic = FakeClinicAPI()
    bot = create_orchestrator(clinic, store=_store())
    bot._extractor._semantic = semantic
    bot.start_call(CallStart(call_id=call_id, direction="outbound", appointment_id="apt_00417"))
    lines = [*VERIFIED, *SETUP[row["question_id"]]]
    for turn, line in enumerate(lines, start=1):
        bot.handle_turn(call_id, CallerInput(turn=turn, text=line))
    raw = bot.sessions.store.get_session(call_id).context
    asked = CallContext.from_dict(raw).question if raw else None
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
    observed = _behaviour(action, ctx, clinic, row["question_id"])
    accepted = row["expect_behaviour"].split("|")
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
        "behaviour_ok": observed in accepted,
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
    if not row["behaviour_ok"]:
        return "F"
    return "t" if row["semantic_status"] == "timeout" else "."


def _print_progress(
    attempt: int, repeats: int, index: int, total: int, row: dict[str, Any]
) -> None:
    """`-v`: một dòng mỗi câu, in ngay (flush) để biết đang chạy câu nào khi có model."""
    mark = "PASS" if row["behaviour_ok"] else "FAIL"
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
            if row["behaviour_ok"]:
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
            f" (expected {row['expect_behaviour']}; runs {entry['runs']})"
        )


def _run_line(attempt: int, repeats: int, summary: dict[str, Any]) -> str:
    """ "run 1/3: passed 120/121 (99.2%) · unsafe writes 0 · ..." """
    passed, scored = summary["holdout_passed"], summary["holdout_cases"]
    statuses = ", ".join(f"{name} {count}" for name, count in summary["model_statuses"].items())
    model = f"model calls {summary['model_calls']}" + (f" ({statuses})" if statuses else "")
    return (
        f"run {attempt}/{repeats}: passed {passed}/{scored} ({passed / max(1, scored):.1%})"
        f" [rule {summary['rule_passed']}/{summary['rule_cases']}"
        f", inference {summary['inference_passed']}/{summary['inference_cases']}]"
        f" · unsafe writes {summary['unsafe_writes']}"
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
    inference = [r for r in holdout if r["needs_inference"]]
    rule = [r for r in holdout if not r["needs_inference"]]
    statuses = dict(sorted(counter.statuses.items())) if counter else {}
    return {
        "cases": len(rows),
        "holdout_cases": len(holdout),
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
                )
            }
            for r in holdout
            if not r["behaviour_ok"]
        ],
        "model_calls": counter.routed if counter else 0,
        "model_statuses": statuses,
        "turn_latency_ms": _latency([r["elapsed_ms"] for r in rows]),
        "semantic_latency_ms": _latency(counter.latencies_ms if counter else []),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Confirm-step eval: which answers unlock CONFIRMED / RESCHEDULED writes."
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
        "model": gateway.model if gateway else None,
        "prompt_version": PROMPT_VERSION if gateway else None,
        "repeats": args.repeats,
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runs": per_repeat,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _print_failures(runs)
    print(f"-> {out_dir}")
    return 0 if all(run["unsafe_writes"] == 0 for run in per_repeat) else 1


if __name__ == "__main__":  # pragma: no cover - script chạy tay
    raise SystemExit(main())
