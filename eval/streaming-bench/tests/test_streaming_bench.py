import importlib.util
import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from speech.audio.codec import encode_wav
from speech.settings import SpeechSettings
from speech.types import AudioSegment, TranscriptEvent

_PATH = Path(__file__).resolve().parents[1] / "bench.py"
_SPEC = importlib.util.spec_from_file_location("streaming_bench_test", _PATH)
bench = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = bench
_SPEC.loader.exec_module(bench)


def case(tmp_path, reference="không đồng ý", *, critical=True):
    path = tmp_path / "clip.wav"
    path.write_bytes(encode_wav(AudioSegment(pcm=b"\x00\x10" * 1920, sample_rate=16000)))
    gold = bench.golden.GoldenCase(
        id="test",
        audio="clip.wav",
        audio_path=path,
        category="confirmation",
        reference=reference,
        critical_entities=(),
        critical=critical,
        should_produce_text=bool(reference),
    )
    return bench.Case(gold)


def args(tmp_path):
    return SimpleNamespace(
        prefix_ms=0,
        tail_ms=90,
        frame_ms=30,
        rate=16000,
        drain_timeout_s=1,
        out=tmp_path / "results",
        providers=["zipformer", "gemini_live"],
        modes=["pipeline"],
    )


class SlowASR:
    name = "zipformer"
    model = "fake"
    input_sample_rate = 16000
    supports_stream_context = False

    def __init__(self, *, text="không đồng ý", fail=False):
        self.text = text
        self.fail = fail
        self.audio = bytearray()

    async def stream(self, frames, **kwargs):
        import asyncio

        async for item in frames:
            self.audio.extend(item)
            await asyncio.sleep(0.06)
        if self.fail:
            raise RuntimeError("private upstream payload must not be logged")
        yield TranscriptEvent(text=self.text, is_final=True)


def test_scoring_preserves_diacritics_and_negation(tmp_path):
    c = case(tmp_path)
    assert bench.text_scores(c.gold, "Không đồng ý.")["content_pass"]
    wrong = bench.text_scores(c.gold, "đồng ý")
    assert wrong["wer"] == pytest.approx(1 / 3)
    assert not wrong["negation_pass"]
    assert not wrong["content_pass"]
    assert bench.text_scores(c.gold, "khong dong y")["cer"] > 0
    positive = case(tmp_path, "tôi đồng ý")
    assert not bench.text_scores(positive.gold, "tôi không đồng ý")["negation_pass"]


async def test_realtime_feed_is_independent_of_slow_decode_and_keeps_last_samples(tmp_path):
    c = case(tmp_path)
    inner = SlowASR()
    events = io.StringIO()
    row = await bench.replay(
        c, inner, SpeechSettings(sample_rate=16000), args(tmp_path), "asr", events
    )
    assert bytes(inner.audio) == b"\x00\x10" * 1920
    assert row["max_queue_frames"] > 1
    assert row["audio_ms"] == 120
    assert row["asr_content_pass"]
    assert not row["missing_final"]
    assert row["latency_reference"] == "file_end_proxy"
    assert '"client_end_queued"' in events.getvalue()


async def test_errors_remain_in_quality_denominator_and_hide_upstream_payload(tmp_path):
    c = case(tmp_path)
    events = io.StringIO()
    row = await bench.replay(
        c, SlowASR(fail=True), SpeechSettings(sample_rate=16000), args(tmp_path), "asr", events
    )
    summary = bench.summarize([row])
    assert summary["asr"]["micro_wer"] == 1
    assert summary["asr"]["content_pass"] == 0
    assert summary["errors"] == summary["missing_final"] == 1
    assert "private upstream" not in events.getvalue()
    assert summary["final_latency_ms"]["n"] == 0


async def test_pipeline_tap_records_final_and_turn_without_constructing_tts(tmp_path, monkeypatch):
    import speech.bundle

    def forbidden(*args, **kwargs):
        raise AssertionError("Evaluation must not build a paid TTS provider")

    monkeypatch.setattr(speech.bundle, "create_tts_gateway", forbidden)
    settings = SpeechSettings(
        vad_provider="energy",
        turn_validator_enabled=False,
        turn_min_speech_ms=0,
        vad_end_silence_ms=60,
        turn_post_bot_guard_ms=0,
    )
    c = case(tmp_path)
    row = await bench.replay(c, SlowASR(), settings, args(tmp_path), "pipeline", io.StringIO())
    assert not row["error"]
    assert row["asr_text"] == row["turn_text"] == "không đồng ý"
    assert row["turn_count"] == 1
    assert row["turn_content_pass"]


def test_pm_excludes_unresolved_and_helper_audio_and_applies_human_correction(
    tmp_path, monkeypatch
):
    import csv

    root = tmp_path / "temp/PM_Public_Eval_STT"
    audio = root / "01_audio_goc/Ha_Noi/S01"
    audio.mkdir(parents=True)
    records = []
    for identifier in ["B-HOLD-01", "B-AUD-RATE", "B-OVER-01-CHEN", "B-VM-01", "B-SIL-01"]:
        filename = identifier + "_S01.wav"
        (audio / filename).write_bytes(
            encode_wav(AudioSegment(pcm=b"\x00\x00" * 1600, sample_rate=16000))
        )
        records.append(
            {"id": identifier, "file": filename, "dieu_kien": "sach", "cau_chuan": "original"}
        )
    with (root / "manifest.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    (root / "loi_da_chot.csv").write_text(
        "file,cau_thuc_te\nB-VM-01_S01.wav,xin hãy để lại lời nhắn\n"
    )
    monkeypatch.setattr(bench, "ROOT", tmp_path)
    opts = SimpleNamespace(
        manifest=None, dataset="pm", pm_clean=True, pm_rate=16000, case=None, limit=None
    )
    cases, excluded = bench.load_cases(opts)
    assert len(cases) == 2
    assert not any(
        c.gold.id.startswith(("B-HOLD-01", "B-AUD-RATE", "B-OVER-01-CHEN")) for c in cases
    )
    assert excluded
    vm = next(c for c in cases if c.gold.id == "B-VM-01_S01")
    assert "hãy" in vm.gold.reference
    assert vm.label_source == "human_override"
    silence = next(c for c in cases if c.gold.id == "B-SIL-01_S01")
    assert silence.gold.reference == ""
    assert not silence.gold.should_produce_text


def test_p95_requires_enough_observations_and_does_not_clamp_early_finals():
    assert bench.latency([-20, 10])["p95"] is None
    assert bench.latency([-20, 10])["negative_samples"] == 1
    assert bench.latency(list(range(20)))["p95"] == 18


async def test_archived_comparison_checks_same_audio_and_shared_config(tmp_path, monkeypatch):
    import json

    monkeypatch.syspath_prepend(str(_PATH.parent))
    import compare as comparator

    c = case(tmp_path)
    row = await bench.replay(
        c, SlowASR(), SpeechSettings(sample_rate=16000), args(tmp_path), "asr", io.StringIO()
    )
    snapshot = {
        "schema": "streaming-eval.v1",
        "realtime_speed": 1,
        "frame_ms": 30,
        "prefix_ms": 0,
        "tail_ms": 90,
        "settings": {},
        "code_sha256": {},
        "providers": {},
    }
    first, second = tmp_path / "a", tmp_path / "b"
    for provider, directory in [("zipformer", first), ("gemini_live", second)]:
        options = SimpleNamespace(out=directory, providers=[provider], modes=["asr"])
        bench.write_report([{**row, "provider": provider}], options, snapshot)
    comparator.compare([first, second], tmp_path / "matched")
    summary = json.loads((tmp_path / "matched/summary.json").read_text())
    assert len(summary["results"]) == 2
    csv_path = second / "cases.csv"
    csv_path.write_text(
        csv_path.read_text(encoding="utf-8-sig").replace(row["audio_sha256"], "different_audio"),
        encoding="utf-8-sig",
    )
    with pytest.raises(ValueError, match="audio hashes"):
        comparator.compare([first, second], tmp_path / "mismatch")
