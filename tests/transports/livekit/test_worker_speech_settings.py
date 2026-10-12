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


class _PrewarmedZipFormer:
    name = "zipformer"


def _missing_key(provider):
    raise ValueError("ASR_PROVIDER=gemini_live cần GEMINI_API_KEY")


async def test_call_reuses_prewarmed_asr_only_for_the_same_provider(monkeypatch) -> None:
    from callbot.transports.livekit import worker

    prewarmed = _PrewarmedZipFormer()
    monkeypatch.setattr(worker, "create_asr_gateway", _missing_key)

    assert await worker._recognizer_for("zipformer", prewarmed) is prewarmed
    assert await worker._recognizer_for("gemini_live", prewarmed) is None


async def test_chosen_asr_that_cannot_start_stops_the_call_instead_of_switching(
    monkeypatch,
) -> None:
    """Chọn Gemini mà worker không tạo được Gemini: báo lỗi lên trang gọi thử và dừng, không
    lặng lẽ chạy cuộc gọi bằng ZipFormer nạp sẵn."""
    import json
    from types import SimpleNamespace

    from callbot.transports.livekit import worker

    published: list[tuple[str, dict]] = []
    shutdowns: list[str] = []

    class _Bot:
        async def publish_data(self, payload, *, reliable, topic):
            published.append((topic, json.loads(payload)))

        async def set_attributes(self, attributes):
            raise AssertionError("không được báo ASR khi chưa có ASR đã chọn")

    class _Job:
        proc = SimpleNamespace(userdata={worker._PREWARMED_ASR: _PrewarmedZipFormer()})
        room = SimpleNamespace(local_participant=_Bot())

        async def connect(self):
            pass

        async def wait_for_participant(self):
            return SimpleNamespace(
                kind=rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD,
                identity="caller",
                attributes={worker.ASR_ATTRIBUTE: "gemini_live"},
            )

        def shutdown(self, reason=""):
            shutdowns.append(reason)

    def no_other_asr(*args, **kwargs):
        raise AssertionError("không được dựng pipeline bằng ASR khác")

    monkeypatch.setattr(worker, "create_asr_gateway", _missing_key)
    monkeypatch.setattr(worker, "build_streaming_bundle", no_other_asr)

    await worker.entrypoint(_Job())

    assert [(topic, body["code"]) for topic, body in published] == [
        ("callbot.status", "ASR_UNAVAILABLE")
    ]
    assert "gemini_live" in published[0][1]["message"]
    assert shutdowns == ["asr unavailable"]
