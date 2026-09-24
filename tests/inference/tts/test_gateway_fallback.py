"""TTSGateway fallback: provider chính lỗi thì dùng dự phòng đúng một lần, không log text."""

import logging

import pytest

from inference.tts import TTSGateway, TTSResult, create_tts_gateway
from inference.tts.config import VbeeTTSConfig
from inference.tts.errors import TTSUnavailable
from speech.settings import SpeechSettings

TEXT = "Dạ lịch hẹn của anh Nguyễn Văn A"


class _Provider:
    def __init__(self, model: str, error: Exception | None = None) -> None:
        self.model = model
        self._error = error
        self.spoken: list[str] = []

    def synthesize(self, text: str) -> TTSResult:
        self.spoken.append(text)
        if self._error is not None:
            raise self._error
        return TTSResult(pcm=self.model.encode(), sample_rate=8000)


def _gateway(primary: _Provider, backup: _Provider) -> TTSGateway:
    return TTSGateway(
        primary,
        provider_name="vbee",
        fallback=TTSGateway(backup, provider_name="elevenlabs"),
    )


def test_primary_success_does_not_touch_fallback() -> None:
    primary, backup = _Provider("vbee"), _Provider("eleven")

    assert _gateway(primary, backup).synthesize(TEXT).pcm == b"vbee"
    assert backup.spoken == []


def test_primary_error_falls_back_once_and_logs_code_not_text(caplog) -> None:
    primary = _Provider("vbee", TTSUnavailable("Vbee trả 503", code="http_503"))
    backup = _Provider("eleven")

    with caplog.at_level(logging.WARNING, logger="inference.tts.gateway"):
        result = _gateway(primary, backup).synthesize(f"  {TEXT} ")

    assert result.pcm == b"eleven"
    assert primary.spoken == backup.spoken == [TEXT]
    assert "http_503" in caplog.text and "elevenlabs" in caplog.text
    assert "Nguyễn" not in caplog.text


def test_unexpected_exception_also_falls_back() -> None:
    backup = _Provider("eleven")
    assert (
        _gateway(_Provider("vbee", RuntimeError("bug")), backup).synthesize(TEXT).pcm == b"eleven"
    )


def test_fallback_error_propagates() -> None:
    primary = _Provider("vbee", TTSUnavailable("x", code="timeout"))
    backup = _Provider("eleven", TTSUnavailable("y", code="http_401"))

    with pytest.raises(TTSUnavailable) as err:
        _gateway(primary, backup).synthesize(TEXT)
    assert err.value.code == "http_401"


def test_blank_text_calls_no_provider() -> None:
    primary, backup = _Provider("vbee"), _Provider("eleven")
    assert _gateway(primary, backup).synthesize("   ") is None
    assert primary.spoken == backup.spoken == []


def test_create_tts_gateway_builds_vbee_with_elevenlabs_fallback(monkeypatch) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk_x")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "v1")
    config = VbeeTTSConfig(api_token="t", app_id="a", _env_file=None)

    gateway = create_tts_gateway("vbee", config=config, fallback="elevenlabs")

    assert gateway.provider_name == "vbee"
    assert gateway.fallback is not None
    assert gateway.fallback.provider_name == "elevenlabs"
    assert gateway.fallback.fallback is None


def test_fallback_same_as_primary_is_ignored() -> None:
    config = VbeeTTSConfig(api_token="t", app_id="a", _env_file=None)
    assert create_tts_gateway("vbee", config=config, fallback="vbee").fallback is None


def test_missing_fallback_credentials_fail_at_build(monkeypatch) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "")
    config = VbeeTTSConfig(api_token="t", app_id="a", _env_file=None)
    with pytest.raises(ValueError, match="ELEVENLABS_API_KEY"):
        create_tts_gateway("vbee", config=config, fallback="elevenlabs")


@pytest.mark.parametrize(
    ("raw", "expected"), [("", None), ("  ", None), ("elevenlabs", "elevenlabs")]
)
def test_speech_settings_reads_fallback_provider(monkeypatch, raw: str, expected) -> None:
    monkeypatch.setenv("TTS_FALLBACK_PROVIDER", raw)
    assert SpeechSettings(_env_file=None).tts_fallback_provider == expected
