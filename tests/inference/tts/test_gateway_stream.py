"""TTSGateway.synthesize_stream: dự phòng đúng câu khi lỗi trước chunk đầu, lỗi giữa câu thì dừng
(không đọc lại), cancel tới provider đang chạy, không log text."""

import asyncio
import logging

import pytest

from inference.tts import TTSGateway, TTSResult
from inference.tts.errors import TTSRejected, TTSUnavailable

TEXT = "Dạ lịch hẹn của anh Nguyễn Văn A"
A, B, C = b"\x01\x00" * 4, b"\x02\x00" * 4, b"\x03\x00" * 4


class _Streamer:
    """Provider giả có stream: phát `chunks`, lỗi ở vị trí `fail_at` (0 = trước chunk đầu)."""

    stream_sample_rate = 8000

    def __init__(
        self,
        model: str,
        chunks: tuple[bytes, ...] = (A, B, C),
        *,
        fail_at: int | None = None,
        error: Exception | None = None,
        hold: bool = False,
    ) -> None:
        self.model = model
        self.voice = f"{model}-voice"
        self._chunks = chunks
        self._fail_at = fail_at
        self._error = error or TTSUnavailable("lỗi", code="http_503")
        self._hold = hold
        self._released = asyncio.Event()
        self.spoken: list[str] = []
        self.cancelled = 0
        self.closed = False

    def synthesize(self, text: str) -> TTSResult:  # pragma: no cover - không dùng ở đây
        raise AssertionError("stream không được gọi synthesize")

    async def synthesize_stream(self, text: str):
        self.spoken.append(text)
        try:
            for index, chunk in enumerate(self._chunks):
                if index == self._fail_at:
                    raise self._error
                yield chunk
                if self._hold and index == 0:
                    # Như Vbee còn đang sinh: chờ tới khi bị hủy
                    await self._released.wait()
                    return
            if self._fail_at == len(self._chunks):
                raise self._error
        finally:
            self.closed = True

    async def cancel(self) -> None:
        self.cancelled += 1
        self._released.set()


def _gateway(primary, backup=None) -> TTSGateway:
    fallback = TTSGateway(backup, provider_name="elevenlabs") if backup is not None else None
    return TTSGateway(primary, provider_name="vbee", fallback=fallback)


async def _collect(gateway: TTSGateway, text: str = TEXT) -> list[bytes]:
    return [chunk async for chunk in gateway.synthesize_stream(text)]


async def test_primary_streams_without_touching_fallback() -> None:
    primary, backup = _Streamer("vbee"), _Streamer("eleven")
    gateway = _gateway(primary, backup)

    assert await _collect(gateway, f"  {TEXT} ") == [A, B, C]
    assert primary.spoken == [TEXT]
    assert backup.spoken == []
    info = gateway.last_stream
    assert (info.provider_actual, info.voice, info.sample_rate) == ("vbee", "vbee-voice", 8000)
    assert info.fallback_used is False
    assert info.ttfa_ms is not None and info.error_code is None


async def test_error_before_first_chunk_switches_to_fallback_for_same_sentence(caplog) -> None:
    primary = _Streamer("vbee", fail_at=0)
    backup = _Streamer("eleven", (C,))
    gateway = _gateway(primary, backup)

    with caplog.at_level(logging.WARNING, logger="inference.tts.gateway"):
        assert await _collect(gateway) == [C]

    assert primary.spoken == backup.spoken == [TEXT]
    info = gateway.last_stream
    assert (info.provider_actual, info.voice, info.fallback_used) == (
        "elevenlabs",
        "eleven-voice",
        True,
    )
    assert "http_503" in caplog.text and "chuyển sang elevenlabs" in caplog.text
    assert "Nguyễn" not in caplog.text


async def test_rejected_text_also_falls_back() -> None:
    primary = _Streamer("vbee", fail_at=0, error=TTSRejected("dài", "text_too_long"))
    assert await _collect(_gateway(primary, _Streamer("eleven", (C,)))) == [C]


async def test_error_mid_sentence_stops_without_replay(caplog) -> None:
    # Đã phát A, B mà lỗi: đọc lại từ đầu sẽ lặp câu, audio khác utterance (§4.1.3)
    primary = _Streamer("vbee", fail_at=2, error=TTSUnavailable("rớt", code="connection_failed"))
    backup = _Streamer("eleven")
    gateway = _gateway(primary, backup)

    with caplog.at_level(logging.WARNING, logger="inference.tts.gateway"):
        assert await _collect(gateway) == [A, B]

    assert backup.spoken == []
    assert gateway.last_stream.error_code == "connection_failed"
    assert "giữa câu" in caplog.text and "chuyển sang" not in caplog.text
    assert "Nguyễn" not in caplog.text


async def test_both_fail_before_first_chunk_raises_fallback_error() -> None:
    primary = _Streamer("vbee", fail_at=0, error=TTSUnavailable("x", code="timeout"))
    backup = _Streamer("eleven", fail_at=0, error=TTSUnavailable("y", code="http_401"))
    gateway = _gateway(primary, backup)

    with pytest.raises(TTSUnavailable) as err:
        await _collect(gateway)
    assert err.value.code == "http_401"
    assert gateway.last_stream is None


async def test_fallback_error_mid_sentence_stops_and_is_recorded() -> None:
    primary = _Streamer("vbee", fail_at=0)
    backup = _Streamer("eleven", fail_at=1, error=TTSUnavailable("rớt", code="connection_closed"))
    gateway = _gateway(primary, backup)

    assert await _collect(gateway) == [A]
    assert gateway.last_stream.fallback_used is True
    assert gateway.last_stream.error_code == "connection_closed"


async def test_no_fallback_configured_raises() -> None:
    with pytest.raises(TTSUnavailable):
        await _collect(_gateway(_Streamer("vbee", fail_at=0)))


async def test_blank_text_calls_no_provider() -> None:
    primary, backup = _Streamer("vbee"), _Streamer("eleven")
    assert await _collect(_gateway(primary, backup), "   ") == []
    assert primary.spoken == backup.spoken == []


async def test_cancel_reaches_primary_and_does_not_fall_back() -> None:
    primary, backup = _Streamer("vbee", hold=True), _Streamer("eleven")
    gateway = _gateway(primary, backup)
    chunks = gateway.synthesize_stream(TEXT)

    assert await anext(chunks) == A
    pending = asyncio.create_task(anext(chunks, None))
    await asyncio.sleep(0.01)
    await gateway.cancel()

    assert await asyncio.wait_for(pending, 1.0) is None
    assert primary.cancelled == 1
    assert backup.spoken == []


async def test_error_after_cancel_does_not_switch_to_fallback() -> None:
    # Hủy đóng kết nối có thể làm provider ném lỗi đọc: đó là dừng chủ động, không phải lỗi
    primary = _Streamer("vbee", fail_at=1, error=TTSUnavailable("đóng", code="connection_failed"))
    backup = _Streamer("eleven")
    gateway = _gateway(primary, backup)
    chunks = gateway.synthesize_stream(TEXT)

    assert await anext(chunks) == A
    await gateway.cancel()
    assert [chunk async for chunk in chunks] == []
    assert backup.spoken == []


async def test_cancel_during_fallback_reaches_fallback_provider() -> None:
    primary = _Streamer("vbee", fail_at=0)
    backup = _Streamer("eleven", hold=True)
    gateway = _gateway(primary, backup)
    chunks = gateway.synthesize_stream(TEXT)

    assert await anext(chunks) == A
    pending = asyncio.create_task(anext(chunks, None))
    await asyncio.sleep(0.01)
    await gateway.cancel()

    assert await asyncio.wait_for(pending, 1.0) is None
    assert backup.cancelled == 1


async def test_next_sentence_after_cancel_plays_normally() -> None:
    gateway = _gateway(_Streamer("vbee"), _Streamer("eleven"))
    await gateway.cancel()
    assert await _collect(gateway) == [A, B, C]


async def test_consumer_stopping_early_closes_provider_stream_at_once() -> None:
    # CallBridge bỏ vòng lặp khi bị ngắt lời: request tới provider phải đóng ngay, không chờ GC
    primary = _Streamer("vbee")
    chunks = _gateway(primary).synthesize_stream(TEXT)
    assert await anext(chunks) == A
    await chunks.aclose()
    assert primary.closed


async def test_sync_only_provider_streams_one_block_at_its_rate() -> None:
    class SyncOnly:
        model = "sync"

        def synthesize(self, text: str) -> TTSResult:
            return TTSResult(pcm=A + B, sample_rate=24_000, voice="alloy")

    gateway = _gateway(SyncOnly())
    assert await _collect(gateway) == [A + B]
    assert (gateway.last_stream.sample_rate, gateway.last_stream.voice) == (24_000, "alloy")
