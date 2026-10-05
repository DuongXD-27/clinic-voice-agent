"""Paired real-time ASR and turn-boundary evaluation; no virtual clock or TTS calls."""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import importlib.util
import json
import math
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "eval/stt-bench"))
spec = importlib.util.spec_from_file_location(
    "_streaming_golden", ROOT / "eval/stt-bench/evaluate.py"
)
golden = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = golden
spec.loader.exec_module(golden)

from callbot.transports.livekit.settings import LiveKitSettings  # noqa: E402
from inference.asr import create_asr_gateway  # noqa: E402
from speech.asr.recognizer import SpeechRecognizer  # noqa: E402
from speech.audio.codec import read_wav, to_sample_rate  # noqa: E402
from speech.bundle import build_streaming_bundle  # noqa: E402
from speech.settings import SpeechSettings  # noqa: E402
from speech.turn.controller import TurnController  # noqa: E402

END = object()
NEGATIONS = {"không", "chưa", "chẳng", "đừng"}


@dataclass
class Case:
    gold: object
    condition: str = "unspecified"
    speech_start_ms: float = 0
    speech_end_ms: float | None = None
    label_source: str = "dataset"


def load_cases(args):
    excluded = []
    if args.manifest:
        cases = []
        for line in args.manifest.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            case = golden.GoldenCase(
                id=row["id"],
                audio=row["audio"],
                audio_path=(args.manifest.parent / row["audio"]).resolve(),
                category=row.get("category", "custom"),
                reference=row["reference"],
                critical_entities=tuple(
                    golden.CriticalEntity(**e) for e in row.get("critical_entities", [])
                ),
                critical=row.get("critical", False),
                should_produce_text=row.get("should_produce_text", bool(row["reference"])),
            )
            cases.append(
                Case(
                    case,
                    row.get("condition", "unspecified"),
                    row.get("speech_start_ms", 0),
                    row.get("speech_end_ms"),
                    row.get("label_source", "custom"),
                )
            )
    elif args.dataset == "pm":
        root = ROOT / "temp/PM_Public_Eval_STT"
        with (root / "loi_da_chot.csv").open(encoding="utf-8-sig") as f:
            overrides = {r["file"]: r["cau_thuc_te"] for r in csv.DictReader(f)}
        with (root / "manifest.csv").open(encoding="utf-8-sig") as f:
            manifest = list(csv.DictReader(f))
        cases = []
        for row in manifest:
            if row["id"] in {"B-HOLD-01", "B-AUD-RATE", "B-OVER-01-CHEN"} or row["dieu_kien"] in {
                "matdau",
                "chong",
            }:
                excluded.append({"file": row["file"], "reason": "unresolved_label_or_helper"})
                continue
            if args.pm_clean and row["dieu_kien"] not in {"sach", "im"}:
                continue
            speech = row["id"] != "B-SIL-01"
            reference = overrides.get(row["file"], row["cau_chuan"]) if speech else ""
            # VM correction applies to all variants of the same original recording.
            if row["id"] == "B-VM-01":
                reference = overrides["B-VM-01_S01.wav"]
            folder = "01_audio_goc" if args.pm_rate == 16000 else "01_audio_8k"
            case = golden.GoldenCase(
                id=Path(row["file"]).stem,
                audio=row["file"],
                audio_path=root / folder / "Ha_Noi/S01" / row["file"],
                category=row["id"].rsplit("-", 1)[0],
                reference=reference,
                critical_entities=(),
                critical=speech,
                should_produce_text=speech,
            )
            cases.append(
                Case(
                    case,
                    row["dieu_kien"],
                    label_source=(
                        "human_override" if row["id"] == "B-VM-01" else "PM_script_reference"
                    ),
                )
            )
    else:
        cases = [Case(c, "golden_8k") for c in golden.load_dataset(golden.DEFAULT_DATASET).cases]
    if args.case:
        selected = set(args.case)
        missing = selected - {c.gold.id for c in cases}
        if missing:
            raise ValueError(f"Unknown/excluded case IDs: {sorted(missing)}")
        cases = [c for c in cases if c.gold.id in selected]
    if args.limit:
        cases = cases[: args.limit]
    if not cases or len({c.gold.id for c in cases}) != len(cases):
        raise ValueError("Dataset must contain nonempty, unique case IDs")
    for c in cases:
        segment, _ = read_wav(c.gold.audio_path.read_bytes())
        duration = len(segment.pcm) / 2 / segment.sample_rate * 1000
        end = c.speech_end_ms if c.speech_end_ms is not None else duration
        if duration <= 0 or not 0 <= c.speech_start_ms <= end <= duration:
            raise ValueError(f"Invalid WAV or speech boundaries: {c.gold.id}")
    return cases, excluded


def text_scores(case, text):
    score = golden.evaluate_case(case, golden.STTResult(text=text))
    ref = golden.normalize_for_wer(case.reference)
    hyp = golden.normalize_for_wer(text)
    chars_ref, chars_hyp = ref.replace(" ", ""), hyp.replace(" ", "")
    previous = list(range(len(chars_hyp) + 1))
    for i, ch in enumerate(chars_ref, 1):
        current = [i]
        for j, other in enumerate(chars_hyp, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (ch != other)))
        previous = current
    negation_pass = [w for w in ref.split() if w in NEGATIONS] == [
        w for w in hyp.split() if w in NEGATIONS
    ]
    critical_pass = score.critical_entities_pass
    if case.critical and not case.critical_entities:
        # Without hand-labeled entities, use strict full-text accuracy, never infer intent.
        critical_pass = ref == hyp
    return {
        "wer": score.wer.wer,
        "word_errors": score.wer.substitutions + score.wer.deletions + score.wer.insertions,
        "reference_words": score.wer.reference_word_count,
        "cer": previous[-1] / len(chars_ref) if chars_ref else None,
        "character_errors": previous[-1],
        "reference_characters": len(chars_ref),
        "exact_match": ref == hyp,
        "negation_pass": negation_pass,
        "critical_pass": critical_pass,
        "hallucination": score.hallucination,
        "content_pass": not score.hallucination
        and negation_pass
        and (not case.should_produce_text or bool(hyp))
        and (not case.critical or critical_pass),
    }


class NoTTS:
    """Gateway used only by this replay; production bundle construction stays unchanged."""

    def synthesize(self, text):
        raise AssertionError("STT evaluation must not synthesize audio")

    async def aclose(self):
        pass


class RecordingController(TurnController):
    """Observe controller resets locally; no measurement callbacks in production."""

    def __init__(self, record, **kwargs):
        self._record = record
        super().__init__(**kwargs)

    def _reset_candidate(self):
        if self._candidate.text.strip() and not self._candidate.finalized:
            self._record("decision", decision="DROPPED", reason="controller_reset")
        super()._reset_candidate()

    def _try_emit(self, **kwargs):
        emitted = super()._try_emit(**kwargs)
        if emitted:
            self._record("decision", decision="EMITTED", reason="controller_emit")
        return emitted


class AlwaysSpeech:
    def is_speech(self, pcm):
        return True


class Tap:
    def __init__(self, inner, record):
        self.inner = inner
        self.record = record
        self.name, self.model = inner.name, inner.model
        self.input_sample_rate = inner.input_sample_rate
        self.supports_stream_context = inner.supports_stream_context

    async def stream(self, frames, **kwargs):
        async for event in self.inner.stream(frames, **kwargs):
            self.record(
                "asr_final" if event.is_final else "asr_partial",
                text=event.text,
                generation=event.generation,
                segment_id=event.segment_id,
            )
            yield event


async def replay(case, inner, settings, args, mode, events_file):
    source, info = read_wav(case.gold.audio_path.read_bytes())
    audio = to_sample_rate(source, args.rate)
    duration_ms = len(audio.pcm) / 2 / audio.sample_rate * 1000
    prefix_ms = args.prefix_ms if mode == "pipeline" else 0
    pcm = b"\x00\x00" * (audio.sample_rate * prefix_ms // 1000) + audio.pcm
    if mode == "pipeline":
        pcm += b"\x00\x00" * (audio.sample_rate * args.tail_ms // 1000)
    loop = asyncio.get_running_loop()
    start = loop.time()
    events = []
    feed = {"audio_ms": 0.0, "max_queue_frames": 0, "max_pacing_lag_ms": 0.0}

    def record(kind, **data):
        entry = {
            "case_id": case.gold.id,
            "provider": inner.name,
            "mode": mode,
            "wall_ms": round((loop.time() - start) * 1000, 3),
            "audio_fed_ms": round(feed["audio_ms"], 3),
            "kind": kind,
            **data,
        }
        events.append(entry)
        events_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        events_file.flush()

    queue = asyncio.Queue(maxsize=1000)
    frame_bytes = audio.sample_rate * args.frame_ms // 1000 * 2

    async def producer():
        for offset in range(0, len(pcm), frame_bytes):
            target = offset / 2 / audio.sample_rate
            await asyncio.sleep(max(0, start + target - loop.time()))
            chunk = pcm[offset : offset + frame_bytes]
            feed["max_pacing_lag_ms"] = max(
                feed["max_pacing_lag_ms"], (loop.time() - start - target) * 1000
            )
            await queue.put(chunk)
            feed["audio_ms"] = (offset + len(chunk)) / 2 / audio.sample_rate * 1000
            feed["max_queue_frames"] = max(feed["max_queue_frames"], queue.qsize())
            record("audio", bytes=len(chunk))
        await asyncio.sleep(max(0, start + len(pcm) / 2 / audio.sample_rate - loop.time()))
        if mode == "asr":
            record("client_end_queued")
        await queue.put(END)

    async def frames():
        while True:
            item = await queue.get()
            if item is END:
                return
            yield item

    tap = Tap(inner, record)
    controller = None
    bundle = None
    producer_task = asyncio.create_task(producer())
    error = ""
    try:
        async with asyncio.timeout(len(pcm) / 2 / audio.sample_rate + args.drain_timeout_s):
            if mode == "asr":
                async for _ in tap.stream(
                    frames(), audio_sample_rate=audio.sample_rate, silence_classifier=AlwaysSpeech()
                ):
                    pass
            else:
                livekit = LiveKitSettings()
                with patch("speech.bundle.create_tts_gateway", return_value=NoTTS()):
                    bundle = build_streaming_bundle(
                        settings,
                        asr=tap,
                        sample_rate=args.rate,
                        frame_ms=args.frame_ms,
                        input_queue_ms=livekit.input_queue_ms,
                        asr_queue_ms=livekit.asr_queue_ms,
                        barge_in_preroll_ms=livekit.barge_in_preroll_ms,
                    )
                controller = RecordingController(
                    record,
                    min_speech_ms=settings.turn_min_speech_ms,
                    max_wait_after_vad_end_ms=settings.turn_max_wait_after_vad_end_ms,
                    max_wait_for_asr_ms=settings.turn_max_wait_for_asr_ms,
                    post_bot_guard_ms=settings.turn_post_bot_guard_ms,
                    validator=bundle.validator,
                )
                async for turn in bundle.stt_pipeline.stream(
                    frames(),
                    turn_controller=controller,
                ):
                    record("turn", text=turn.text)
            await producer_task
    except Exception as exc:
        # Provider sanitizes upstream errors; do not expose arbitrary exception payloads.
        error = type(exc).__name__
        if isinstance(exc, RuntimeError) and str(exc).startswith("Gemini Live STT"):
            error += ": " + str(exc)
        record("error", error=error)
    finally:
        producer_task.cancel()
        await asyncio.gather(producer_task, return_exceptions=True)
        if controller:
            await controller.aclose()
        if bundle:
            await bundle.tts.aclose()
    finals = [e for e in events if e["kind"] == "asr_final" and e["text"].strip()]
    turns = [e for e in events if e["kind"] == "turn" and e["text"].strip()]
    partials = [e for e in events if e["kind"] == "asr_partial" and e["text"].strip()]
    reference_offset = prefix_ms + (
        case.speech_end_ms if case.speech_end_ms is not None else duration_ms
    )
    onset = prefix_ms + case.speech_start_ms
    final_text = " ".join(e["text"].strip() for e in finals)
    turn_text = " ".join(e["text"].strip() for e in turns)
    scores = {"asr": text_scores(case.gold, final_text), "turn": text_scores(case.gold, turn_text)}
    if error:
        for value in scores.values():
            value["content_pass"] = False
    revisions = 0
    for a, b in zip(partials, partials[1:], strict=False):
        edits = golden.calculate_wer(a["text"], b["text"])
        revisions += edits.substitutions + edits.deletions + edits.insertions
    return {
        "case_id": case.gold.id,
        "provider": inner.name,
        "model": inner.model,
        "mode": mode,
        "category": case.gold.category,
        "condition": case.condition,
        "source_rate": info.sample_rate,
        "pipeline_rate": audio.sample_rate,
        "label_source": case.label_source,
        "audio_sha256": hashlib.sha256(case.gold.audio_path.read_bytes()).hexdigest(),
        "should_produce_text": case.gold.should_produce_text,
        "critical": case.gold.critical,
        "has_negation": any(
            w in NEGATIONS for w in golden.normalize_for_wer(case.gold.reference).split()
        ),
        "reference": case.gold.reference,
        "asr_text": final_text,
        "turn_text": turn_text,
        "error": error,
        "missing_final": case.gold.should_produce_text and not finals,
        "missing_turn": case.gold.should_produce_text and not turns if mode == "pipeline" else None,
        "dropped_after_asr": bool(finals) and not turns if mode == "pipeline" else None,
        "false_turns": len(turns) if not case.gold.should_produce_text else 0,
        "extra_turns": max(0, len(turns) - 1),
        "final_count": len(finals),
        "turn_count": len(turns),
        "partial_count": len(partials),
        "partial_revision_edits": revisions,
        "first_partial_ms": partials[0]["wall_ms"] - onset if partials else None,
        "final_latency_ms": finals[-1]["wall_ms"] - reference_offset if finals else None,
        "turn_latency_ms": turns[-1]["wall_ms"] - reference_offset if turns else None,
        "latency_reference": "annotated_speech"
        if case.speech_end_ms is not None
        else "file_end_proxy",
        "audio_duration_ms": duration_ms,
        **feed,
        "drop_reasons": dict(
            Counter(
                e["reason"]
                for e in events
                if e["kind"] == "decision" and e["decision"] == "DROPPED"
            )
        ),
        **{
            f"{level}_{key}": value
            for level, values in scores.items()
            for key, value in values.items()
        },
    }


def latency(values):
    values = sorted(v for v in values if v is not None)

    def percentile(p):
        return values[min(len(values) - 1, math.ceil(len(values) * p) - 1)] if values else None

    return {
        "n": len(values),
        "p50": percentile(0.5),
        "p95": percentile(0.95) if len(values) >= 20 else None,
        "negative_samples": sum(v < 0 for v in values),
    }


def summarize(rows):
    out = {
        "cases": len(rows),
        "errors": sum(bool(r["error"]) for r in rows),
        "missing_final": sum(r["missing_final"] for r in rows),
        "missing_turn": sum(bool(r["missing_turn"]) for r in rows),
        "dropped_after_asr": sum(bool(r["dropped_after_asr"]) for r in rows),
        "false_turns": sum(r["false_turns"] for r in rows),
        "extra_turns": sum(r["extra_turns"] for r in rows),
        "speech_cases": sum(r["should_produce_text"] for r in rows),
        "nonspeech_cases": sum(not r["should_produce_text"] for r in rows),
    }
    for level in ["asr", "turn"]:
        words = sum(r[f"{level}_reference_words"] for r in rows)
        chars = sum(r[f"{level}_reference_characters"] for r in rows)
        out[level] = {
            "micro_wer": sum(r[f"{level}_word_errors"] for r in rows) / words if words else None,
            "micro_cer": sum(r[f"{level}_character_errors"] for r in rows) / chars
            if chars
            else None,
            "exact_match_rate": sum(r[f"{level}_exact_match"] and not r["error"] for r in rows)
            / len(rows),
            "content_pass": sum(r[f"{level}_content_pass"] for r in rows),
            "critical_failures": sum(
                r["critical"] and not r[f"{level}_critical_pass"] for r in rows
            ),
            "negation_failures": sum(not r[f"{level}_negation_pass"] for r in rows),
            "hallucination_cases": sum(r[f"{level}_hallucination"] for r in rows),
        }
    for field in ["first_partial_ms", "final_latency_ms", "turn_latency_ms"]:
        out[field] = latency(r[field] for r in rows if not r["error"])
    return out


def write_report(rows, args, metadata):
    args.out.mkdir(parents=True, exist_ok=True)
    summary = {}
    for provider in args.providers:
        for mode in args.modes:
            group = [r for r in rows if r["provider"] == provider and r["mode"] == mode]
            if not group:
                continue
            breakdown = {"overall": summarize(group)}
            for label, field in (
                ("category", "category"),
                ("condition", "condition"),
                ("rate", "source_rate"),
            ):
                breakdown[f"by_{label}"] = {
                    str(k): summarize([r for r in group if r[field] == k])
                    for k in sorted({r[field] for r in group})
                }
            summary[f"{provider}/{mode}"] = breakdown
    (args.out / "summary.json").write_text(
        json.dumps({"metadata": metadata, "results": summary}, ensure_ascii=False, indent=2) + "\n"
    )
    with (args.out / "cases.csv").open("w", newline="", encoding="utf-8-sig") as f:
        if rows:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(
                {
                    k: json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v
                    for k, v in row.items()
                }
                for row in rows
            )
    lines = [
        "# Gemini Live vs GipFormer — real-time replay",
        "",
        "Same WAV + shared pipeline settings; failures stay in quality denominators.",
        "",
        "| Provider/mode | n | ASR WER | Turn WER | ASR / turn pass | Missing final / turn | Errors | False turns | Final p50 / p95 ms | Turn p50 / p95 ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    def fmt(x):
        return "—" if x is None else f"{x:.1f}"

    for key, item in summary.items():
        s = item["overall"]
        lines.append(
            f"| {key} | {s['cases']} | {fmt(s['asr']['micro_wer'] * 100) if s['asr']['micro_wer'] is not None else '—'}% | "
            f"{fmt(s['turn']['micro_wer'] * 100) if s['turn']['micro_wer'] is not None and key.endswith('/pipeline') else '—'} | "
            f"{s['asr']['content_pass']} / {s['turn']['content_pass'] if key.endswith('/pipeline') else '—'} | "
            f"{s['missing_final']} / {s['missing_turn'] if key.endswith('/pipeline') else '—'} | {s['errors']} | {s['false_turns']} | "
            f"{fmt(s['final_latency_ms']['p50'])} / {fmt(s['final_latency_ms']['p95'])} | "
            f"{fmt(s['turn_latency_ms']['p50'])} / {fmt(s['turn_latency_ms']['p95'])} |"
        )
    lines += ["", "## Paired content regressions", ""]
    for mode in args.modes:
        a = {r["case_id"]: r for r in rows if r["provider"] == "zipformer" and r["mode"] == mode}
        b = {r["case_id"]: r for r in rows if r["provider"] == "gemini_live" and r["mode"] == mode}
        for level in ["asr", "turn"] if mode == "pipeline" else ["asr"]:
            improvements = [
                i
                for i in a.keys() & b.keys()
                if not a[i][f"{level}_content_pass"] and b[i][f"{level}_content_pass"]
            ]
            regressions = [
                i
                for i in a.keys() & b.keys()
                if a[i][f"{level}_content_pass"] and not b[i][f"{level}_content_pass"]
            ]
            lines.append(
                f"- {mode}/{level}: improved {len(improvements)} {sorted(improvements)}; regressed {len(regressions)} {sorted(regressions)}."
            )
    lines += [
        "",
        "Latency uses annotated speech offsets when supplied; otherwise WAV end is a proxy (may be negative with trailing silence).",
        "Latency covers completed events only; always read missing/error counts beside latency. p95 requires 20 observations.",
        "ASR mode uses annotated clip boundaries and forces speech admission. Pipeline mode preserves local VAD/turn gates.",
        "No LiveKit transport, browser DSP, TTS, interruption or business writes are evaluated. Turn = ready for engine input.",
        "PM references are scripted utterances plus one human correction; unresolved cases are excluded, not inferred from ASR.",
        "Silence/noise coverage and label review are required before replacing the baseline.",
    ]
    (args.out / "comparison.md").write_text("\n".join(lines) + "\n")


async def run(args, cases, excluded):
    settings = SpeechSettings()
    livekit = LiveKitSettings()
    metadata = {
        "schema": "streaming-eval.v1",
        "dataset": str(args.manifest or args.dataset),
        "realtime_speed": 1,
        "frame_ms": args.frame_ms,
        "prefix_ms": args.prefix_ms,
        "tail_ms": args.tail_ms,
        "excluded": excluded,
        "settings": {
            "livekit_queues": {
                key: getattr(livekit, key)
                for key in ("input_queue_ms", "asr_queue_ms", "barge_in_preroll_ms")
            },
            **{
                k: v
                for k, v in settings.model_dump(mode="json").items()
                if k.startswith(("vad_", "silero_", "turn_", "asr_")) and k != "asr_provider"
            },
        },
        "providers": {},
        "code_sha256": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [
                Path(__file__).resolve(),
                ROOT / "src/speech/bundle.py",
                ROOT / "src/speech/asr/pipeline.py",
                ROOT / "src/speech/turn/controller.py",
                ROOT / "src/inference/asr/providers/gemini_live.py",
                ROOT / "src/inference/asr/providers/zipformer.py",
            ]
        },
    }
    recognizers = {}
    for provider in args.providers:
        print(f"Preparing {provider}...", flush=True)
        gateway = create_asr_gateway(provider)
        recognizers[provider] = SpeechRecognizer(gateway)
        metadata["providers"][provider] = gateway.provider._config.model_dump(
            mode="json", exclude={"api_key"}
        )
        if provider == "zipformer":
            started = time.perf_counter()
            await asyncio.to_thread(
                gateway.transcribe,
                b"\x00\x00" * gateway.input_sample_rate,
                gateway.input_sample_rate,
            )
            metadata["providers"][provider]["warmup_ms"] = (time.perf_counter() - started) * 1000
        else:
            await gateway.provider.check_connection()
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    total = len(cases) * len(args.modes) * len(args.providers)
    with (args.out / "events.jsonl").open("w", encoding="utf-8") as events:
        for index, case in enumerate(cases):
            for mode in args.modes:
                # Alternate provider order to reduce systematic network/time drift.
                order = args.providers if index % 2 == 0 else list(reversed(args.providers))
                for provider in order:
                    row = await replay(case, recognizers[provider], settings, args, mode, events)
                    rows.append(row)
                    write_report(rows, args, metadata)
                    print(
                        f"[{len(rows)}/{total}] {case.gold.id} {provider}/{mode}: "
                        f"ASR pass={row['asr_content_pass']} turn pass={row['turn_content_pass']} "
                        f"error={row['error'] or '-'}",
                        flush=True,
                    )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=["golden", "pm"], default="golden")
    parser.add_argument(
        "--manifest", type=Path, help="Custom JSONL labels; audio relative to manifest"
    )
    parser.add_argument("--pm-clean", action="store_true")
    parser.add_argument("--pm-rate", type=int, choices=[8000, 16000], default=16000)
    parser.add_argument(
        "--providers",
        nargs="+",
        choices=["zipformer", "gemini_live"],
        default=["zipformer", "gemini_live"],
    )
    parser.add_argument("--modes", nargs="+", choices=["pipeline", "asr"], default=["pipeline"])
    parser.add_argument("--case", action="append")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--rate", type=int, choices=[8000, 16000], default=16000)
    parser.add_argument("--frame-ms", type=int, choices=[10, 20, 30], default=30)
    parser.add_argument("--prefix-ms", type=int, default=300)
    parser.add_argument("--tail-ms", type=int, default=2000)
    parser.add_argument("--drain-timeout-s", type=float, default=10)
    parser.add_argument("--out", type=Path, default=ROOT / "temp/streaming-eval")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if (
        args.prefix_ms < 0
        or args.tail_ms < 0
        or args.drain_timeout_s <= 0
        or (args.limit is not None and args.limit < 1)
    ):
        parser.error("Invalid padding, timeout or limit")
    if len(set(args.providers)) != len(args.providers) or len(set(args.modes)) != len(args.modes):
        parser.error("Providers and modes must be unique")
    cases, excluded = load_cases(args)
    print(
        f"Validated {len(cases)} cases; excluded {len(excluded)} unresolved/helper files.",
        flush=True,
    )
    if args.validate_only:
        return 0
    if args.out.exists() and any(args.out.iterdir()):
        parser.error("Output directory must be empty; use a new --out for each run")
    rows = asyncio.run(run(args, cases, excluded))
    print(f"Report: {args.out / 'comparison.md'}", flush=True)
    return 1 if any(r["error"] for r in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
