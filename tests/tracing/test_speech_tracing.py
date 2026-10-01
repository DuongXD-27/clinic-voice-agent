from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from uuid import uuid4

import fakeredis
import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from tests.transports.http.fakes import FakeASR, FakeTTS

from callbot.engine import EngineSettings
from callbot.tracing import CompositeTraceSink, JsonlTraceSink, Tracer
from callbot.tracing.config import TracingSettings, create_tracer
from callbot.tracing.langfuse_sink import LangfuseOtlpSettings, LangfuseOtlpTraceSink
from callbot.tracing.models import CompletedSpan
from callbot.tracing.pseudonym import CallKeyFactory
from callbot.transports.http.call_mode import CallModeStore
from callbot.transports.http.main import create_app
from clinic_mock_sim import FakeClinicAPI
from speech.audio.storage import AudioArtifactStore
from speech.bundle import SpeechBundle
from speech.types import AudioSegment, Transcript

_AUDIO = AudioSegment(pcm=b"\x00\x00" * 100, sample_rate=8000)


class MemorySink:
    def __init__(self, *, fail: bool = False) -> None:
        self.spans: list[CompletedSpan] = []
        self.fail = fail

    def emit(self, span: CompletedSpan) -> None:
        if self.fail:
            raise OSError("private sink failure")
        self.spans.append(span)


class ControllableASR(FakeASR):
    def __init__(self, transcript: str = "Nguyễn Văn A") -> None:
        super().__init__(transcript)
        self.error: Exception | None = None

    def transcribe(self, segment: AudioSegment) -> Transcript:
        if self.error is not None:
            raise self.error
        return super().transcribe(segment)


class BrokenAudioStore(AudioArtifactStore):
    def save(self, call_id: str, turn: int, segment: AudioSegment) -> str:
        del call_id, turn, segment
        raise OSError("private storage path")


def _tracer(sink) -> Tracer:
    return Tracer(
        sink,
        CallKeyFactory("speech-tracing-key-material-000000000", version="v1", environment="test"),
    )


def _app(
    tmp_path,
    redis_store_factory,
    redis_server,
    tracer: Tracer,
    *,
    asr: FakeASR | None = None,
    tts: FakeTTS | None = None,
    audio_store: AudioArtifactStore | None = None,
    audio_loader: Callable[[str], AudioSegment] | None = None,
):
    speech = SpeechBundle(
        asr=asr or FakeASR(transcript="Nguyễn Văn A"),
        tts=tts or FakeTTS(),
        audio_store=audio_store or AudioArtifactStore(str(tmp_path / "audio"), "http://test"),
        audio_loader=audio_loader or (lambda _url: _AUDIO),
    )
    return create_app(
        clinic_factory=FakeClinicAPI,
        engine_settings=EngineSettings(llm_provider="none"),
        session_store_factory=redis_store_factory,
        speech_factory=lambda: speech,
        call_mode_factory=lambda: CallModeStore(
            fakeredis.FakeRedis(server=redis_server, decode_responses=True),
            key_prefix=f"test:{uuid4().hex}",
        ),
        tracer_factory=lambda: tracer,
    )


def _start(client: TestClient, call_id: str, *, mode: str) -> httpx.Response:
    return client.post(
        "/v1/calls",
        json={
            "call_id": call_id,
            "direction": "outbound",
            "appointment_id": "apt_00417",
            "caller_number": None,
            "locale": "vi-VN",
            "mode": mode,
            "max_turns": 20,
        },
    )


def _audio_turn(client: TestClient, call_id: str) -> httpx.Response:
    return client.post(
        f"/v1/calls/{call_id}/turn",
        json={
            "turn": 1,
            "text": None,
            "silence_ms": 0,
            "audio_url": "https://private.test/input.wav",
        },
    )


def test_text_mode_has_core_without_fake_speech_spans(
    tmp_path, redis_store_factory, redis_server
) -> None:
    sink = MemorySink()
    app = _app(tmp_path, redis_store_factory, redis_server, _tracer(sink))
    with TestClient(app) as client:
        assert _start(client, "text-trace", mode="text").status_code == 200
        response = client.post(
            "/v1/calls/text-trace/turn",
            json={"turn": 1, "text": "Nguyễn Văn A", "silence_ms": 0, "audio_url": None},
        )
        assert response.status_code == 200

    assert any(span.component == "CORE" for span in sink.spans)
    assert not any(span.component in {"STT", "TTS"} for span in sink.spans)


def test_empty_transcript_is_successful_silence_not_technical_error(
    tmp_path, redis_store_factory, redis_server
) -> None:
    sink = MemorySink()
    asr = FakeASR(transcript="")
    app = _app(tmp_path, redis_store_factory, redis_server, _tracer(sink), asr=asr)
    with TestClient(app) as client:
        assert _start(client, "empty-stt", mode="audio").status_code == 200
        assert _audio_turn(client, "empty-stt").status_code == 200

    stt = next(span for span in sink.spans if span.component == "STT")
    assert stt.status == "OK"
    assert stt.attributes["transcript_empty"] is True
    assert stt.attributes["silence_detected"] is True
    assert "error_code" not in stt.attributes


def test_tts_none_is_successful_unavailable_output(
    tmp_path, redis_store_factory, redis_server
) -> None:
    sink = MemorySink()
    app = _app(
        tmp_path,
        redis_store_factory,
        redis_server,
        _tracer(sink),
        tts=FakeTTS(respond=False),
    )
    with TestClient(app) as client:
        response = _start(client, "tts-none", mode="audio")
        assert response.status_code == 200
        assert response.json()["audio_url"] is None

    tts = next(span for span in sink.spans if span.component == "TTS")
    assert tts.status == "OK"
    assert "error_code" not in tts.attributes
    assert "bytes" not in tts.attributes


@pytest.mark.parametrize(
    ("failure", "http_status", "error_type", "error_code"),
    [
        (RuntimeError("private STT provider response"), 503, "PROVIDER", "STT_PROVIDER_ERROR"),
        (httpx.ReadTimeout("private STT timeout"), 503, "TIMEOUT", "STT_TIMEOUT"),
    ],
)
def test_stt_provider_failure_is_safe_and_reports_upstream_unavailable(
    failure, http_status, error_type, error_code, tmp_path, redis_store_factory, redis_server
) -> None:
    sink = MemorySink()
    asr = ControllableASR()
    app = _app(tmp_path, redis_store_factory, redis_server, _tracer(sink), asr=asr)
    with TestClient(app) as client:
        assert _start(client, "stt-failure", mode="audio").status_code == 200
        asr.error = failure
        response = _audio_turn(client, "stt-failure")
        assert response.status_code == http_status

    stt = next(span for span in sink.spans if span.component == "STT")
    assert stt.status == "ERROR"
    assert stt.attributes["error_type"] == error_type
    assert stt.attributes["error_code"] == error_code
    assert "private STT" not in json.dumps(stt.to_dict())


def test_audio_load_failure_is_an_stt_stage_error(
    tmp_path, redis_store_factory, redis_server
) -> None:
    sink = MemorySink()

    def broken_loader(_url: str) -> AudioSegment:
        raise ValueError("private audio URL and decode detail")

    app = _app(
        tmp_path,
        redis_store_factory,
        redis_server,
        _tracer(sink),
        audio_loader=broken_loader,
    )
    with TestClient(app) as client:
        assert _start(client, "audio-load-failure", mode="audio").status_code == 200
        assert _audio_turn(client, "audio-load-failure").status_code == 503

    stt = next(span for span in sink.spans if span.component == "STT")
    assert stt.status == "ERROR"
    assert stt.attributes["error_type"] == "UPSTREAM"
    assert stt.attributes["error_code"] == "STT_DECODE_ERROR"
    assert "private audio URL" not in json.dumps(stt.to_dict())


def test_tts_provider_and_storage_failures_are_distinguished_without_behavior_change(
    tmp_path, redis_store_factory, redis_server
) -> None:
    provider_sink = MemorySink()
    provider_app = _app(
        tmp_path / "provider",
        redis_store_factory,
        redis_server,
        _tracer(provider_sink),
        tts=FakeTTS(error=RuntimeError("private TTS provider response")),
    )
    with TestClient(provider_app) as client:
        response = _start(client, "tts-provider-failure", mode="audio")
        assert response.status_code == 200
        assert response.json()["audio_url"] is None

    provider_span = next(span for span in provider_sink.spans if span.component == "TTS")
    assert provider_span.status == "ERROR"
    assert provider_span.attributes["error_type"] == "PROVIDER"
    assert provider_span.attributes["error_code"] == "TTS_PROVIDER_ERROR"

    storage_sink = MemorySink()
    storage_app = _app(
        tmp_path / "storage",
        redis_store_factory,
        redis_server,
        _tracer(storage_sink),
        audio_store=BrokenAudioStore(str(tmp_path / "broken"), "http://test"),
    )
    with TestClient(storage_app) as client:
        assert _start(client, "tts-storage-failure", mode="audio").status_code == 500

    storage_span = next(span for span in storage_sink.spans if span.component == "TTS")
    assert storage_span.status == "ERROR"
    assert storage_span.attributes["error_type"] == "STORAGE"
    assert storage_span.attributes["error_code"] == "TTS_STORAGE_ERROR"
    serialized = json.dumps([provider_span.to_dict(), storage_span.to_dict()])
    assert "private TTS provider response" not in serialized
    assert "private storage path" not in serialized


def test_tts_timeout_is_recorded_without_changing_fallback(
    tmp_path, redis_store_factory, redis_server
) -> None:
    sink = MemorySink()
    app = _app(
        tmp_path,
        redis_store_factory,
        redis_server,
        _tracer(sink),
        tts=FakeTTS(error=httpx.ReadTimeout("private TTS timeout")),
    )
    with TestClient(app) as client:
        response = _start(client, "tts-timeout", mode="audio")
        assert response.status_code == 200
        assert response.json()["audio_url"] is None

    tts = next(span for span in sink.spans if span.component == "TTS")
    assert tts.status == "ERROR"
    assert tts.attributes["error_type"] == "TIMEOUT"
    assert tts.attributes["error_code"] == "TTS_TIMEOUT"
    assert "private TTS timeout" not in json.dumps(tts.to_dict())


def test_sink_failure_does_not_repeat_stt_or_tts_provider_calls(
    tmp_path, redis_store_factory, redis_server
) -> None:
    asr = FakeASR(transcript="Nguyễn Văn A")
    tts = FakeTTS()
    app = _app(
        tmp_path,
        redis_store_factory,
        redis_server,
        _tracer(MemorySink(fail=True)),
        asr=asr,
        tts=tts,
    )
    with TestClient(app) as client:
        warmup_count = len(asr.received)
        assert _start(client, "sink-failure", mode="audio").status_code == 200
        tts_before_turn = len(tts.spoken)
        assert _audio_turn(client, "sink-failure").status_code == 200
        assert len(asr.received) == warmup_count + 1
        assert len(tts.spoken) == tts_before_turn + 1


def test_invalid_runtime_speech_metadata_is_fail_open_and_secret_safe(
    tmp_path, redis_store_factory, redis_server, caplog: pytest.LogCaptureFixture
) -> None:
    sink = MemorySink()
    asr = FakeASR(transcript="Nguyễn Văn A")
    tts = FakeTTS()
    canary = "private speech label"
    asr.model = canary
    tts.model = canary
    app = _app(
        tmp_path,
        redis_store_factory,
        redis_server,
        _tracer(sink),
        asr=asr,
        tts=tts,
    )

    with TestClient(app) as client:
        warmup_count = len(asr.received)
        assert _start(client, "invalid-metadata", mode="audio").status_code == 200
        tts_before_turn = len(tts.spoken)
        assert _audio_turn(client, "invalid-metadata").status_code == 200
        assert len(asr.received) == warmup_count + 1
        assert len(tts.spoken) == tts_before_turn + 1

    assert canary not in json.dumps([span.to_dict() for span in sink.spans])
    assert canary not in caplog.text


def _langfuse_settings() -> LangfuseOtlpSettings:
    return LangfuseOtlpSettings(
        enabled=True,
        endpoint="https://langfuse.test/api/public/otel",
        public_key=SecretStr("pk-test"),
        secret_key=SecretStr("sk-test"),
        queue_size=32,
        batch_size=32,
        flush_interval_seconds=10.0,
        environment="test",
    )


def _otlp_spans(requests: list[httpx.Request]) -> list[dict]:
    return [
        span
        for request in requests
        for resource in json.loads(request.content)["resourceSpans"]
        for scope in resource["scopeSpans"]
        for span in scope["spans"]
    ]


def _otlp_attributes(span: dict) -> dict[str, object]:
    return {item["key"]: next(iter(item["value"].values())) for item in span["attributes"]}


def test_audio_spans_export_to_jsonl_and_langfuse_without_speech_content(
    tmp_path, redis_store_factory, redis_server
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, request=request)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    trace_dir = tmp_path / "traces"
    tracer = create_tracer(
        TracingSettings(
            enabled=True,
            jsonl_dir=trace_dir,
            pseudonymization_key=SecretStr("speech-export-key-material-000000000"),
            environment="test",
        ),
        _langfuse_settings(),
        langfuse_client=http_client,
    )
    app = _app(tmp_path, redis_store_factory, redis_server, tracer)
    call_id = "private-export-call"
    with TestClient(app) as client:
        assert _start(client, call_id, mode="audio").status_code == 200
        assert _audio_turn(client, call_id).status_code == 200

    records = [
        json.loads(line)
        for path in trace_dir.glob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    root = next(
        record for record in records if record["component"] == "TURN" and record["turn"] == 1
    )
    direct = {
        record["component"]: record
        for record in records
        if record["parent_span_id"] == root["span_id"]
    }
    assert set(direct) == {"STT", "CORE", "TTS"}
    assert all(record["trace_id"] == root["trace_id"] for record in direct.values())
    assert all(record["call_key"] == root["call_key"] for record in direct.values())
    assert direct["STT"]["provider"] == "fake"
    assert direct["STT"]["model"] == "fake-asr-v1"
    assert direct["TTS"]["provider"] == "fake"
    assert direct["TTS"]["model"] == "fake-tts-v1"

    exported = _otlp_spans(requests)
    exported_root = next(
        span
        for span in exported
        if _otlp_attributes(span)["langfuse.observation.metadata.component"] == "TURN"
        and _otlp_attributes(span)["langfuse.observation.metadata.turn"] == "1"
    )
    exported_direct = {
        _otlp_attributes(span)["langfuse.observation.metadata.component"]: span
        for span in exported
        if span.get("parentSpanId") == exported_root["spanId"]
    }
    assert set(exported_direct) == {"STT", "CORE", "TTS"}
    assert all(span["traceId"] == exported_root["traceId"] for span in exported_direct.values())
    assert all(
        _otlp_attributes(span)["langfuse.session.id"]
        == _otlp_attributes(exported_root)["langfuse.session.id"]
        for span in exported_direct.values()
    )

    serialized = json.dumps({"jsonl": records, "otlp": exported}, ensure_ascii=False)
    for forbidden in (
        call_id,
        "Nguyễn Văn A",
        "https://private.test/input.wav",
        '"transcript":',
        "utterance",
        "audio_url",
        "langfuse.observation.input",
        "langfuse.observation.output",
        "user.id",
    ):
        assert forbidden not in serialized
    http_client.close()


@pytest.mark.parametrize(
    ("component", "operation", "field"),
    [
        ("STT", "speech.stt.transcribe", "transcript"),
        ("STT", "speech.stt.transcribe", "audio_url"),
        ("STT", "speech.stt.transcribe", "phone"),
        ("STT", "speech.stt.transcribe", "patient_id"),
        ("TTS", "speech.tts.synthesize", "utterance"),
        ("TTS", "speech.tts.synthesize", "name"),
        ("TTS", "speech.tts.synthesize", "dob"),
        ("TTS", "speech.tts.synthesize", "appointment_id"),
        ("TTS", "speech.tts.synthesize", "audio_bytes"),
    ],
)
def test_private_speech_metadata_is_rejected_before_jsonl_or_network(
    component,
    operation,
    field,
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    remote = LangfuseOtlpTraceSink(
        endpoint="https://langfuse.test/api/public/otel",
        public_key="pk-test",
        secret_key="sk-test",
        environment="test",
        client=client,
    )
    tracer = _tracer(CompositeTraceSink(JsonlTraceSink(tmp_path), remote))
    base = CompletedSpan(
        trace_id="0" * 32,
        span_id="1" * 16,
        parent_span_id="2" * 16,
        call_key="ck_v1_safe",
        turn=1,
        component=component,
        operation=operation,
        start_time="2026-01-01T00:00:00Z",
        end_time="2026-01-01T00:00:01Z",
        duration_ms=1000.0,
        status="OK",
    )
    canary = "private-speech-canary"

    tracer._emit(replace(base, attributes={field: canary}))
    assert tracer.close(1.0)

    assert requests == []
    assert list(tmp_path.glob("*.jsonl")) == []
    assert canary not in caplog.text
    client.close()
