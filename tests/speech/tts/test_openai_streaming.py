import asyncio

import pytest

from inference.tts.config import OpenAITTSConfig
from inference.tts.providers.openai import OpenAITTS


class _FakeStreamResponse:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aenter__(self) -> "_FakeStreamResponse":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None

    async def iter_bytes(self):
        for chunk in self._chunks:
            await asyncio.sleep(0)  # nhường event loop, giống I/O thật
            yield chunk


class _FakeSpeechWithStreamingResponse:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.create_calls: list[dict] = []

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return _FakeStreamResponse(self._chunks)


class _FakeAudioSpeech:
    def __init__(self, chunks: list[bytes]) -> None:
        self.with_streaming_response = _FakeSpeechWithStreamingResponse(chunks)


class _FakeAudio:
    def __init__(self, chunks: list[bytes]) -> None:
        self.speech = _FakeAudioSpeech(chunks)


class _FakeAsyncClient:
    def __init__(self, chunks: list[bytes]) -> None:
        self.audio = _FakeAudio(chunks)


def _tts_with_fake_client(chunks: list[bytes]) -> tuple[OpenAITTS, _FakeAsyncClient]:
    tts = OpenAITTS(OpenAITTSConfig(api_key="test", model="tts-1", voice="alloy"))
    fake_client = _FakeAsyncClient(chunks)
    tts._async_client = fake_client
    return tts, fake_client


async def test_synthesize_stream_yields_all_chunks() -> None:
    tts, _ = _tts_with_fake_client([b"AAAA", b"BBBB", b"CCCC"])

    chunks = [c async for c in tts.synthesize_stream("xin chào")]

    assert chunks == [b"AAAA", b"BBBB", b"CCCC"]


async def test_synthesize_stream_empty_text_yields_nothing() -> None:
    tts, fake_client = _tts_with_fake_client([b"should-not-be-used"])

    chunks = [c async for c in tts.synthesize_stream("   ")]

    assert chunks == []
    assert fake_client.audio.speech.with_streaming_response.create_calls == []


async def test_cancel_stops_stream_before_remaining_chunks() -> None:
    tts, _ = _tts_with_fake_client([b"AAAA", b"BBBB", b"CCCC", b"DDDD"])

    received: list[bytes] = []
    async for chunk in tts.synthesize_stream("câu dài"):
        received.append(chunk)
        if len(received) == 2:
            await tts.cancel()

    assert received == [b"AAAA", b"BBBB"]


async def test_cancel_flag_resets_on_new_stream_call() -> None:
    """cancel() của lượt trước không được rò rỉ sang lượt synthesize_stream() kế tiếp —
    _cancelled.clear() ở đầu synthesize_stream phải reset đúng."""
    tts, _ = _tts_with_fake_client([b"AAAA"])
    await tts.cancel()  # giả lập cancel gọi thừa/sớm trước khi có stream nào chạy

    chunks = [c async for c in tts.synthesize_stream("câu tiếp theo")]

    assert chunks == [b"AAAA"]


if __name__ == "__main__":
    pytest.main([__file__])
