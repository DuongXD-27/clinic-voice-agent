"""Synthetic identity audit: offline by default; --ner enables configured name NER.

    python scripts/identity_eval.py --output outputs/eval/identity/results.csv
    python scripts/identity_eval.py --ner --groups suffix_other,greeting_with_name

This is a discovery set, not a held-out accuracy benchmark. Empty expected values mean
NONE; '*' marks a name boundary needing human review. Exit 1 reports known mismatches.
Dialogue state transitions are covered separately by test_identity_dialogue.py.
"""

from __future__ import annotations

import argparse
import csv
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from callbot.engine.extraction import InformationExtractor, QuestionId, TurnContext
from callbot.engine.extraction.greeting import is_greeting, is_identity_question
from callbot.engine.extraction.ner import NameNER
from callbot.engine.extraction.schema import VN_TZ
from callbot.engine.settings import EngineSettings
from inference.llm.gateway import create_gateway
from inference.llm.prompt.ner import PROMPT_VERSION

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 23, 9, 0, tzinfo=VN_TZ)
FIELDS = ("name", "greeting", "identity_question", "intent", "dob")


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
        fallback=NameNER(gateway) if gateway else None, name_fallback=gateway is not None
    )
    with path.open(encoding="utf-8-sig", newline="") as source:
        cases = list(csv.DictReader(source))
    results = []
    for case in cases:
        if groups is not None and case["group"] not in groups:
            continue
        context = TurnContext(
            turn=1,
            question_id=QuestionId(case["question_id"]),
            direction="inbound",
            now=NOW,
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
                **{f"actual_{field}": value for field, value in actual.items()},
                "name_source": extraction.full_name.provenance.value,
                "ner_called": str(int(called)),
                "ner_transport_status": gateway.status if called else "not_called",
                "elapsed_ms": str(elapsed_ms),
                "mode": "ner" if gateway else "rules",
                "model": gateway.model if gateway else "",
                "prompt_version": PROMPT_VERSION if gateway else "",
                "status": "FAIL" if mismatches else "REVIEW" if review else "PASS",
                "mismatches": ";".join(mismatches),
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=ROOT / "eval/identity/cases.csv")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--ner", action="store_true", help="Call configured NAME_FALLBACK_PROVIDER; uses API quota"
    )
    parser.add_argument(
        "--groups", help="Comma-separated groups; omit for the complete discovery set"
    )
    args = parser.parse_args()
    gateway = None
    if args.ner:
        settings = EngineSettings()
        if settings.name_fallback_provider == "none":
            parser.error("--ner requires NAME_FALLBACK_PROVIDER to be configured")
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
            f"NER: {gateway.provider_name}/{gateway.model}; {gateway.calls} requests; {PROMPT_VERSION}"
        )
    for group, counts in groups.items():
        print(f"  {group}: {dict(counts)}")
    for row in results:
        if row["status"] == "FAIL":
            print(f"  {row['id']}: mismatch in {row['mismatches']}")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=list(results[0]) if results else [])
            writer.writeheader()
            writer.writerows(results)
        print(f"Results: {args.output}")
    return 1 if total["FAIL"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
