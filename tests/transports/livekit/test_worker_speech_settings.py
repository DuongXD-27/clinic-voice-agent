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
