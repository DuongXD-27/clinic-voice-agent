"""ElevenLabsTTS qua fake WebSocket: giao thức stream-input, gom chunk, timing, phân loại lỗi (AC-2, AC-3)."""

from urllib.parse import parse_qs, urlparse

import pytest
from websockets.exceptions import ConnectionClosedError, WebSocketException
from websockets.frames import Close

from inference.tts.config import ElevenLabsTTSConfig
from inference.tts.providers.elevenlabs import (
    ElevenLabsTTS,
    TTSError,
    TTSRejected,
    TTSTiming,
    TTSUnavailable,
    sample_rate_of,
)
from tests.inference.tts.providers.fake_ws import (
    FakeConnect,
    FakeWebSocket,
    audio_message,
    closed_ok,
    error_message,
    final_message,
    handshake_error,
)

KEY = "sk_test_key_khong_duoc_lot_vao_message"
VOICE = "voice_123"
TEXT = "Dạ em xin chào anh chị."
CHUNKS = [b"\x01\x00" * 400, b"\x02\x00" * 400, b"\x03\x00" * 80]


def _config(**overrides) -> ElevenLabsTTSConfig:
    fields = {"api_key": KEY, "voice_id": VOICE, "_env_file": None}
    fields.update(overrides)
    return ElevenLabsTTSConfig(**fields)


def _tts(connect: FakeConnect, **overrides) -> ElevenLabsTTS:
    return ElevenLabsTTS(_config(**overrides), connect=connect)


def _happy_connect(**kwargs) -> FakeConnect:
    return FakeConnect([audio_message(c) for c in CHUNKS] + [final_message()], **kwargs)


# --- giao thức ---------------------------------------------------------------------------------


def test_synthesize_joins_chunks_in_order_at_8khz() -> None:
    connect = _happy_connect()
    result = _tts(connect).synthesize(TEXT)

    assert result.pcm == b"".join(CHUNKS)
    assert result.sample_rate == 8000
    assert connect.sockets[0].closed


def test_endpoint_carries_model_format_language_and_auto_mode() -> None:
    connect = _happy_connect()
    _tts(connect, model="eleven_flash_v2_5").synthesize(TEXT)

    uri = urlparse(connect.calls[0]["uri"])
    assert uri.scheme == "wss" and uri.netloc == "api.elevenlabs.io"
    assert uri.path == f"/v1/text-to-speech/{VOICE}/stream-input"
    query = parse_qs(uri.query)
    assert query["model_id"] == ["eleven_flash_v2_5"]
    assert query["output_format"] == ["pcm_8000"]
    assert query["language_code"] == ["vi"]
    assert query["auto_mode"] == ["true"]


def test_language_code_none_means_autodetect() -> None:
    connect = _happy_connect()
    _tts(connect, language_code=None).synthesize(TEXT)
    assert "language_code" not in parse_qs(urlparse(connect.calls[0]["uri"]).query)


def test_key_goes_in_header_not_in_messages() -> None:
    connect = _happy_connect()
    _tts(connect).synthesize(TEXT)

    assert connect.calls[0]["additional_headers"] == {"xi-api-key": KEY}
    sent = connect.sockets[0].sent
    assert KEY not in str(sent)
    # BOS -> text + flush -> EOS, đúng thứ tự; text gửi nguyên văn + khoảng trắng kết
    assert sent[0] == {"text": " "}
    assert sent[1] == {"text": TEXT + " ", "flush": True}
    assert sent[2] == {"text": ""}


def test_server_closing_without_isfinal_still_returns_audio() -> None:
    connect = FakeConnect([audio_message(CHUNKS[0]), closed_ok()])
    result = _tts(connect).synthesize(TEXT)
    assert result.pcm == CHUNKS[0]


def test_stream_yields_chunks_as_received() -> None:
    connect = _happy_connect()
    assert list(_tts(connect).stream(TEXT)) == CHUNKS


# --- timing (TTS-1.6) --------------------------------------------------------------------------


def test_timing_fields_are_filled_without_text() -> None:
    result, timing = _tts(_happy_connect()).synthesize_timed(TEXT)

    assert timing.chars == len(TEXT)
    assert timing.chunks == 3
    assert timing.audio_bytes == len(result.pcm)
    for field in ("connect_ms", "ttfa_ms", "last_chunk_ms", "total_ms"):
        assert isinstance(getattr(timing, field), int), field
    assert timing.connect_ms <= timing.ttfa_ms <= timing.last_chunk_ms <= timing.total_ms
    assert TEXT not in str(timing.to_trace())


def test_stream_fills_caller_supplied_timing() -> None:
    timing = TTSTiming()
    list(_tts(_happy_connect()).stream(TEXT, timing))
    assert timing.chunks == 3 and timing.total_ms is not None


# --- lỗi -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code", ["payment_required", "quota_exceeded", "invalid_api_key", "voice_not_found"]
)
def test_in_stream_rejection_codes(code: str) -> None:
    connect = FakeConnect([error_message(code)])
    with pytest.raises(TTSRejected) as exc:
        _tts(connect).synthesize(TEXT)
    assert exc.value.code == code


@pytest.mark.parametrize("code", ["too_many_concurrent_requests", "system_busy", "unknown_x"])
def test_in_stream_unknown_or_transient_codes_are_unavailable(code: str) -> None:
    connect = FakeConnect([error_message(code)])
    with pytest.raises(TTSUnavailable) as exc:
        _tts(connect).synthesize(TEXT)
    assert exc.value.code == code


@pytest.mark.parametrize("status", [401, 402, 403, 404, 422])
def test_handshake_4xx_is_rejected(status: int) -> None:
    connect = FakeConnect([], raise_on_connect=handshake_error(status))
    with pytest.raises(TTSRejected) as exc:
        _tts(connect).synthesize(TEXT)
    assert exc.value.code == f"http_{status}"


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_handshake_429_5xx_is_unavailable(status: int) -> None:
    connect = FakeConnect([], raise_on_connect=handshake_error(status))
    with pytest.raises(TTSUnavailable):
        _tts(connect).synthesize(TEXT)


def test_connect_timeout_is_unavailable() -> None:
    connect = FakeConnect([], raise_on_connect=TimeoutError("timed out during opening handshake"))
    with pytest.raises(TTSUnavailable) as exc:
        _tts(connect).synthesize(TEXT)
    assert exc.value.code == "timeout"


def test_recv_timeout_is_unavailable() -> None:
    connect = FakeConnect([audio_message(CHUNKS[0]), TimeoutError()])
    with pytest.raises(TTSUnavailable) as exc:
        _tts(connect).synthesize(TEXT)
    assert exc.value.code == "timeout"


def test_overall_deadline_enforced_across_chunks() -> None:
    # Mỗi recv tốn 30 ms, timeout tổng 50 ms: chunk thứ 2 phải bị chặn dù từng recv không quá hạn
    connect = _happy_connect(recv_delay_s=0.03)
    with pytest.raises(TTSUnavailable) as exc:
        _tts(connect, timeout_s=0.05).synthesize(TEXT)
    assert exc.value.code == "timeout"
    # open_timeout và recv timeout đều là phần thời gian còn lại, không phải hằng số
    assert connect.calls[0]["open_timeout"] <= 0.05
    assert all(t is not None and t <= 0.05 for t in connect.sockets[0].recv_timeouts)


def test_abnormal_close_is_unavailable() -> None:
    connect = FakeConnect([ConnectionClosedError(Close(1011, "internal"), None)])
    with pytest.raises(TTSUnavailable) as exc:
        _tts(connect).synthesize(TEXT)
    assert exc.value.code == "connection_closed"


@pytest.mark.parametrize("error", [OSError("dns"), WebSocketException("x")])
def test_network_errors_are_unavailable(error: BaseException) -> None:
    connect = FakeConnect([], raise_on_connect=error)
    with pytest.raises(TTSUnavailable) as exc:
        _tts(connect).synthesize(TEXT)
    assert exc.value.code == "connection_failed"


def test_no_audio_before_final_is_unavailable() -> None:
    connect = FakeConnect([final_message()])
    with pytest.raises(TTSUnavailable) as exc:
        _tts(connect).synthesize(TEXT)
    assert exc.value.code == "no_audio"


@pytest.mark.parametrize("raw", ["không phải json", "[1, 2]"])
def test_non_json_or_non_object_message_is_unavailable(raw: str) -> None:
    class GarbageSocket(FakeWebSocket):
        def recv(self, timeout=None, decode=None) -> str:
            return raw

    def connect(uri: str, **kwargs) -> FakeWebSocket:
        return GarbageSocket([])

    with pytest.raises(TTSUnavailable) as exc:
        ElevenLabsTTS(_config(), connect=connect).synthesize(TEXT)
    assert exc.value.code == "bad_message"


def test_empty_text_is_rejected_without_connecting() -> None:
    connect = _happy_connect()
    with pytest.raises(TTSRejected):
        _tts(connect).synthesize("   ")
    assert connect.calls == []


def test_errors_never_expose_websockets_types() -> None:
    cases = [
        FakeConnect([], raise_on_connect=handshake_error(401)),
        FakeConnect([ConnectionClosedError(Close(1011, ""), None)]),
        FakeConnect([error_message("payment_required")]),
    ]
    for connect in cases:
        with pytest.raises(TTSError) as exc:
            _tts(connect).synthesize(TEXT)
        assert not isinstance(exc.value, WebSocketException)
        assert "websockets" not in str(exc.value).lower()


# --- cấu hình -----------------------------------------------------------------------------------


@pytest.mark.parametrize("fmt, rate", [("pcm_8000", 8000), ("pcm_16000", 16000)])
def test_sample_rate_of_pcm(fmt: str, rate: int) -> None:
    assert sample_rate_of(fmt) == rate


@pytest.mark.parametrize("fmt", ["ulaw_8000", "mp3_44100_128", "pcm", "pcm_x"])
def test_non_pcm_format_rejected(fmt: str) -> None:
    with pytest.raises(ValueError):
        sample_rate_of(fmt)


@pytest.mark.parametrize(
    "overrides, missing",
    [
        ({"api_key": "", "voice_id": VOICE}, "ELEVENLABS_API_KEY"),
        ({"api_key": KEY, "voice_id": ""}, "ELEVENLABS_VOICE_ID"),
    ],
)
def test_missing_credentials_fail_fast(overrides: dict, missing: str) -> None:
    with pytest.raises(ValueError, match=missing):
        ElevenLabsTTS(_config(**overrides), connect=FakeConnect([]))
