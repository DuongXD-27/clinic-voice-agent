"""VbeeTTS qua httpx.MockTransport: payload/header, PCM 8 kHz, phân loại lỗi, không lộ token."""

import asyncio
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


def test_consecutive_sentences_share_one_client() -> None:
    clients: list[httpx.Client] = []
    transport = httpx.MockTransport(_audio())

    def factory() -> httpx.Client:
        clients.append(httpx.Client(transport=transport))
        return clients[-1]

    tts = VbeeTTS(_config(), client_factory=factory)
    for _ in range(3):
        assert tts.synthesize(TEXT).pcm == PCM

    assert len(clients) == 1
    assert not clients[0].is_closed


def test_client_survives_errors_and_closes_once() -> None:
    statuses = iter([503, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(statuses)
        return httpx.Response(status, content=PCM, headers={"content-type": "audio/pcm"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    tts = VbeeTTS(_config(), client_factory=lambda: client)

    with pytest.raises(TTSUnavailable):
        tts.synthesize(TEXT)
    assert tts.synthesize(TEXT).pcm == PCM

    tts.close()
    assert client.is_closed


def test_default_client_keeps_idle_connection_for_configured_time() -> None:
    tts = VbeeTTS(_config(keepalive_s=42.0, timeout_s=2.5, connect_timeout_s=1.0))
    try:
        pool = tts._client._transport._pool
        assert pool._keepalive_expiry == 42.0
        assert tts._client.timeout == httpx.Timeout(2.5, connect=1.0)
    finally:
        tts.close()


# --- synthesize_stream / cancel (đường LiveKit) ------------------------------------------------


def _stream_tts(handler, **overrides) -> VbeeTTS:
    transport = httpx.MockTransport(handler)
    return VbeeTTS(
        _config(**overrides),
        client_factory=lambda: httpx.Client(transport=transport),
        async_client_factory=lambda: httpx.AsyncClient(transport=transport),
    )


def _chunked(*parts: bytes, delay_s: float = 0.0):
    async def body():
        for part in parts:
            if delay_s:
                await asyncio.sleep(delay_s)
            yield part

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body(), headers={"content-type": "audio/pcm"})

    return handler


class _HeldStream(httpx.AsyncByteStream):
    """Trả `parts` rồi treo như Vbee còn đang sinh; aclose() làm lần đọc đang chờ ném ReadError,
    đúng như httpx thật khi response bị đóng từ task khác (đã thử với server local)."""

    def __init__(self, *parts: bytes) -> None:
        self._parts = parts
        self._closed = asyncio.Event()
        self.closed = False

    async def __aiter__(self):
        for part in self._parts:
            yield part
        await self._closed.wait()
        raise httpx.ReadError("connection closed")

    async def aclose(self) -> None:
        self.closed = True
        self._closed.set()


def _held(stream: _HeldStream):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream, headers={"content-type": "audio/pcm"})

    return handler


async def _collect(tts: VbeeTTS, text: str = TEXT) -> list[bytes]:
    return [chunk async for chunk in tts.synthesize_stream(text)]


async def test_stream_yields_chunks_in_order_with_same_request_as_sync() -> None:
    seen: list[httpx.Request] = []
    parts = (b"\x01\x00" * 100, b"\x02\x00" * 50, b"\x03\x00" * 10)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _chunked(*parts)(request)

    tts = _stream_tts(handler)
    assert await _collect(tts, f"  {TEXT} ") == list(parts)

    request = seen[0]
    assert str(request.url) == "https://api.vbee.vn/v1/tts"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert json.loads(request.content)["text"] == TEXT
    assert json.loads(request.content)["sampleRate"] == 8000
    await tts.aclose()


async def test_stream_carries_odd_byte_into_next_chunk() -> None:
    # Vbee cắt chunk theo byte HTTP, vd. 4090 B rồi 6 B: mẫu PCM16 bị chia đôi giữa hai chunk
    chunks = await _collect(_stream_tts(_chunked(b"\x01\x02\x03", b"\x04\x05", b"\x06\x07\x08")))

    assert chunks == [b"\x01\x02", b"\x03\x04", b"\x05\x06\x07\x08"]


async def test_stream_drops_trailing_odd_byte() -> None:
    assert await _collect(_stream_tts(_chunked(PCM + b"\x07"))) == [PCM]


@pytest.mark.parametrize(
    ("status", "error_type"),
    [(401, TTSRejected), (402, TTSRejected), (429, TTSUnavailable), (503, TTSUnavailable)],
)
async def test_stream_http_status_is_classified(status: int, error_type: type[TTSError]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "x"})

    with pytest.raises(error_type) as err:
        await _collect(_stream_tts(handler))
    assert err.value.code == f"http_{status}"
    assert TOKEN not in str(err.value)


@pytest.mark.parametrize(
    ("handler", "code"),
    [
        (_audio(b'{"status": 0}', "application/json"), "bad_response"),
        (_audio(b""), "no_audio"),
    ],
)
async def test_stream_bad_body_is_unavailable(handler, code: str) -> None:
    with pytest.raises(TTSUnavailable) as err:
        await _collect(_stream_tts(handler))
    assert err.value.code == code


async def test_stream_network_errors_are_unavailable() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(TTSUnavailable) as err:
        await _collect(_stream_tts(timeout))
    assert err.value.code == "timeout"
    with pytest.raises(TTSUnavailable) as err:
        await _collect(_stream_tts(refused))
    assert err.value.code == "connection_failed"


@pytest.mark.parametrize(("text", "code"), [("   ", "empty_text"), ("a" * 301, "text_too_long")])
async def test_stream_rejects_bad_text_without_request(text: str, code: str) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=PCM)

    with pytest.raises(TTSRejected) as err:
        await _collect(_stream_tts(handler), text)
    assert err.value.code == code
    assert calls == []


async def test_stream_deadline_ignores_time_spent_playing() -> None:
    # Bên phát giữ generator lâu hơn timeout_s (đang phát audio) không được tính là Vbee chậm
    tts = _stream_tts(_chunked(PCM, PCM, PCM), timeout_s=0.05)
    chunks = []
    async for chunk in tts.synthesize_stream(TEXT):
        chunks.append(chunk)
        await asyncio.sleep(0.08)
    assert chunks == [PCM, PCM, PCM]


async def test_stream_deadline_counts_time_waiting_for_vbee() -> None:
    tts = _stream_tts(_chunked(PCM, PCM, PCM, PCM, delay_s=0.06), timeout_s=0.1)
    with pytest.raises(TTSUnavailable) as err:
        await _collect(tts)
    assert err.value.code == "timeout"


@pytest.mark.parametrize("stage", ["headers", "first_byte"])
async def test_stream_deadline_bounds_wait_before_first_byte(stage: str) -> None:
    # Trước đây trần chỉ kiểm sau khi có chunk: Vbee treo trước byte đầu thì chỉ còn timeout
    # từng pha của httpx (connect + read > trần), cộng ElevenLabs là vượt 8 s/lượt
    async def slow_body():
        await asyncio.sleep(5)
        yield PCM

    async def handler(request: httpx.Request) -> httpx.Response:
        if stage == "headers":
            await asyncio.sleep(5)
        return httpx.Response(200, content=slow_body(), headers={"content-type": "audio/pcm"})

    started = asyncio.get_running_loop().time()
    with pytest.raises(TTSUnavailable) as err:
        await _collect(_stream_tts(handler, timeout_s=0.1))
    assert err.value.code == "timeout"
    assert asyncio.get_running_loop().time() - started < 1.0


async def test_late_close_of_old_stream_does_not_break_cancel_of_current_one() -> None:
    # CallBridge bỏ generator câu cũ mà không aclose: finally của nó chạy muộn, lúc câu mới đã
    # phát. Trước đây finally đó xoá response đang mở của câu mới, barge-in không đóng được.
    old, current = _HeldStream(PCM), _HeldStream(PCM)
    streams = iter([old, current])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=next(streams), headers={"content-type": "audio/pcm"})

    tts = _stream_tts(handler)
    old_chunks = tts.synthesize_stream(TEXT)
    assert await anext(old_chunks) == PCM
    current_chunks = tts.synthesize_stream(TEXT)
    assert await anext(current_chunks) == PCM

    await old_chunks.aclose()
    await tts.cancel()

    assert current.closed
    assert [chunk async for chunk in current_chunks] == []


async def test_cancel_between_chunks_stops_stream_and_closes_request() -> None:
    stream = _HeldStream(PCM, PCM, PCM)
    tts = _stream_tts(_held(stream))
    chunks = tts.synthesize_stream(TEXT)

    assert await anext(chunks) == PCM
    await tts.cancel()

    assert [chunk async for chunk in chunks] == []
    assert stream.closed


async def test_cancel_while_waiting_for_vbee_ends_stream_without_error() -> None:
    # Khách nói chen lúc Vbee chưa trả xong: task phát đang chờ đọc, cancel() từ task khác
    stream = _HeldStream(PCM)
    tts = _stream_tts(_held(stream))
    chunks = tts.synthesize_stream(TEXT)
    assert await anext(chunks) == PCM

    pending = asyncio.create_task(anext(chunks, None))
    await asyncio.sleep(0.01)
    assert not pending.done()
    await tts.cancel()

    assert await asyncio.wait_for(pending, 1.0) is None
    assert stream.closed


async def test_cancel_before_first_chunk_yields_nothing() -> None:
    stream = _HeldStream()
    tts = _stream_tts(_held(stream))

    pending = asyncio.create_task(_collect(tts))
    await asyncio.sleep(0.01)
    await tts.cancel()

    assert await asyncio.wait_for(pending, 1.0) == []
    assert stream.closed


async def test_next_stream_after_cancel_plays_normally() -> None:
    tts = _stream_tts(_chunked(PCM, PCM))
    await tts.cancel()
    assert await _collect(tts) == [PCM, PCM]


async def test_streams_share_one_async_client_and_aclose_closes_both() -> None:
    created: list[httpx.AsyncClient] = []
    transport = httpx.MockTransport(_chunked(PCM))
    sync_client = httpx.Client(transport=transport)

    def factory() -> httpx.AsyncClient:
        created.append(httpx.AsyncClient(transport=transport))
        return created[-1]

    tts = VbeeTTS(_config(), client_factory=lambda: sync_client, async_client_factory=factory)
    for _ in range(3):
        assert await _collect(tts) == [PCM]

    assert len(created) == 1
    await tts.aclose()
    assert created[0].is_closed
    assert sync_client.is_closed


def test_sync_only_use_never_opens_async_client() -> None:
    created: list[httpx.AsyncClient] = []
    tts = VbeeTTS(
        _config(),
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(_audio())),
        async_client_factory=lambda: created.append(httpx.AsyncClient()) or created[-1],
    )
    assert tts.synthesize(TEXT).pcm == PCM
    tts.close()
    assert created == []


async def test_default_async_client_keeps_idle_connection_for_configured_time() -> None:
    tts = VbeeTTS(_config(keepalive_s=42.0, timeout_s=2.5, connect_timeout_s=1.0))
    client = tts._default_async_client()
    try:
        assert client._transport._pool._keepalive_expiry == 42.0
        assert client.timeout == httpx.Timeout(2.5, connect=1.0)
    finally:
        await client.aclose()
        await tts.aclose()


def test_missing_credentials_fail_at_construction() -> None:
    with pytest.raises(ValueError, match="VBEE_API_TOKEN"):
        VbeeTTS(_config(api_token=""))
    with pytest.raises(ValueError, match="VBEE_APP_ID"):
        VbeeTTS(_config(app_id=""))
