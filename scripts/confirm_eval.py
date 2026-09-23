"""Đánh giá bước xác nhận (T-04): câu nào mở khóa lệnh ghi CONFIRMED / RESCHEDULED, câu nào hỏi đúng.

    python scripts/confirm_eval.py --baseline                 # chỉ luật, KHÔNG gọi API
    python scripts/confirm_eval.py --route-only               # luật + model giả trả None: đếm lượt gọi model
    python scripts/confirm_eval.py --semantic --repeats 3     # gọi model thật, cần OPENAI_API_KEY
    python scripts/eval_compare.py outputs/eval/confirm/<A> outputs/eval/confirm/<B>

Chạy tay, không nằm trong `pytest`. Mỗi câu chạy qua **Orchestrator thật + FakeClinicAPI** ở đúng câu
hỏi đang chờ (`question_id` trong bộ câu):
- `CONFIRM_READBACK`: outbound vừa xác minh, câu tóm tắt gộp đọc lại lịch (Figure 0);
- `ASK_INTENT`: sau khi người gọi nói "Không" ở câu tóm tắt (bot hỏi "đổi hay hủy");
- `SLOT_READBACK`: sau "tôi muốn đổi lịch" và "khung 1".

`expect_behaviour` liệt kê các hành vi chấp nhận được, ngăn bằng `|`; hành vi ĐẦU TIÊN là lý tưởng
(vd. câu kể bận: lý tưởng là hỏi đổi / hủy, đọc lại lịch vẫn chấp nhận được). Báo cáo tách:
- độ chính xác "chấp nhận được" và "lý tưởng" trên `holdout` (tập `prompt` là câu mẫu của prompt),
- số lần GHI SAI (lệnh ghi khi không có hành vi ghi nào được chấp nhận) — exit code 1 nếu > 0,
- tỷ lệ câu đồng ý thật không được ghi ngay, số lượt gọi model theo nhóm.
Mỗi dòng kết quả ghi nhãn model trả về (`semantic_kind`, `semantic_reason`, `semantic_intent`).

Kết quả ghi ra `outputs/eval/confirm/<label>/`. Transcript là dữ liệu tổng hợp, không có PII.
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
from cancel_eval import Counting, RecordingGateway, _latency  # noqa: E402
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
OUT_ROOT = ROOT / "outputs" / "eval" / "confirm"
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
        "expect_behaviour": row["expect_behaviour"],
        "observed_behaviour": observed,
        "behaviour_ok": observed in accepted,
        "ideal_ok": observed == accepted[0],
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


def _summarise(rows: list[dict[str, Any]], counter: Optional[Counting]) -> dict[str, Any]:
    holdout = [r for r in rows if r["split"] == "holdout"]
    by_group: dict[str, dict[str, int]] = {}
    for row in holdout:
        bucket = by_group.setdefault(row["group"], {"total": 0, "ok": 0, "ideal": 0, "routed": 0})
        bucket["total"] += 1
        bucket["ok"] += int(row["behaviour_ok"])
        bucket["ideal"] += int(row["ideal_ok"])
        bucket["routed"] += int(row["routed"])
    agree = [r for r in rows if r["expect_behaviour"].split("|")[0] in WRITE_BEHAVIOURS]
    statuses = dict(sorted(counter.statuses.items())) if counter else {}
    return {
        "cases": len(rows),
        "holdout_cases": len(holdout),
        "holdout_behaviour_accuracy": round(
            sum(r["behaviour_ok"] for r in holdout) / max(1, len(holdout)), 4
        ),
        "holdout_ideal": sum(r["ideal_ok"] for r in holdout),
        "unsafe_writes": sum(r["unsafe_write"] for r in rows),
        "unsafe": sorted({r["transcript"] for r in rows if r["unsafe_write"]}),
        "agree_cases": len(agree),
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
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--baseline", action="store_true", help="chỉ luật, không gọi API")
    mode.add_argument(
        "--route-only", action="store_true", help="model giả trả None: đếm lượt gọi, không gọi API"
    )
    mode.add_argument("--semantic", action="store_true", help="bật model thật (cần OPENAI_API_KEY)")
    parser.add_argument("--repeats", type=int, default=1, help="chạy lại để đo biến thiên")
    parser.add_argument("--label", default=None)
    args = parser.parse_args()

    mode_name = "semantic" if args.semantic else "route-only" if args.route_only else "baseline"
    label = args.label or mode_name
    extractor: Any = None
    gateway = None
    if args.semantic:
        extractor = _semantic_extractor(EngineSettings(semantic_fallback_enabled=True))
        if extractor is None:
            print("Không dựng được tầng ngữ nghĩa — kiểm tra cấu hình.", file=sys.stderr)
            return 2
        gateway = RecordingGateway(extractor._gateway)
        extractor._gateway = gateway
    elif args.route_only:
        extractor = NullSemantic()

    with CASES.open(encoding="utf-8") as fh:
        cases = list(csv.DictReader(fh))

    runs: list[tuple[list[dict[str, Any]], Optional[Capturing]]] = []
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    for attempt in range(args.repeats):
        counter = Capturing(extractor, gateway) if extractor is not None else None
        rows = [
            _run_case(row, f"ceval_{stamp}_{attempt}_{i}", counter, attempt + 1)
            for i, row in enumerate(cases)
        ]
        runs.append((rows, counter))
        summary = _summarise(rows, counter)
        print(
            f"lần {attempt + 1}: holdout {summary['holdout_behaviour_accuracy']}"
            f" · lý tưởng {summary['holdout_ideal']}/{summary['holdout_cases']}"
            f" · ghi sai {summary['unsafe_writes']}"
            f" · đồng ý bị đọc lại {summary['agree_reread_rate']}"
            f" · gọi model {summary['model_calls']} {summary['model_statuses']}"
        )

    out_dir = OUT_ROOT / label
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
    print(json.dumps(per_repeat[-1]["failures"], ensure_ascii=False, indent=2))
    print(f"-> {out_dir}")
    return 0 if all(run["unsafe_writes"] == 0 for run in per_repeat) else 1


if __name__ == "__main__":  # pragma: no cover - script chạy tay
    raise SystemExit(main())
