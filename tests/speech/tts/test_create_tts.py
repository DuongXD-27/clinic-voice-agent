"""create_tts theo TTS_PROVIDER (AC-4): none giữ như cũ; elevenlabs fail-fast khi thiếu cấu hình."""

import pytest

from callbot.speech.settings import SpeechSettings
from callbot.speech.tts import NullTTS, create_tts
from callbot.speech.tts.elevenlabs import ElevenLabsTTS


def _settings(**overrides) -> SpeechSettings:
    # _env_file=None: không đọc .env của máy dev để test quyết định theo giá trị truyền vào
    return SpeechSettings(_env_file=None, **overrides)


def test_default_provider_is_none() -> None:
    tts = create_tts(_settings())
    assert isinstance(tts, NullTTS)
    assert tts.synthesize("x") is None


def test_elevenlabs_builds_provider_from_settings() -> None:
    tts = create_tts(
        _settings(
            tts_provider="elevenlabs",
            elevenlabs_api_key="sk_x",
            elevenlabs_voice_id="v1",
            elevenlabs_model="eleven_flash_v2_5",
            elevenlabs_output_format="pcm_8000",
            elevenlabs_language_code="vi",
        )
    )
    assert isinstance(tts, ElevenLabsTTS)
    assert tts.name == "elevenlabs"
    assert tts.sample_rate == 8000
    assert "/v1/text-to-speech/v1/stream-input" in tts.endpoint()
    assert "language_code=vi" in tts.endpoint()


def test_elevenlabs_empty_language_code_means_autodetect() -> None:
    tts = create_tts(
        _settings(
            tts_provider="elevenlabs",
            elevenlabs_api_key="sk_x",
            elevenlabs_voice_id="v1",
            elevenlabs_language_code="",
        )
    )
    assert "language_code" not in tts.endpoint()


@pytest.mark.parametrize(
    "overrides, missing",
    [
        ({"elevenlabs_voice_id": "v1"}, "ELEVENLABS_API_KEY"),
        ({"elevenlabs_api_key": "sk_x"}, "ELEVENLABS_VOICE_ID"),
    ],
)
def test_elevenlabs_missing_config_names_the_variable(overrides: dict, missing: str) -> None:
    with pytest.raises(ValueError, match=missing):
        create_tts(_settings(tts_provider="elevenlabs", **overrides))


def test_unknown_provider_rejected_by_settings() -> None:
    with pytest.raises(ValueError):
        _settings(tts_provider="azure")
