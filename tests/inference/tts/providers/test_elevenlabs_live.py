"""Test tích hợp ElevenLabs thật — tốn quota, cần mạng. Chỉ chạy khi `ELEVENLABS_LIVE=1`.

ELEVENLABS_LIVE=1 python -m pytest tests/inference/tts/providers/test_elevenlabs_live.py -q -s
"""

import os

import pytest

from inference.tts.config import ElevenLabsTTSConfig
from inference.tts.providers.elevenlabs import ElevenLabsTTS

pytestmark = pytest.mark.skipif(
    os.getenv("ELEVENLABS_LIVE") != "1", reason="đặt ELEVENLABS_LIVE=1 để gọi ElevenLabs thật"
)


@pytest.fixture
def live_tts() -> ElevenLabsTTS:
    config = ElevenLabsTTSConfig()
    if not config.api_key.get_secret_value() or not config.voice_id:
        pytest.skip("thiếu ELEVENLABS_API_KEY / ELEVENLABS_VOICE_ID trong .env")
    return ElevenLabsTTS(config)


def test_live_greeting_is_8khz_and_streamed(live_tts: ElevenLabsTTS) -> None:
    result, timing = live_tts.synthesize_timed("Dạ em xin chào anh chị.")

    assert result.sample_rate == 8000
    duration_ms = len(result.pcm) / 2 / result.sample_rate * 1000
    # Câu ~6 âm tiết phải dài hơn 0,5 s; quá 5 s là có gì sai (đọc lặp / im lặng dài)
    assert 500 < duration_ms < 5000, duration_ms
    assert timing.chunks >= 1 and timing.ttfa_ms is not None
    assert timing.ttfa_ms <= timing.total_ms <= int(live_tts._timeout_s * 1000)
    print("\nlive timing:", timing.to_trace())
