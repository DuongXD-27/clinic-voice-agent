"""Test tích hợp ElevenLabs thật — tốn quota, cần mạng. Chỉ chạy khi `ELEVENLABS_LIVE=1`.

ELEVENLABS_LIVE=1 python -m pytest tests/speech/tts/test_elevenlabs_live.py -q -s
"""

import os

import pytest

from callbot.speech.settings import SpeechSettings
from callbot.speech.tts.elevenlabs import ElevenLabsTTS

pytestmark = pytest.mark.skipif(
    os.getenv("ELEVENLABS_LIVE") != "1", reason="đặt ELEVENLABS_LIVE=1 để gọi ElevenLabs thật"
)


@pytest.fixture
def live_tts() -> ElevenLabsTTS:
    settings = SpeechSettings()
    if not settings.elevenlabs_api_key or not settings.elevenlabs_voice_id:
        pytest.skip("thiếu ELEVENLABS_API_KEY / ELEVENLABS_VOICE_ID trong .env")
    return ElevenLabsTTS(
        settings.elevenlabs_api_key,
        settings.elevenlabs_voice_id,
        settings.elevenlabs_model,
        timeout_s=settings.elevenlabs_timeout_s,
        language_code=settings.elevenlabs_language_code or None,
    )


def test_live_greeting_is_8khz_and_streamed(live_tts: ElevenLabsTTS) -> None:
    segment, timing = live_tts.synthesize_timed("Dạ em xin chào anh chị.")

    assert segment.sample_rate == 8000
    # Câu ~6 âm tiết phải dài hơn 0,5 s; quá 5 s là có gì sai (đọc lặp / im lặng dài)
    assert 500 < segment.duration_ms < 5000, segment.duration_ms
    assert timing.chunks >= 1 and timing.ttfa_ms is not None
    assert timing.ttfa_ms <= timing.total_ms <= int(live_tts._timeout_s * 1000)
    print("\nlive timing:", timing.to_trace())
