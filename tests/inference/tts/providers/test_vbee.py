"""VbeeTTS qua httpx.MockTransport: payload/header, PCM 8 kHz, phân loại lỗi, không lộ token."""

import json

import httpx
import pytest

from inference.tts.config import VbeeTTSConfig
from inference.tts.errors import TTSError, TTSRejected, TTSUnavailable
from inference.tts.providers.vbee import MAX_TEXT_CHARS, VbeeTTS

TOKEN = "vbee_token_khong_duoc_lot_vao_message"
APP_ID = "app_123"
TEXT = "Dạ em xin chào anh chị."
PCM = b"\x01\x00" * 400


def _config(**overrides) -> VbeeTTSConfig:
    fields = {"api_token": TOKEN, "app_id": APP_ID, "_env_file": None}
    fields.update(overrides)
    return VbeeTTSConfig(**fields)


def _tts(handler, **overrides) -> VbeeTTS:
    transport = httpx.MockTransport(handler)
    return VbeeTTS(_config(**overrides), client_factory=lambda: httpx.Client(transport=transport))


def _audio(body: bytes = PCM, content_type: str = "audio/pcm"):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": content_type})

    return handler


def test_synthesize_returns_pcm_at_8khz_with_voice_as_model() -> None:
    tts = _tts(_audio())
    result = tts.synthesize(TEXT)

    assert result.pcm == PCM
    assert result.sample_rate == 8000
    assert tts.model == "hn_female_ngochuyen_full_48k-fhg"
    assert result.voice == tts.model
    assert result.ttfa_ms is not None and result.ttfa_ms >= 0


def test_request_carries_auth_headers_and_pcm_payload() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=PCM, headers={"content-type": "audio/pcm"})

    _tts(handler, voice_code="v_test", speed=1.1).synthesize(TEXT)

    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == "https://api.vbee.vn/v1/tts"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert request.headers["app-id"] == APP_ID
    assert json.loads(request.content) == {
        "text": TEXT,
        "mode": "sync",
        "voiceCode": "v_test",
        "outputFormat": "pcm",
        "sampleRate": 8000,
        "bitrate": 128,
        "speed": 1.1,
    }


def test_odd_trailing_byte_is_dropped() -> None:
    assert _tts(_audio(PCM + b"\x07")).synthesize(TEXT).pcm == PCM


def test_text_over_limit_is_rejected_without_request() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=PCM)

    with pytest.raises(TTSRejected) as err:
        _tts(handler).synthesize("a" * (MAX_TEXT_CHARS + 1))
    assert err.value.code == "text_too_long"
    assert calls == []


@pytest.mark.parametrize(
    ("status", "error_type"),
    [(401, TTSRejected), (402, TTSRejected), (429, TTSUnavailable), (503, TTSUnavailable)],
)
def test_http_status_is_classified(status: int, error_type: type[TTSError]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "x"})

    with pytest.raises(error_type) as err:
        _tts(handler).synthesize(TEXT)
    assert err.value.code == f"http_{status}"
    assert TOKEN not in str(err.value)


def test_json_body_on_200_is_unavailable() -> None:
    with pytest.raises(TTSUnavailable) as err:
        _tts(_audio(b'{"status": 0}', "application/json")).synthesize(TEXT)
    assert err.value.code == "bad_response"


def test_empty_audio_is_unavailable() -> None:
    with pytest.raises(TTSUnavailable) as err:
        _tts(_audio(b"")).synthesize(TEXT)
    assert err.value.code == "no_audio"


def test_timeout_and_network_errors_are_unavailable() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(TTSUnavailable) as err:
        _tts(timeout).synthesize(TEXT)
    assert err.value.code == "timeout"
    with pytest.raises(TTSUnavailable) as err:
        _tts(refused).synthesize(TEXT)
    assert err.value.code == "connection_failed"


def test_missing_credentials_fail_at_construction() -> None:
    with pytest.raises(ValueError, match="VBEE_API_TOKEN"):
        VbeeTTS(_config(api_token=""))
    with pytest.raises(ValueError, match="VBEE_APP_ID"):
        VbeeTTS(_config(app_id=""))
