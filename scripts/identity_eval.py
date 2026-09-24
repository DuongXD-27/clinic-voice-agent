"""Synthetic identity audit: offline by default; --slot-filling enables name slot filling.

    python scripts/identity_eval.py
    python scripts/identity_eval.py --slot-filling --groups suffix_other,greeting_with_name

`--ner` remains a compatibility alias for `--slot-filling`. Each case may set `bot_question`,
the pending question the bot actually said; empty means the inbound opening greeting, since
every case is turn 1 of an inbound call. The question is sent only for ASK_NAME cases.

This is a discovery set, not a held-out accuracy benchmark. Empty expected values mean
NONE; '*' marks a name boundary needing human review. Exit 1 reports known mismatches.
Dialogue state transitions are covered separately by test_identity_dialogue.py.
Results default to result/<dd-mm-yyyy>/identity/<baseline|slot_filling>/results.csv (Vietnam
time). A summary.json is written beside the CSV, including counts, failures and transport status.
Report columns keep their ner_* names so older result files stay comparable.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from callbot.engine.dialogue import templates
from callbot.engine.extraction import InformationExtractor, QuestionId, TurnContext
from callbot.engine.extraction.greeting import is_greeting, is_identity_question
from callbot.engine.extraction.name_slot_filling import NameSlotFiller
from callbot.engine.extraction.schema import VN_TZ
from callbot.engine.settings import EngineSettings
from inference.llm.gateway import create_gateway
from inference.llm.prompt.name_slot_filling import PROMPT_VERSION

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 23, 9, 0, tzinfo=VN_TZ)
FIELDS = ("name", "greeting", "identity_question", "intent", "dob")
DIRECTION = "inbound"
MODE = "slot_filling"


class RecordingGateway:
    """Record request status only; never output credentials or raw provider responses."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.calls = 0
        self.status = "not_called"

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def generate_structured(self, *args: Any, **kwargs: Any):
        self.calls += 1
        self.status = "error"
        reply = self.inner.generate_structured(*args, **kwargs)
        self.status = reply.status
        return reply


def evaluate(
    path: Path,
    gateway: RecordingGateway | None = None,
    groups: frozenset[str] | None = None,
) -> list[dict[str, str]]:
    extractor = InformationExtractor(
        fallback=NameSlotFiller(gateway) if gateway else None, name_fallback=gateway is not None
    )
    with path.open(encoding="utf-8-sig", newline="") as source:
        cases = list(csv.DictReader(source))
    results = []
    for case in cases:
        if groups is not None and case["group"] not in groups:
            continue
        question_id = QuestionId(case["question_id"])
        bot_question = bot_question_for(case, question_id)
        context = TurnContext(
            turn=1,
            question_id=question_id,
            direction=DIRECTION,
            now=NOW,
            question_text=bot_question,
        )
        transcript = case["transcript"]
        calls_before = gateway.calls if gateway else 0
        started = time.perf_counter()
        extraction = extractor.extract(context, transcript)
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        called = gateway is not None and gateway.calls > calls_before
        actual = {
            "name": extraction.full_name.value or "",
            "greeting": str(int(is_greeting(transcript))),
            "identity_question": str(int(is_identity_question(transcript))),
            "intent": extraction.intent.value.value,
            "dob": str(extraction.dob.value) if extraction.dob.value is not None else "",
        }
        mismatches = [
            field
            for field in FIELDS
            if case[f"expect_{field}"] != "*" and case[f"expect_{field}"] != actual[field]
        ]
        review = any(case[f"expect_{field}"] == "*" for field in FIELDS)
        results.append(
            {
                **case,
                "bot_question": bot_question or "",
                **{f"actual_{field}": value for field, value in actual.items()},
                "name_source": extraction.full_name.provenance.value,
                "ner_called": str(int(called)),
                "ner_transport_status": gateway.status if called else "not_called",
                "elapsed_ms": str(elapsed_ms),
                "mode": MODE if gateway else "rules",
                "fallback_method": MODE if gateway else "",
                "model": gateway.model if gateway else "",
                "prompt_version": PROMPT_VERSION if gateway else "",
                "status": "FAIL" if mismatches else "REVIEW" if review else "PASS",
                "mismatches": ";".join(mismatches),
            }
        )
    return results


def bot_question_for(case: dict[str, str], question_id: QuestionId) -> str | None:
    """Pending question text as the orchestrator would pass it: ASK_NAME only."""
    if question_id is not QuestionId.ASK_NAME:
        return None
    return case.get("bot_question") or templates.greeting(DIRECTION)


def summarise(results: list[dict[str, str]]) -> dict[str, Any]:
    """Summarise saved rows without rerunning extraction or making model requests."""
    counts = Counter(row["status"] for row in results)
    scored = counts["PASS"] + counts["FAIL"]
    groups: dict[str, Counter] = defaultdict(Counter)
    for row in results:
        groups[row["group"]][row["status"]] += 1
    called = [row for row in results if row["ner_called"] == "1"]
    return {
        "evaluation_scope": "identity_extraction",
        "limitations": "Synthetic discovery set, not held-out accuracy or dialogue compliance. REVIEW rows excluded from pass rate; transport errors are not model-quality evidence.",
        "mode": results[0]["mode"] if results else None,
        "fallback_method": results[0].get("fallback_method") or None if results else None,
        "models": sorted({row["model"] for row in results if row["model"]}),
        "prompt_versions": sorted(
            {row["prompt_version"] for row in results if row["prompt_version"]}
        ),
        "cases": len(results),
        "scored_cases": scored,
        "passed_cases": counts["PASS"],
        "failed_cases": counts["FAIL"],
        "review_cases": counts["REVIEW"],
        "pass_rate": round(counts["PASS"] / scored, 4) if scored else None,
        "by_group": {group: dict(totals) for group, totals in sorted(groups.items())},
        "mismatch_counts": dict(
            Counter(field for row in results for field in row["mismatches"].split(";") if field)
        ),
        "ner_called_cases": len(called),
        "ner_transport_statuses": dict(Counter(row["ner_transport_status"] for row in called)),
        "failures": [
            {
                key: row[key]
                for key in ("id", "group", "transcript", "mismatches", "ner_transport_status")
            }
            for row in results
            if row["status"] == "FAIL"
        ],
        "review_ids": [row["id"] for row in results if row["status"] == "REVIEW"],
    }


def write_summary(results: list[dict[str, str]], output: Path) -> Path:
    summary_path = output.with_name("summary.json")
    report = {
        **summarise(results),
        "source_results": str(output.resolve()),
        "results_modified_at": datetime.fromtimestamp(output.stat().st_mtime, VN_TZ).isoformat(
            timespec="seconds"
        ),
        "generated_at": datetime.now(VN_TZ).isoformat(timespec="seconds"),
    }
    summary_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=ROOT / "eval/identity/cases.csv")
    parser.add_argument(
        "--output",
        type=Path,
        help="Override result/<dd-mm-yyyy>/identity/<baseline|slot_filling>/results.csv",
    )
    parser.add_argument(
        "--slot-filling",
        "--ner",
        dest="slot_filling",
        action="store_true",
        help="Call configured NAME_FALLBACK_PROVIDER for name slot filling; uses API quota "
        "(--ner is a compatibility alias)",
    )
    parser.add_argument(
        "--groups", help="Comma-separated groups; omit for the complete discovery set"
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    output = args.output or (
        ROOT
        / "result"
        / datetime.now(VN_TZ).strftime("%d-%m-%Y")
        / "identity"
        / (MODE if args.slot_filling else "baseline")
        / "results.csv"
    )
    gateway = None
    if args.slot_filling:
        settings = EngineSettings()
        if settings.name_fallback_provider == "none":
            parser.error("--slot-filling requires NAME_FALLBACK_PROVIDER to be configured")
        gateway = RecordingGateway(create_gateway(settings.name_fallback_provider))
    results = evaluate(
        args.cases, gateway, frozenset(args.groups.split(",")) if args.groups else None
    )
    if not results:
        parser.error("No matching cases")
    groups: dict[str, Counter] = defaultdict(Counter)
    for row in results:
        groups[row["group"]][row["status"]] += 1
    total = Counter(row["status"] for row in results)
    print(f"Synthetic discovery set: {len(results)} cases; {dict(total)}")
    if gateway:
        print(
            f"Slot filling: {gateway.provider_name}/{gateway.model}; "
            f"{gateway.calls} requests; {PROMPT_VERSION}"
        )
    for group, counts in groups.items():
        print(f"  {group}: {dict(counts)}")
    for row in results:
        if row["status"] == "FAIL":
            print(f"  {row['id']}: mismatch in {row['mismatches']}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    print(f"Results: {output}")
    print(f"Summary: {write_summary(results, output)}")
    return 1 if total["FAIL"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
