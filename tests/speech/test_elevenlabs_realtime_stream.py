"""ElevenLabs realtime: key bị từ chối thành lỗi cấu hình rõ ràng, không phải RuntimeError chung."""

import pytest

pytest.importorskip("elevenlabs", reason="cần SDK elevenlabs (extra livekit)")

from elevenlabs.realtime.connection import RealtimeEvents  # noqa: E402

from inference.asr.base import AsrAuthError  # noqa: E402
from inference.asr.config import ElevenLabsRealtimeConfig  # noqa: E402
from inference.asr.providers import elevenlabs_realtime  # noqa: E402

_LOUD = b"\x10\x27" * 240  # 30 ms ở 8 kHz, đủ to để bộ phân loại năng lượng gọi là tiếng nói


class _Connection:
    """Server trả auth_error ngay khi nhận audio đầu tiên."""

    def __init__(self) -> None:
        self.handlers: dict = {}

    def on(self, event, handler) -> None:
        self.handlers[event] = handler

    async def send(self, _message) -> None:
        self.handlers[RealtimeEvents.ERROR](
            {
                "message_type": "auth_error",
                "error": "You must be authenticated to use this endpoint.",
            }
        )

    async def commit(self) -> None:
        pass

    async def close(self) -> None:
        pass


class _Client:
    def __init__(self, api_key: str) -> None:
        connection = _Connection()

        class _Realtime:
            async def connect(self, _options):
                return connection

        self.speech_to_text = type("Stt", (), {"realtime": _Realtime()})()


async def test_rejected_key_raises_auth_error_naming_the_env_var(monkeypatch) -> None:
    monkeypatch.setattr("elevenlabs.client.AsyncElevenLabs", _Client)
    asr = elevenlabs_realtime.ElevenLabsRealtimeASR(
        ElevenLabsRealtimeConfig(_env_file=None, api_key="sk_invalid")
    )

    async def frames():
        for _ in range(5):
            yield _LOUD

    with pytest.raises(AsrAuthError, match="ELEVENLABS_API_KEY") as caught:
        async for _event in asr.stream(frames(), audio_sample_rate=8_000):
            pass

    assert "sk_invalid" not in str(caught.value)
