"""Worker chọn cấu hình speech theo loại người gọi: SIP (điện thoại) áp `phone_overrides`."""

import pytest
from livekit import rtc

from callbot.transports.livekit.settings import LiveKitSettings
from callbot.transports.livekit.worker import speech_settings_for
from speech.settings import SpeechSettings


def test_sip_caller_gets_phone_overrides() -> None:
    phone = speech_settings_for(rtc.ParticipantKind.PARTICIPANT_KIND_SIP, LiveKitSettings())

    assert phone.asr_pre_speech_ms == SpeechSettings().phone_overrides["asr_pre_speech_ms"]


def test_web_caller_keeps_default_settings() -> None:
    web = speech_settings_for(rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD, LiveKitSettings())

    assert web.asr_pre_speech_ms == SpeechSettings().asr_pre_speech_ms


def test_phone_overrides_reject_unknown_keys() -> None:
    with pytest.raises(ValueError):
        SpeechSettings(phone_overrides={"asr_pre_speach_ms": 1000})


def test_asr_chosen_on_the_test_page_wins_over_worker_config() -> None:
    worker_default = LiveKitSettings(asr_provider="zipformer")

    chosen = speech_settings_for(
        rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD, worker_default, "gemini_live"
    )
    unknown = speech_settings_for(
        rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD, worker_default, "whisper"
    )

    assert chosen.asr_provider == "gemini_live"
    assert unknown.asr_provider == "zipformer"


async def test_call_reuses_prewarmed_asr_or_falls_back_when_the_choice_fails(monkeypatch) -> None:
    from callbot.transports.livekit import worker

    class _Prewarmed:
        name = "zipformer"

    prewarmed = _Prewarmed()

    def missing_key(provider):
        raise ValueError("ASR_PROVIDER=gemini_live cần GEMINI_API_KEY")

    monkeypatch.setattr(worker, "create_asr_gateway", missing_key)

    assert await worker._recognizer_for("zipformer", prewarmed) is prewarmed
    assert await worker._recognizer_for("gemini_live", prewarmed) is None
