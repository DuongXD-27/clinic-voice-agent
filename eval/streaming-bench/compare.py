"""Compare completed replay runs only when audio, references and shared config match."""

import argparse
import csv
import json
from pathlib import Path
from types import SimpleNamespace

from bench import write_report

TEXT_FIELDS = {
    "case_id",
    "provider",
    "model",
    "mode",
    "category",
    "condition",
    "label_source",
    "audio_sha256",
    "reference",
    "asr_text",
    "turn_text",
    "error",
    "latency_reference",
}


def read_rows(path):
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as source:
        for raw in csv.DictReader(source):
            row = {}
            for key, value in raw.items():
                if key in TEXT_FIELDS:
                    row[key] = value
                elif key == "drop_reasons":
                    row[key] = json.loads(value)
                elif value in {"True", "False"}:
                    row[key] = value == "True"
                elif not value:
                    row[key] = None
                else:
                    row[key] = float(value)
            rows.append(row)
    return rows


def compare(runs, out):
    rows = []
    shared = None
    providers = {}
    sources = []
    for run in runs:
        metadata = json.loads((run / "summary.json").read_text())["metadata"]
        frozen = {
            k: metadata[k]
            for k in [
                "schema",
                "realtime_speed",
                "frame_ms",
                "prefix_ms",
                "tail_ms",
                "settings",
                "code_sha256",
            ]
        }
        if shared is not None and frozen != shared:
            raise ValueError(
                "Runs have different replay code or shared settings; rerun under one frozen configuration"
            )
        shared = frozen
        providers.update(metadata["providers"])
        sources.append(str(run.resolve()))
        rows.extend(read_rows(run / "cases.csv"))
    keys = [(r["provider"], r["mode"], r["case_id"]) for r in rows]
    if not rows or len(set(keys)) != len(keys):
        raise ValueError("Empty runs or duplicate provider/mode/case results")
    signatures = {}
    for row in rows:
        if row["latency_reference"] == "annotated_speech" and "speech_end_ms" not in row:
            raise ValueError(
                "These archived runs lack explicit speech offsets; use one paired run for annotated manifests"
            )
        key = row["provider"]
        signatures.setdefault(key, {})[(row["mode"], row["case_id"])] = (
            row["audio_sha256"],
            row["reference"],
            row["source_rate"],
            row["latency_reference"],
            row.get("speech_start_ms"),
            row.get("speech_end_ms"),
        )
    if any(signature != next(iter(signatures.values())) for signature in signatures.values()):
        raise ValueError(
            "Providers must have identical case sets, audio hashes, references and boundary labels"
        )
    if len(signatures) < 2:
        raise ValueError("Comparison needs two different providers")
    if out.exists() and any(out.iterdir()):
        raise ValueError("Output directory must be empty")
    metadata = {**shared, "providers": providers, "source_runs": sources}
    options = SimpleNamespace(
        out=out, providers=sorted(signatures), modes=sorted({r["mode"] for r in rows})
    )
    write_report(rows, options, metadata)
    print(out / "comparison.md")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        compare(args.runs, args.out)
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
