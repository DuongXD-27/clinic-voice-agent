"""/v1/stt/* — API PM thử chất lượng STT trên file WAV (stt_eval.py)."""

import math
import socket
from collections.abc import Iterator
from uuid import uuid4

import fakeredis
import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from tests.transports.http.fakes import FakeASR, make_speech_bundle

import callbot.transports.http.stt_eval as stt_eval
from callbot.engine import EngineSettings
from callbot.transports.http.call_mode import CallModeStore
from callbot.transports.http.config import Settings
from callbot.transports.http.config import settings as http_settings
from callbot.transports.http.main import create_app
from speech.asr.vad import EnergyFrameClassifier
from speech.audio.codec import encode_wav
from speech.types import AudioSegment

PUBLIC_IP = "93.184.216.34"


def _wav() -> bytes:
    t = np.arange(16_000) / 16_000
    tone = (8000 * np.sin(2 * math.pi * 440 * t)).astype(np.int16)
    silence = np.zeros(16_000, dtype=np.int16)
    pcm = np.concatenate([silence, tone, silence]).tobytes()
    return encode_wav(AudioSegment(pcm=pcm, sample_rate=16_000))


def _resolver(mapping: dict[str, str]):
    def resolve(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (mapping[host], port))]

    return resolve


@pytest.fixture
def stt_client(clinic, redis_store_factory, redis_server, tmp_path) -> Iterator[TestClient]:
    app = create_app(
        clinic_factory=lambda: clinic,
        engine_settings=EngineSettings(),
        session_store_factory=redis_store_factory,
        speech_factory=lambda: make_speech_bundle(
            tmp_path, asr=FakeASR("xin chào", confidence=0.9)
        ),
        call_mode_factory=lambda: CallModeStore(
            fakeredis.FakeRedis(server=redis_server, decode_responses=True),
            key_prefix=f"test:{uuid4().hex}",
        ),
        stt_eval_enabled=True,
        stt_vad_factory=lambda rate: EnergyFrameClassifier(500),
    )
    with TestClient(app) as client:
        yield client


@pytest.fixture
def remote_wav(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """clips.example -> IP public, trả WAV; ghi lại request để kiểm tra."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=_wav())

    monkeypatch.setattr(stt_eval, "_resolve", _resolver({"clips.example": PUBLIC_IP}))
    monkeypatch.setattr(stt_eval, "_transport", httpx.MockTransport(handler))
    return seen


def _upload(client: TestClient, data: bytes, **form: str) -> httpx.Response:
    return client.post(
        "/v1/stt/transcribe/upload", files={"file": ("a.wav", data, "audio/wav")}, data=form
    )


def _upload_turn(client: TestClient, data: bytes, **form: str) -> httpx.Response:
    return client.post(
        "/v1/stt/turn/upload", files={"file": ("a.wav", data, "audio/wav")}, data=form
    )


def test_routes_are_not_mounted_by_default(client: TestClient) -> None:
    assert _upload(client, _wav()).status_code == 404
    assert client.post("/v1/stt/transcribe", json={"audio_url": "https://x"}).status_code == 404
    assert _upload_turn(client, _wav()).status_code == 404
    assert client.post("/v1/stt/turn", json={"audio_url": "https://x"}).status_code == 404


def test_enabling_requires_bot_api_keys() -> None:
    with pytest.raises(ValidationError, match="STT_EVAL_ENABLED=true requires BOT_API_KEYS"):
        Settings(_env_file=None, stt_eval_enabled=True, bot_api_keys="")
    assert Settings(_env_file=None, stt_eval_enabled=True, bot_api_keys="sk_test").stt_eval_enabled


def test_upload_returns_transcript_and_details(stt_client: TestClient) -> None:
    response = _upload(stt_client, _wav(), compare="true")

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["text"], body["confidence"], body["is_silence"]) == ("xin chào", 0.9, False)
    assert body["segments"] == [
        {"start_ms": 0, "end_ms": 2310, "text": "xin chào", "confidence": 0.9}
    ]
    assert body["raw"]["text"] == "xin chào"
    assert body["model"] == {"provider": "fake", "model": "fake-asr-v1", "input_sample_rate": 16000}
    assert body["audio"]["source"] == "upload"
    assert (body["audio"]["format"], body["audio"]["sample_rate"]) == ("PCM_16", 16000)
    assert body["audio"]["duration_ms"] == 3000
    assert body["latency_ms"]["download"] is None
    assert body["latency_ms"]["total"] >= body["latency_ms"]["asr"]
    assert body["preprocessing"]["steps"] == ["DC_REMOVAL", "VAD_SEGMENT"]
    assert body["warnings"] == []


def test_url_is_downloaded(stt_client: TestClient, remote_wav: list[httpx.Request]) -> None:
    response = stt_client.post(
        "/v1/stt/transcribe", json={"audio_url": "https://clips.example/a.wav"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["audio"]["source"] == "url"
    assert body["latency_ms"]["download"] is not None
    assert body["raw"] is None
    assert str(remote_wav[0].url) == "https://clips.example/a.wav"


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "ftp://clips.example/a.wav", "http://127.0.0.1/a.wav", "not a url"],
)
def test_non_public_urls_are_rejected(stt_client: TestClient, url: str) -> None:
    response = stt_client.post("/v1/stt/transcribe", json={"audio_url": url})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "URL_NOT_ALLOWED"


def test_hostname_resolving_to_private_ip_is_rejected(
    stt_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stt_eval, "_resolve", _resolver({"intranet.example": "10.0.0.5"}))

    response = stt_client.post(
        "/v1/stt/transcribe", json={"audio_url": "http://intranet.example/a.wav"}
    )

    assert response.json()["detail"]["code"] == "URL_NOT_ALLOWED"


def test_redirect_to_private_ip_is_rejected(
    stt_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        stt_eval,
        "_resolve",
        _resolver({"clips.example": PUBLIC_IP, "metadata.internal": "169.254.169.254"}),
    )
    monkeypatch.setattr(
        stt_eval,
        "_transport",
        httpx.MockTransport(
            lambda request: httpx.Response(302, headers={"location": "http://metadata.internal/"})
        ),
    )

    response = stt_client.post(
        "/v1/stt/transcribe", json={"audio_url": "https://clips.example/a.wav"}
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "URL_NOT_ALLOWED"


def test_oversized_audio_is_rejected(
    stt_client: TestClient, remote_wav: list[httpx.Request], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stt_eval, "MAX_AUDIO_BYTES", 1000)

    uploaded = _upload(stt_client, _wav())
    downloaded = stt_client.post(
        "/v1/stt/transcribe", json={"audio_url": "https://clips.example/a.wav"}
    )

    for response in (uploaded, downloaded):
        assert response.status_code == 413
        assert response.json()["detail"]["code"] == "AUDIO_TOO_LARGE"


def test_upstream_errors_are_mapped(
    stt_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stt_eval, "_resolve", _resolver({"clips.example": PUBLIC_IP}))

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    cases = [
        (httpx.MockTransport(lambda request: httpx.Response(404)), 502, "AUDIO_URL_FETCH_FAILED"),
        (httpx.MockTransport(timeout), 504, "AUDIO_URL_TIMEOUT"),
    ]
    for transport, status, code in cases:
        monkeypatch.setattr(stt_eval, "_transport", transport)
        response = stt_client.post(
            "/v1/stt/transcribe", json={"audio_url": "https://clips.example/a.wav"}
        )
        assert (response.status_code, response.json()["detail"]["code"]) == (status, code)


def test_invalid_wav_is_rejected(stt_client: TestClient) -> None:
    response = _upload(stt_client, b"RIFF....not a wav")

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_WAV"


def test_bearer_key_is_required_when_configured(
    stt_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(http_settings, "bot_api_keys", "sk_test")

    assert _upload(stt_client, _wav()).status_code == 401
    authorized = stt_client.post(
        "/v1/stt/transcribe/upload",
        files={"file": ("a.wav", _wav(), "audio/wav")},
        headers={"Authorization": "Bearer sk_test"},
    )
    assert authorized.status_code == 200


def test_turn_upload_returns_transcript_and_production(stt_client: TestClient) -> None:
    response = _upload_turn(stt_client, _wav(), compare="true")

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["text"], body["confidence"], body["is_silence"]) == ("xin chào", 0.9, False)
    assert body["production"]["text"] == "xin chào"
    assert "segments" not in body
    assert body["audio"]["source"] == "upload"
    assert body["audio"]["duration_ms"] == 3000
    assert body["preprocessing"]["steps"] == ["DC_REMOVAL"]
    assert set(body["latency_ms"]) == {"download", "decode", "preprocess", "asr", "total"}
    assert body["warnings"] == []


def test_turn_url_is_downloaded(stt_client: TestClient, remote_wav: list[httpx.Request]) -> None:
    response = stt_client.post("/v1/stt/turn", json={"audio_url": "https://clips.example/a.wav"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["audio"]["source"] == "url"
    assert body["latency_ms"]["download"] is not None
    assert body["production"] is None


def test_turn_longer_than_30_seconds_is_rejected(stt_client: TestClient) -> None:
    long_clip = encode_wav(AudioSegment(pcm=b"\x00\x00" * 8_000 * 31, sample_rate=8_000))

    response = _upload_turn(stt_client, long_clip)

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "AUDIO_TOO_LONG",
        "message": "Audio dài quá 30 giây",
    }


def test_turn_requires_bearer_key(stt_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(http_settings, "bot_api_keys", "sk_test")

    assert _upload_turn(stt_client, _wav()).status_code == 401


def _room_tone_wav() -> bytes:
    pcm = np.random.default_rng(0).normal(0, 15, 48_000).astype(np.int16).tobytes()  # ~ −67 dBFS
    return encode_wav(AudioSegment(pcm=pcm, sample_rate=16_000))


def test_turn_returns_silence_for_room_tone_without_asr(stt_client: TestClient) -> None:
    """Hồi quy (bộ PM, B-SIL-01): tiếng phòng bị khuếch đại +20 dB rồi model bịa ra "ĐÂY"."""
    asr = stt_client.app.state.speech.asr
    calls_before = len(asr.received)  # lúc khởi động app đã warm-up ASR một lần

    response = _upload_turn(stt_client, _room_tone_wav())

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["text"], body["is_silence"]) == ("", True)
    assert body["preprocessing"]["steps"] == ["DC_REMOVAL", "VAD_NO_SPEECH"]
    assert body["preprocessing"]["gain_db"] == 0.0
    assert len(asr.received) == calls_before


def test_silence_gate_can_be_turned_off(
    stt_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stt_client.app.state, "stt_silence_gate", False)

    body = _upload_turn(stt_client, _room_tone_wav()).json()

    assert body["text"] == "xin chào"
    assert "VAD_NO_SPEECH" not in body["preprocessing"]["steps"]
