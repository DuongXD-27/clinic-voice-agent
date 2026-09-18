"""VbeeTTS qua httpx.MockTransport: header/body, gom chunk, cắt 300 ký tự, phân loại lỗi."""

import json
from typing import Any, Callable, Optional

import httpx
import pytest

from callbot.speech.audio.codec import encode_wav
from callbot.speech.tts.errors import TTSError, TTSRejected, TTSUnavailable
from callbot.speech.tts.vbee import MAX_CHARS, VbeeTTS, split_text
from callbot.speech.types import AudioSegment

TOKEN, APP_ID, VOICE = "tok_test", "app_test", "hn_female_ngochuyen_full_48k-fhg"
TEXT = "Dạ em xin chào anh chị."
CHUNKS = [b"\x01\x00" * 400, b"\x02\x00" * 400, b"\x03\x00" * 80]


class Recorder:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]


def _tts(
    handler: Callable[[httpx.Request], httpx.Response], recorder: Optional[Recorder] = None, **kw
) -> VbeeTTS:
    def wrapped(request: httpx.Request) -> httpx.Response:
        if recorder is not None:
            recorder.requests.append(request)
        return handler(request)

    return VbeeTTS(TOKEN, APP_ID, VOICE, transport=httpx.MockTransport(wrapped), **kw)


def _stream_pcm(chunks: list[bytes]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=httpx.ByteStream(b"".join(chunks)))

    return handler


def _error(status: int, code: Optional[str], message: str = "x") -> Callable:
    def handler(request: httpx.Request) -> httpx.Response:
        if code is None:
            return httpx.Response(status, text="<html>gateway</html>")
        return httpx.Response(status, json={"error": {"code": code, "message": message}})

    return handler


# --- giao thức ---------------------------------------------------------------------------------


def test_synthesize_returns_pcm_8khz_and_sends_documented_fields() -> None:
    rec = Recorder()
    segment = _tts(_stream_pcm(CHUNKS), rec).synthesize(TEXT)

    assert segment == AudioSegment(pcm=b"".join(CHUNKS), sample_rate=8000)
    request = rec.requests[0]
    assert request.method == "POST" and str(request.url) == "https://api.vbee.vn/v1/tts"
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert request.headers["App-Id"] == APP_ID
    assert request.headers["Content-Type"] == "application/json"
    assert rec.bodies()[0] == {
        "text": TEXT,
        "mode": "sync",
        "voiceCode": VOICE,
        "outputFormat": "pcm",
        "sampleRate": 8000,
        "speed": 1.0,
    }


def test_timing_filled_without_text() -> None:
    segment, timing = _tts(_stream_pcm(CHUNKS)).synthesize_timed(TEXT)
    assert timing.chars == len(TEXT)
    assert timing.audio_bytes == len(segment.pcm) and timing.chunks >= 1
    assert timing.connect_ms is not None and timing.ttfa_ms is not None
    assert timing.ttfa_ms <= timing.last_chunk_ms <= timing.total_ms
    assert TEXT not in str(timing.to_trace())


def test_wav_body_is_unwrapped_to_pcm() -> None:
    pcm = b"\x05\x00" * 1000
    wav = encode_wav(AudioSegment(pcm=pcm, sample_rate=8000))
    segment = _tts(_stream_pcm([wav[:20], wav[20:]])).synthesize(TEXT)
    assert segment.pcm == pcm


def test_custom_sample_rate_and_speed_forwarded() -> None:
    rec = Recorder()
    tts = _tts(_stream_pcm(CHUNKS), rec, sample_rate=16000, speed=1.2)
    segment = tts.synthesize(TEXT)
    assert segment.sample_rate == 16000
    assert rec.bodies()[0]["sampleRate"] == 16000 and rec.bodies()[0]["speed"] == 1.2


# --- cắt 300 ký tự -----------------------------------------------------------------------------


def test_split_text_keeps_every_word_and_respects_limit() -> None:
    sentence = "Dạ em xin xác nhận lịch khám ngày mười bốn tháng mười, chín giờ sáng tại Vinmec Times City. "
    text = (sentence * 6).strip()  # ~560 ký tự
    pieces = split_text(text)

    assert len(pieces) >= 2
    assert all(0 < len(p) <= MAX_CHARS for p in pieces)
    assert " ".join(pieces).split() == text.split()
    # cắt tại ranh giới câu, không cắt giữa từ
    assert all(p.endswith(".") for p in pieces[:-1])


def test_split_text_short_and_empty() -> None:
    assert split_text("  xin chào  ") == ["xin chào"]
    assert split_text("   ") == []


def test_long_utterance_goes_out_as_sequential_requests_in_order() -> None:
    rec = Recorder()
    text = ("Câu thứ nhất khá dài để vượt giới hạn. " * 10).strip()  # > 300
    pieces = split_text(text)

    def handler(request: httpx.Request) -> httpx.Response:
        idx = pieces.index(json.loads(request.content)["text"])
        return httpx.Response(200, stream=httpx.ByteStream(bytes([idx + 1, 0]) * 10))

    segment = _tts(handler, rec).synthesize(text)
    assert [b["text"] for b in rec.bodies()] == pieces
    assert segment.pcm == b"".join(bytes([i + 1, 0]) * 10 for i in range(len(pieces)))


# --- lỗi -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status, code",
    [(401, "UNAUTHORIZED"), (400, "BAD_REQUEST"), (400, "BAD_REQUEST")],
)
def test_4xx_is_rejected_with_vbee_code(status: int, code: str) -> None:
    with pytest.raises(TTSRejected) as exc:
        _tts(_error(status, code, "text must be less than or equal to 300 characters")).synthesize(
            TEXT
        )
    assert exc.value.code == code
    assert "300" in str(exc.value)


@pytest.mark.parametrize(
    "status, code",
    [
        (429, "TTS_CCR_MAX_LIMIT_REACHED"),
        (500, "TTS_SPEND_CREDITS_FAILED"),
        (500, "INTERNAL_SERVER_ERROR"),
        (502, None),
    ],
)
def test_429_5xx_is_unavailable(status: int, code: Optional[str]) -> None:
    with pytest.raises(TTSUnavailable) as exc:
        _tts(_error(status, code)).synthesize(TEXT)
    assert exc.value.code == (code or f"http_{status}")


@pytest.mark.parametrize("error", [httpx.ConnectTimeout("t"), httpx.ReadTimeout("t")])
def test_timeouts_are_unavailable(error: Exception) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    with pytest.raises(TTSUnavailable) as exc:
        _tts(handler).synthesize(TEXT)
    assert exc.value.code == "timeout"


def test_connect_error_is_unavailable_without_httpx_types() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns")

    with pytest.raises(TTSError) as exc:
        _tts(handler).synthesize(TEXT)
    assert isinstance(exc.value, TTSUnavailable) and exc.value.code == "connection_failed"
    assert not isinstance(exc.value, httpx.HTTPError)
    assert "httpx" not in str(exc.value).lower()


def test_empty_body_is_no_audio() -> None:
    with pytest.raises(TTSUnavailable) as exc:
        _tts(_stream_pcm([])).synthesize(TEXT)
    assert exc.value.code == "no_audio"


def test_empty_text_rejected_without_request() -> None:
    rec = Recorder()
    with pytest.raises(TTSRejected):
        _tts(_stream_pcm(CHUNKS), rec).synthesize("   ")
    assert rec.requests == []


@pytest.mark.parametrize("kwargs", [dict(access_token=""), dict(app_id=""), dict(voice_code="")])
def test_missing_credentials_fail_fast(kwargs: dict) -> None:
    args = dict(access_token=TOKEN, app_id=APP_ID, voice_code=VOICE)
    args.update(kwargs)
    with pytest.raises(ValueError):
        VbeeTTS(args["access_token"], args["app_id"], args["voice_code"])
