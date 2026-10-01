import json
import logging
from threading import Event, get_ident
from uuid import uuid4

import fakeredis
import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from tests.transports.http.fakes import FakeASR, FakeTTS

from callbot.engine import EngineSettings
from callbot.tracing import Tracer, current_span
from callbot.tracing.config import TracingSettings, create_tracer
from callbot.tracing.langfuse_sink import LangfuseOtlpSettings
from callbot.tracing.models import CompletedSpan
from callbot.tracing.pseudonym import CallKeyFactory
from callbot.transports.http.call_mode import CallModeStore
from callbot.transports.http.main import create_app
from clinic_mock_sim import FakeClinicAPI
from speech.audio.storage import AudioArtifactStore
from speech.bundle import SpeechBundle
from speech.types import AudioSegment, Transcript

_AUDIO = AudioSegment(pcm=b"\x00\x00" * 100, sample_rate=8000)


def _active_turn() -> tuple[str, int] | None:
    span = current_span()
    if span is None or not span.enabled:
        return None
    return span.operation, span.turn


class LifecycleSink:
    def __init__(self, timeline: list[object]) -> None:
        self.timeline = timeline
        self.spans: list[CompletedSpan] = []

    def emit(self, span: CompletedSpan) -> None:
        self.spans.append(span)
        self.timeline.append(("emit", span.operation, span.turn))

    def flush(self, timeout: float) -> bool:
        self.timeline.append(("trace.flush", timeout, get_ident()))
        return True

    def close(self, timeout: float) -> bool:
        self.timeline.append(("trace.close", timeout, get_ident()))
        return True


class TrackingASR(FakeASR):
    def __init__(self, timeline: list[object]) -> None:
        super().__init__(transcript="Nguyễn Văn A")
        self.timeline = timeline

    def transcribe(self, segment: AudioSegment) -> Transcript:
        active = _active_turn()
        if active is not None:
            self.timeline.append(("stt", *active))
        return super().transcribe(segment)

    def close(self) -> None:
        self.timeline.append("asr.close")


class TrackingTTS(FakeTTS):
    def __init__(self, timeline: list[object]) -> None:
        super().__init__(respond=True)
        self.timeline = timeline

    def synthesize(self, text: str) -> AudioSegment | None:
        active = _active_turn()
        self.timeline.append(("tts", *(active or ("missing", -1))))
        return super().synthesize(text)

    def close(self) -> None:
        self.timeline.append("tts.close")


class TrackingAudioStore(AudioArtifactStore):
    def __init__(self, directory, timeline: list[object]) -> None:
        super().__init__(str(directory), "http://test")
        self.timeline = timeline

    def save(self, call_id: str, turn: int, segment: AudioSegment) -> str:
        active = _active_turn()
        self.timeline.append(("audio_store", *(active or ("missing", -1))))
        return super().save(call_id, turn, segment)


class ClosingClinic(FakeClinicAPI):
    def __init__(self, timeline: list[object]) -> None:
        super().__init__()
        self.timeline = timeline

    def close(self) -> None:
        self.timeline.append("clinic.close")


class ClosingCallMode(CallModeStore):
    def __init__(self, redis_server, timeline: list[object]) -> None:
        super().__init__(
            fakeredis.FakeRedis(server=redis_server, decode_responses=True),
            key_prefix=f"test:{uuid4().hex}",
        )
        self.timeline = timeline

    def close(self) -> None:
        self.timeline.append("call_mode.close")
        super().close()


def test_voice_turn_root_context_reuse_privacy_and_shutdown_order(
    tmp_path, redis_store_factory, redis_server
) -> None:
    timeline: list[object] = []
    sink = LifecycleSink(timeline)
    tracer = Tracer(
        sink,
        CallKeyFactory("runtime-reconciliation-key-000000000", version="v1", environment="test"),
    )
    tracer_factory_calls = 0
    asr = TrackingASR(timeline)
    tts = TrackingTTS(timeline)
    speech = SpeechBundle(
        asr=asr,
        tts=tts,
        audio_store=TrackingAudioStore(tmp_path / "audio", timeline),
        audio_loader=lambda _url: (timeline.append(("audio_load", *_active_turn())), _AUDIO)[1],
    )
    clinic = ClosingClinic(timeline)

    def tracer_factory() -> Tracer:
        nonlocal tracer_factory_calls
        tracer_factory_calls += 1
        return tracer

    def store_factory():
        store = redis_store_factory()
        original_close = store.close

        def close() -> None:
            timeline.append("store.close")
            original_close()

        store.close = close
        return store

    app = create_app(
        clinic_factory=lambda: clinic,
        engine_settings=EngineSettings(llm_provider="none"),
        session_store_factory=store_factory,
        speech_factory=lambda: speech,
        call_mode_factory=lambda: ClosingCallMode(redis_server, timeline),
        tracer_factory=tracer_factory,
    )
    call_id = "runtime-private-call"
    with TestClient(app) as client:
        start = client.post(
            "/v1/calls",
            json={
                "call_id": call_id,
                "direction": "outbound",
                "appointment_id": "apt_00417",
                "caller_number": "0912345600",
                "locale": "vi-VN",
                "mode": "audio",
                "max_turns": 20,
            },
        )
        turn = client.post(
            f"/v1/calls/{call_id}/turn",
            json={
                "turn": 1,
                "text": None,
                "silence_ms": 0,
                "audio_url": "https://private.test/input.wav",
            },
        )

        assert start.status_code == turn.status_code == 200
        assert start.json()["audio_url"] == "http://test/audio/runtime-private-call/0.wav"
        assert turn.json()["audio_url"] == "http://test/audio/runtime-private-call/1.wav"
        assert app.state.tracer is tracer
        assert app.state.orchestrator.tracer is tracer
        assert tracer_factory_calls == 1

    assert ("tts", "speech.tts.synthesize", 0) in timeline
    assert ("audio_store", "speech.tts.synthesize", 0) in timeline
    assert ("audio_load", "speech.stt.transcribe", 1) in timeline
    assert ("stt", "speech.stt.transcribe", 1) in timeline
    assert ("tts", "speech.tts.synthesize", 1) in timeline
    assert ("audio_store", "speech.tts.synthesize", 1) in timeline
    assert timeline.index(("audio_store", "speech.tts.synthesize", 1)) < timeline.index(
        ("emit", "http.call_turn", 1)
    )

    roots = [span for span in sink.spans if span.component == "TURN"]
    cores = [span for span in sink.spans if span.component == "CORE"]
    assert [(span.operation, span.turn) for span in roots] == [
        ("http.start_call", 0),
        ("http.call_turn", 1),
    ]
    assert all(core.parent_span_id == roots[core.turn].span_id for core in cores)
    direct_children = {
        root.turn: {span.component for span in sink.spans if span.parent_span_id == root.span_id}
        for root in roots
    }
    assert direct_children[0] == {"CORE", "TTS"}
    assert direct_children[1] == {"STT", "CORE", "TTS"}

    stt = next(span for span in sink.spans if span.component == "STT")
    tts_turn = next(span for span in sink.spans if span.component == "TTS" and span.turn == 1)
    assert stt.status == "OK"
    assert stt.attributes == {
        "provider": "fake",
        "model": "fake-asr-v1",
        "streaming": False,
        "audio_duration_ms": 12,
        "sample_rate_hz": 8000,
        "latency_ms": stt.attributes["latency_ms"],
        "provider_latency_ms": stt.attributes["latency_ms"],
        "silence_detected": False,
        "transcript_empty": False,
        "input_mode": "batch",
        "result": "OK",
    }
    assert stt.attributes["latency_ms"] >= 0
    assert tts_turn.status == "OK"
    assert tts_turn.attributes == {
        "provider": "fake",
        "model": "fake-tts-v1",
        "latency_ms": tts_turn.attributes["latency_ms"],
        "audio_duration_ms": 12,
        "sample_rate_hz": 8000,
        "bytes": 200,
        "chunks": 1,
        "provider_requested": "fake",
        "character_count": len(turn.json()["utterance"]),
        "fallback_used": False,
        "audio_format": "pcm16",
        "result": "OK",
    }
    assert tts_turn.attributes["latency_ms"] >= 0

    serialized = json.dumps([span.to_dict() for span in sink.spans], ensure_ascii=False)
    for private in (
        call_id,
        "apt_00417",
        "0912345600",
        "Nguyễn Văn A",
        "https://private.test/input.wav",
        "audio_url",
        "utterance",
        '"transcript":',
    ):
        assert private not in serialized

    lifecycle = [item for item in timeline if isinstance(item, str)]
    assert lifecycle == [
        "asr.close",
        "tts.close",
        "call_mode.close",
        "clinic.close",
        "store.close",
    ]
    assert timeline[-2][0] == "trace.flush"
    assert timeline[-1][0] == "trace.close"


def _remote_tracer(client: httpx.Client, *, queue_size: int = 8) -> Tracer:
    return create_tracer(
        TracingSettings(
            enabled=True,
            jsonl_dir=None,
            pseudonymization_key=SecretStr("runtime-network-key-material-00000000"),
            environment="test",
        ),
        LangfuseOtlpSettings(
            enabled=True,
            endpoint="https://langfuse.test/api/public/otel",
            public_key=SecretStr("pk-test"),
            secret_key=SecretStr("sk-test"),
            queue_size=queue_size,
            batch_size=1,
            flush_interval_seconds=0.01,
            environment="test",
        ),
        langfuse_client=client,
    )


def _runtime_app(tmp_path, redis_store_factory, redis_server, tracer: Tracer):
    speech = SpeechBundle(
        asr=FakeASR(),
        tts=FakeTTS(),
        audio_store=AudioArtifactStore(str(tmp_path / "audio"), "http://test"),
        audio_loader=lambda _url: _AUDIO,
    )
    return create_app(
        clinic_factory=FakeClinicAPI,
        engine_settings=EngineSettings(llm_provider="none"),
        session_store_factory=redis_store_factory,
        speech_factory=lambda: speech,
        call_mode_factory=lambda: ClosingCallMode(redis_server, []),
        tracer_factory=lambda: tracer,
        trace_shutdown_timeout_s=1.0,
    )


def _start_text_call(client: TestClient, call_id: str):
    return client.post(
        "/v1/calls",
        json={
            "call_id": call_id,
            "direction": "outbound",
            "appointment_id": "apt_00417",
            "caller_number": None,
            "locale": "vi-VN",
            "mode": "text",
            "max_turns": 20,
        },
    )


@pytest.mark.parametrize("failure", ["timeout", "http_500"])
def test_langfuse_network_failure_does_not_fail_http_request(
    failure,
    tmp_path,
    redis_store_factory,
    redis_server,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "timeout":
            raise httpx.ReadTimeout("private transport detail", request=request)
        return httpx.Response(500, request=request)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    app = _runtime_app(tmp_path, redis_store_factory, redis_server, _remote_tracer(http_client))
    with caplog.at_level(logging.WARNING), TestClient(app) as client:
        response = _start_text_call(client, f"network-{failure}")
        assert response.status_code == 200

    expected = (
        "LANGFUSE_EXPORT_NETWORK_FAILED" if failure == "timeout" else "LANGFUSE_EXPORT_HTTP_FAILED"
    )
    assert expected in caplog.text
    assert "private transport detail" not in caplog.text
    http_client.close()


def test_langfuse_queue_full_does_not_fail_http_request(
    tmp_path, redis_store_factory, redis_server
) -> None:
    entered = Event()
    release = Event()

    def handler(request: httpx.Request) -> httpx.Response:
        entered.set()
        release.wait(2.0)
        return httpx.Response(200, request=request)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    tracer = _remote_tracer(http_client, queue_size=1)
    app = _runtime_app(tmp_path, redis_store_factory, redis_server, tracer)
    with TestClient(app) as client:
        started = _start_text_call(client, "queue-full-call")
        assert started.status_code == 200
        assert entered.wait(1.0)
        turned = client.post(
            "/v1/calls/queue-full-call/turn",
            json={"turn": 1, "text": "Nguyễn Văn A", "silence_ms": 0, "audio_url": None},
        )
        assert turned.status_code == 200
        assert tracer._sink.dropped_count > 0
        release.set()
    http_client.close()
