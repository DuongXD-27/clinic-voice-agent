"""W4 handoff: verify/extract recorded evidence offline; --run-vbee opts into paid replay.

    python scripts/w4_voice_eval.py
    python scripts/w4_voice_eval.py --extract-audio temp/w4-voice-audio
    python scripts/w4_voice_eval.py --run-vbee

The default needs only Python's standard library and never reads credentials or calls APIs.
"""

import argparse
import hashlib
import io
import json
import sys
import wave
import zipfile
from array import array
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

REPO = Path(__file__).resolve().parents[1]
EVIDENCE = REPO / "docs/evidence/w4-nonstreaming-2026-10-06"
MODEL = "g-group-ai-lab/gipformer1.5-68M-rnnt"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def verify_artifacts():
    artifact = read_json(EVIDENCE / "artifact-manifest.json")
    archive = EVIDENCE / artifact["archive"]
    require(archive.stat().st_size == artifact["archive_bytes"], "Archive size differs")
    require(
        hashlib.sha256(archive.read_bytes()).hexdigest() == artifact["archive_sha256"],
        "Archive SHA-256 differs",
    )
    files = artifact["files"]
    outputs = read_json(EVIDENCE / "audio-manifest.json")
    require(len(outputs) == 30, "Expected 30 bot WAVs")
    require(len({row["path"] for row in outputs}) == 30, "Duplicate output paths")
    with zipfile.ZipFile(archive) as zipped:
        require(len(zipped.namelist()) == len(files), "Unexpected archive entry count")
        require(set(zipped.namelist()) == {f["path"] for f in files}, "Archive contents differ")
        for item in files:
            path = PurePosixPath(item["path"])
            require(not path.is_absolute() and ".." not in path.parts, "Unsafe archive path")
            data = zipped.read(item["path"])
            require(len(data) == item["bytes"], f"Size differs: {path}")
            require(hashlib.sha256(data).hexdigest() == item["sha256"], f"Hash differs: {path}")
        for item in outputs:
            data = zipped.read(item["path"])
            require(hashlib.sha256(data).hexdigest() == item["sha256"], "Output WAV hash differs")
            with wave.open(io.BytesIO(data), "rb") as wav:
                require(wav.getparams()[:3] == (1, 2, 8000), "Expected PCM16 mono 8 kHz")
                pcm = wav.readframes(wav.getnframes())
            samples = array("h", pcm)
            if sys.byteorder == "big":
                samples.byteswap()
            require(bool(samples) and max(abs(x) for x in samples) > 0, "Empty/silent WAV")
            require(len(pcm) == item["tts"]["pcm_bytes"], "PCM byte count differs")
            require(item["tts"]["provider_actual"] == "vbee", "Unexpected TTS provider")
            require(not item["tts"]["fallback_used"], "Unexpected TTS fallback")

        recorded = read_json(EVIDENCE / "results.json")
        original = json.loads(zipped.read("provenance/results.original.json"))
        # Only path metadata was rebased for handoff; measured comparisons must remain identical.
        require(recorded["flows"] == original["flows"], "Measured flow data differs from original")

    expected = {"identity", "confirm", "cancel", "transfer", "reschedule", "no_answer", "booking"}
    require({f["flow"] for f in recorded["flows"]} == expected, "Missing recorded flow")
    require(recorded["passed_flows"] == len(recorded["flows"]) == 7, "Expected PASS 7/7")
    require(recorded["asr_model"] == MODEL, "Unexpected STT model")
    for flow in recorded["flows"]:
        require(flow["passed"], f"Failed flow: {flow['flow']}")
        modes = {e["mode"]: e for e in flow["evidence"]}
        require(
            modes["text"]["comparison"] == modes["audio"]["comparison"], "State/API parity differs"
        )
        require(
            len(modes["audio"]["writes"]) == (0 if flow["flow"] == "identity" else 1),
            "Unexpected Clinic write count",
        )
        bodies = modes["audio"]["comparison"]["bodies"]
        actual = [o for o in outputs if o["flow"] == flow["flow"]]
        require(len(actual) == len(bodies) == modes["audio"]["audio_count"], "Output count differs")
        for turn, (body, output) in enumerate(zip(bodies, actual, strict=True)):
            require(
                output["turn"] == turn and output["utterance"] == body["utterance"],
                "WAV utterance/turn binding differs",
            )

    ledger = read_json(EVIDENCE / "cost-ledger.json")
    require(len(ledger["attempts"]) == recorded["provider_requests"] == 30, "Request count differs")
    require(
        sum(a["chars"] for a in ledger["attempts"]) == ledger["submitted_chars"] == 3023,
        "Character ledger differs",
    )
    require(ledger["submitted_chars"] <= ledger["budget_chars"] == 5000, "Budget differs")
    require(
        ledger["blocked_requests"] == recorded["blocked_network_attempts"] == 0,
        "Unexpected external HTTP attempt",
    )
    require(
        all(
            a["status"] == "audio_received" and a["http_status"] == 200 for a in ledger["attempts"]
        ),
        "Recorded provider request failed",
    )

    suites = ElementTree.parse(EVIDENCE / "regression/results.xml").getroot().findall("testsuite")
    counts = {
        key: sum(int(s.attrib[key]) for s in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    require(
        counts == {"tests": 215, "failures": 0, "errors": 0, "skipped": 0},
        "Regression result differs",
    )
    require(
        read_json(EVIDENCE / "regression/run-summary.json")["junit_counts"] == counts,
        "Regression summary differs",
    )
    print("PASS: recorded 7/7 parity, 30 WAV SHA-256/PCM, 3023 characters, 215 regression tests.")
    print("Offline verification only; no provider request or new evaluation was run.")
    return artifact


def extract_audio(destination):
    destination = destination.resolve()
    with zipfile.ZipFile(EVIDENCE / "artifacts/voice-audio.zip") as zipped:
        members = [n for n in zipped.namelist() if n.startswith(("inputs/", "outputs/"))]
        targets = [(name, destination / name) for name in members]
        for _, target in targets:
            require(target.resolve().is_relative_to(destination), "Extraction escaped destination")
            require(not target.exists(), f"Refusing to overwrite: {target}")
        for name, target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(zipped.read(name))
    print(f"Extracted {len(targets)} WAVs to {destination}")


def character_budget(value):
    budget = int(value)
    if not 1 <= budget <= 5000:
        raise argparse.ArgumentTypeError("Character budget must be between 1 and 5000")
    return budget


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--verify-artifacts", action="store_true", help="Offline verification (default)"
    )
    actions.add_argument(
        "--extract-audio", type=Path, metavar="DIR", help="Extract WAVs without API calls"
    )
    actions.add_argument(
        "--run-vbee", action="store_true", help="Run a NEW paid Vbee 7-flow evaluation"
    )
    parser.add_argument("--output-dir", type=Path, default=REPO / "temp/w4-voice-eval")
    parser.add_argument("--budget-chars", type=character_budget, default=5000)
    args = parser.parse_args()
    try:
        verify_artifacts()
        if args.extract_audio:
            extract_audio(args.extract_audio)
        if args.run_vbee:
            print(
                f"NEW Vbee evaluation: budget {args.budget_chars} characters; no provider retries."
            )
            return run_vbee(args)
    except Exception as exc:
        # Avoid printing settings validation input, credential values or provider response bodies.
        print(
            f"FAILED: {type(exc).__name__}. Check local assets/config and saved evidence.",
            file=sys.stderr,
        )
        return 1
    return 0


def run_vbee(args):
    import io
    import json
    import os
    import sys
    import wave
    from datetime import datetime
    from time import perf_counter
    from uuid import uuid4

    sys.path[:0] = [str(REPO), str(REPO / "src")]
    os.chdir(REPO)

    for key in (
        "OPENAI_API_KEY",
        "ELEVENLABS_API_KEY",
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
    ):
        os.environ[key] = ""
    os.environ.update(
        NAME_FALLBACK_PROVIDER="none",
        SEMANTIC_FALLBACK_ENABLED="false",
        TRACE_ENABLED="false",
        LANGFUSE_EXPORT_ENABLED="false",
    )

    from threading import Lock
    from urllib.parse import urlsplit

    import httpx

    from inference.tts.config import VbeeTTSConfig

    RUN = args.output_dir.resolve() / ("vbee-eval-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    RUN.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(EVIDENCE / "artifacts/voice-audio.zip") as zipped:
        for name in zipped.namelist():
            if name.startswith("inputs/"):
                target = RUN / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zipped.read(name))
    config = VbeeTTSConfig()
    assert config.api_token.get_secret_value() and config.app_id, "Missing Vbee credentials"
    assert config.sample_rate == 8000
    endpoint = urlsplit(config.endpoint)
    assert endpoint.scheme == "https" and endpoint.hostname == "api.vbee.vn", (
        "Unexpected Vbee endpoint"
    )
    ledger = {
        "budget_chars": args.budget_chars,
        "submitted_chars": 0,
        "attempts": [],
        "blocked_requests": 0,
    }
    lock = Lock()
    original_http = httpx.HTTPTransport.handle_request

    def save_ledger():
        (RUN / "cost-ledger.json").write_text(
            json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def allowed_http(self, request):
        if str(request.url) != config.endpoint or request.method != "POST":
            ledger["blocked_requests"] += 1
            save_ledger()
            raise RuntimeError("External request outside Vbee allowlist")
        payload = json.loads(request.content)
        assert payload["mode"] == "sync" and payload["outputFormat"] == "pcm"
        assert payload["sampleRate"] == 8000
        chars = len(payload["text"])
        with lock:
            if ledger["submitted_chars"] + chars > ledger["budget_chars"]:
                raise RuntimeError("Vbee character budget reached")
            ledger["submitted_chars"] += chars
            row = {"request": len(ledger["attempts"]) + 1, "chars": chars, "status": "submitted"}
            ledger["attempts"].append(row)
            save_ledger()
        started = perf_counter()
        try:
            response = original_http(self, request)
            row.update(status="headers_received", http_status=response.status_code)
            return response
        except Exception as exc:
            row.update(status="transport_error", error=type(exc).__name__)
            raise
        finally:
            row["headers_elapsed_ms"] = round((perf_counter() - started) * 1000, 2)
            save_ledger()

    def no_async_http(*args, **kwargs):
        ledger["blocked_requests"] += 1
        save_ledger()
        raise RuntimeError("Async external requests forbidden in non-streaming eval")

    httpx.HTTPTransport.handle_request = allowed_http
    httpx.AsyncHTTPTransport.handle_async_request = no_async_http

    from inference.tts import create_tts_gateway
    from speech.bundle import SpeechSynthesizer

    class MeasuredVbee:
        def __init__(self):
            self.delegate = SpeechSynthesizer(
                create_tts_gateway("vbee", config=config, fallback=None)
            )
            self.spoken = []
            self.measurements = []
            self.name = self.delegate.name
            self.model = self.delegate.model

        def synthesize(self, text):
            started = perf_counter()
            try:
                result = self.delegate.synthesize(text)
                assert result is not None and result.pcm
                assert result.provider_actual == "vbee" and not result.fallback_used
                assert result.sample_rate == 8000
                self.spoken.append(text)
                self.measurements.append(
                    {
                        "chars": len(text),
                        "elapsed_ms": round((perf_counter() - started) * 1000, 2),
                        "ttfa_ms": result.ttfa_ms,
                        "pcm_bytes": len(result.pcm),
                        "provider_actual": result.provider_actual,
                        "fallback_used": result.fallback_used,
                        "voice": result.voice,
                    }
                )
                ledger["attempts"][-1]["status"] = "audio_received"
                save_ledger()
                return result
            except Exception as exc:
                if ledger["attempts"]:
                    ledger["attempts"][-1].update(
                        status="synthesis_failed",
                        error=type(exc).__name__,
                        error_code=getattr(exc, "code", None),
                    )
                    save_ledger()
                raise

        def close(self):
            self.delegate.close()

    import fakeredis
    from fastapi.testclient import TestClient
    from tests.transports.http.fakes import make_speech_bundle
    from tests.transports.http.test_audio_parity import _records
    from tests.transports.http.test_calls import _start, _turn

    from callbot.engine import EngineSettings, RedisSessionStore
    from callbot.engine.dialogue import templates
    from callbot.engine.extraction.schema import VN_TZ
    from callbot.transports.http import calls as http_calls
    from callbot.transports.http.call_mode import CallModeStore
    from callbot.transports.http.main import create_app
    from clinic_mock_sim import FakeClinicAPI
    from inference.asr import create_asr_gateway
    from speech.asr.recognizer import SpeechRecognizer
    from speech.audio.codec import decode_wav

    SOURCE = RUN / "inputs"
    templates.choose_variant = lambda ctx, group: "v0"
    asr = SpeechRecognizer(create_asr_gateway("zipformer"))
    require(asr.model == MODEL, "Configured ASR must be GipFormer1.5")

    # Token timestamps locate TÔI at 1.88 seconds; retain 0.10 seconds before it.
    # Write only a new file in the workspace. Never alter the original recording.
    trimmed = SOURCE / "QA_BOOKING_REQUEST_clean.wav"
    trimmed.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(SOURCE / "QA_BOOKING_REQUEST.wav"), "rb") as src:
        params = src.getparams()
        src.setpos(round(1.78 * params.framerate))
        frames = src.readframes(params.nframes)
    with wave.open(str(trimmed), "wb") as dst:
        dst.setparams(params)
        dst.writeframes(frames)

    paths = {
        "name": SOURCE / "STT_ID_02.wav",
        "dob": SOURCE / "STT_DOB_01.wav",
        "confirm": SOURCE / "STT_CF_01.wav",
        "cancel": SOURCE / "QA_CANCEL_EXPLICIT.wav",
        "transfer": SOURCE / "QA_TRANSFER_HUMAN.wav",
        "reschedule": SOURCE / "QA_RESCHEDULE_REQUEST.wav",
        "slot": SOURCE / "QA_SLOT_FIRST.wav",
        "agree": SOURCE / "QA_SLOT_CONFIRM_EXPLICIT.wav",
        "book": trimmed,
    }
    decoded = {}
    for key, path in paths.items():
        result = asr.transcribe(decode_wav(path.read_bytes()))
        decoded[key] = {"text": result.text, "confidence": result.confidence, "path": str(path)}
        print("CLIP", key, result.text, flush=True)
    assert decoded["book"]["text"].strip().upper() == "TÔI MUỐN ĐẶT LỊCH KHÁM", decoded["book"]

    scenarios = [
        ("identity", {}, ["name", "dob"], None),
        ("confirm", {}, ["name", "dob", "confirm"], "CONFIRMED"),
        ("cancel", {}, ["name", "dob", "cancel", "cancel"], "CANCELLED"),
        ("transfer", {}, ["transfer"], "TRANSFERRED"),
        ("reschedule", {}, ["name", "dob", "reschedule", "slot", "agree"], "RESCHEDULED"),
        ("no_answer", {}, [None, None, None], "UNREACHABLE"),
        (
            "booking",
            {"direction": "inbound", "appointment_id": None, "caller_number": "0912345600"},
            ["name", "dob", "book", "slot", "agree"],
            "BOOKED",
        ),
    ]
    report = {
        "scope": "HTTP in-process, real GipFormer1.5 local ASR, real Vbee sync TTS, real upload/download WAV; simulated Clinic/fakeredis",
        "started_at": datetime.now().astimezone().isoformat(),
        "asr_model": "g-group-ai-lab/gipformer1.5-68M-rnnt",
        "tts_voice": config.voice_code,
        "budget_chars": args.budget_chars,
        "output_directory": str(RUN),
        "clock": "2026-10-06T10:00:00+07:00",
        "trim": {
            "source": str(SOURCE / "QA_BOOKING_REQUEST.wav"),
            "output": str(trimmed),
            "start_seconds": 1.78,
        },
        "clips": decoded,
        "flows": [],
    }

    for scenario, start, keys, expected in scenarios:
        comparisons = []
        evidence = []
        try:
            for mode in ("text", "audio"):
                clinic = FakeClinicAPI()
                redis_server = fakeredis.FakeServer()
                prefix = "w4_replay:" + uuid4().hex

                def make_store(redis_server=redis_server, prefix=prefix):
                    return RedisSessionStore(
                        fakeredis.FakeRedis(server=redis_server, decode_responses=True),
                        key_prefix=prefix,
                    )

                speech = make_speech_bundle(
                    RUN / "audio" / scenario / mode, base_url="http://testserver"
                )
                if mode == "audio":
                    speech.asr = asr
                    speech.tts = MeasuredVbee()
                app = create_app(
                    clinic_factory=lambda clinic=clinic: clinic,
                    engine_settings=EngineSettings(
                        name_fallback_provider="none", semantic_fallback_enabled=False
                    ),
                    session_store_factory=make_store,
                    speech_factory=lambda speech=speech: speech,
                    call_mode_factory=lambda redis_server=redis_server, prefix=prefix: (
                        CallModeStore(
                            fakeredis.FakeRedis(server=redis_server, decode_responses=True),
                            key_prefix=prefix,
                        )
                    ),
                )
                with TestClient(app) as client:
                    app.state.orchestrator.sessions._clock = lambda: datetime(
                        2026, 10, 6, 10, tzinfo=VN_TZ
                    )

                    def load_from_testclient(url):
                        response = client.get(url)
                        assert response.status_code == 200
                        return decode_wav(response.content)

                    http_calls.load_from_url = load_from_testclient
                    call_id = f"w4_{scenario}_{mode}"
                    opening_started = perf_counter()
                    opening = _start(client, call_id, mode=mode, **start)
                    opening_elapsed_ms = round((perf_counter() - opening_started) * 1000, 2)
                    assert opening.status_code == 200, f"Opening HTTP {opening.status_code}"
                    bodies = [opening.json()]
                    snapshots = []
                    turns = []
                    audio_checks = []

                    def check_audio(url, audio_checks=audio_checks):
                        response = client.get(url)
                        assert response.status_code == 200
                        with wave.open(io.BytesIO(response.content)) as wav:
                            assert wav.getframerate() == 8000
                            assert (
                                wav.getnchannels() == 1
                                and wav.getsampwidth() == 2
                                and wav.getnframes() > 0
                            )
                        from array import array

                        samples = array("h", decode_wav(response.content).pcm)
                        peak = max(abs(x) for x in samples)
                        assert peak > 0, "Silent output"
                        audio_checks.append(
                            {
                                "url": url,
                                "pcm_bytes": len(samples) * 2,
                                "sample_rate": 8000,
                                "duration_seconds": len(samples) / 8000,
                                "peak": peak,
                            }
                        )

                    if mode == "audio":
                        check_audio(bodies[0]["audio_url"])
                    for turn, key in enumerate(keys, 1):
                        audio_url = None
                        if mode == "audio" and key is not None:
                            upload = client.put(
                                f"/demo-api/audio/{call_id}/{turn}.wav",
                                content=paths[key].read_bytes(),
                                headers={"Content-Type": "audio/wav"},
                            )
                            assert upload.status_code == 200, upload.text
                            audio_url = upload.json()["audio_url"]
                        started = perf_counter()
                        response = _turn(
                            client,
                            call_id,
                            turn,
                            decoded[key]["text"] if mode == "text" and key else None,
                            silence_ms=2000 if key is None else 0,
                            audio_url=audio_url,
                        )
                        assert response.status_code == 200, f"Turn HTTP {response.status_code}"
                        body = response.json()
                        bodies.append(body)
                        if mode == "audio":
                            check_audio(body["audio_url"])
                        session = app.state.session_store.get_session(call_id)
                        ctx = session.context
                        snapshots.append(
                            {
                                field: ctx.get(field)
                                for field in (
                                    "state",
                                    "turn",
                                    "identity_verified",
                                    "silent_turns",
                                    "failed_understandings",
                                    "selected_slot_id",
                                    "pending_action",
                                    "presented_slot_ids",
                                )
                            }
                        )
                        turns.append(
                            {
                                "turn": turn,
                                "clip": key,
                                "state": body["state"],
                                "outcome": body["outcome"],
                                "elapsed_ms": round((perf_counter() - started) * 1000, 2),
                            }
                        )
                    assert bodies[-1]["outcome"] == expected
                    assert bodies[-1]["ended"] == (expected is not None)
                    if mode == "audio":
                        assert speech.tts.spoken == [body["utterance"] for body in bodies]
                    else:
                        assert speech.tts.spoken == []
                    assert len(clinic.writes) == (0 if expected is None else 1)
                    comparisons.append(
                        {
                            "bodies": [
                                {k: v for k, v in body.items() if k not in ("call_id", "audio_url")}
                                for body in bodies
                            ],
                            "snapshots": snapshots,
                            "writes": clinic.writes,
                            "records": _records(clinic),
                            "api": [
                                (c.operation, c.method, c.path, c.status, c.code)
                                for c in clinic.calls
                            ],
                        }
                    )
                    evidence.append(
                        {
                            "mode": mode,
                            "turns": turns,
                            "audio_count": len(audio_checks),
                            "audio_checks": audio_checks,
                            "opening_elapsed_ms": opening_elapsed_ms,
                            "tts": speech.tts.measurements if mode == "audio" else [],
                            "writes": clinic.writes,
                            "comparison": comparisons[-1],
                        }
                    )
            assert comparisons[0] == comparisons[1], "Text/audio state or API comparison differs"
            row = {"flow": scenario, "passed": True, "outcome": expected, "evidence": evidence}
            print("FLOW", scenario, "PASS", expected, flush=True)
        except Exception as exc:
            row = {
                "flow": scenario,
                "passed": False,
                "error": type(exc).__name__,
                "detail": "Stopped after failure; see cost ledger for sanitized provider status",
                "evidence": evidence,
            }
            print("FLOW", scenario, "FAIL", type(exc).__name__, flush=True)
        report["flows"].append(row)
        (RUN / "results.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        if not row["passed"]:
            break

    report["passed_flows"] = sum(row["passed"] for row in report["flows"])
    report["blocked_network_attempts"] = ledger["blocked_requests"]
    report["submitted_chars"] = ledger["submitted_chars"]
    report["provider_requests"] = len(ledger["attempts"])
    report["finished_at"] = datetime.now().astimezone().isoformat()
    (RUN / "results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(
        "SUMMARY",
        report["passed_flows"],
        "/ 7; Vbee requests",
        len(ledger["attempts"]),
        "characters",
        ledger["submitted_chars"],
        "report",
        str(RUN / "results.json"),
        flush=True,
    )
    return 0 if report["passed_flows"] == 7 and not ledger["blocked_requests"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
