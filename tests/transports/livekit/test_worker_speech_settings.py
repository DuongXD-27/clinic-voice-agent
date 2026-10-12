"""Worker chọn cấu hình speech theo loại người gọi: SIP (điện thoại) áp `phone_overrides`."""

import pytest
from livekit import rtc

from callbot.transports.livekit.settings import LiveKitSettings
from callbot.transports.livekit.worker import speech_settings_for
from inference.asr.base import AsrAuthError
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


async def test_stt_test_page_runs_only_the_stt_pipeline_without_a_bot(monkeypatch) -> None:
    """`mode=stt` (trang thử STT): không mở engine/clinic, không có CallBridge nói chuyện."""
    from types import SimpleNamespace

    from callbot.transports.livekit import worker

    ran: list[object] = []
    built: list[dict] = []
    bundle = SimpleNamespace(stt_pipeline=object(), validator=None, tts=None)

    def build(*args, **kwargs):
        built.append(kwargs)
        return bundle

    class _Session:
        def __init__(self, room, pipeline, **kwargs) -> None:
            assert pipeline is bundle.stt_pipeline
            assert kwargs["caller_identity"] == "caller"
            assert "min_speech_ms" in kwargs["turn_controller_options"]

        async def run(self) -> None:
            ran.append(self)

    class _Bot:
        async def set_attributes(self, attributes):
            assert attributes == {worker.ASR_ATTRIBUTE: "zipformer"}

    class _Job:
        proc = SimpleNamespace(userdata={worker._PREWARMED_ASR: _PrewarmedZipFormer()})
        room = SimpleNamespace(local_participant=_Bot())

        async def connect(self):
            pass

        async def wait_for_participant(self):
            return SimpleNamespace(
                kind=rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD,
                identity="caller",
                attributes={worker.ASR_ATTRIBUTE: "zipformer", worker.MODE_ATTRIBUTE: "stt"},
            )

    def no_bot(*args, **kwargs):
        raise AssertionError("trang thử STT không được mở cuộc gọi với bot")

    monkeypatch.setattr(worker, "build_streaming_bundle", build)
    monkeypatch.setattr(worker, "SttSession", _Session)
    monkeypatch.setattr(worker, "CallBridge", no_bot)
    monkeypatch.setattr(worker, "build_clinic", no_bot)

    await worker.entrypoint(_Job())

    assert len(ran) == 1
    # Không dựng TTS (review PR #110): TTS cấu hình sai (vd. thiếu key của provider) không được
    # làm hỏng trang thử STT, vốn không phát gì.
    assert built[0]["with_tts"] is False


@pytest.mark.parametrize(
    ("error", "shown"),
    [
        (
            ModuleNotFoundError("No module named 'elevenlabs'", name="elevenlabs"),
            "thiếu thư viện elevenlabs",
        ),
        (
            AsrAuthError("ElevenLabs từ chối ELEVENLABS_API_KEY (auth_error)"),
            "từ chối ELEVENLABS_API_KEY",
        ),
        (RuntimeError("lỗi lạ có thể chứa lời người gọi"), "(RuntimeError)"),
    ],
)
async def test_stt_test_page_is_told_when_the_model_fails_mid_session(
    monkeypatch, error: Exception, shown: str
) -> None:
    """Provider hỏng lúc nhận dạng: trang thấy lỗi rõ, không chờ mãi. Lỗi lạ chỉ lộ tên lỗi."""
    import json
    from types import SimpleNamespace

    from callbot.transports.livekit import worker

    published: list[tuple[str, dict]] = []

    class _Session:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def run(self) -> None:
            raise error

    class _Bot:
        async def set_attributes(self, attributes):
            pass

        async def publish_data(self, payload, *, reliable, topic):
            published.append((topic, json.loads(payload)))

    class _Job:
        proc = SimpleNamespace(userdata={worker._PREWARMED_ASR: _PrewarmedZipFormer()})
        room = SimpleNamespace(local_participant=_Bot())

        async def connect(self):
            pass

        async def wait_for_participant(self):
            return SimpleNamespace(
                kind=rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD,
                identity="caller",
                attributes={worker.ASR_ATTRIBUTE: "zipformer", worker.MODE_ATTRIBUTE: "stt"},
            )

    bundle = SimpleNamespace(stt_pipeline=object(), validator=None, tts=None)
    monkeypatch.setattr(worker, "build_streaming_bundle", lambda *a, **k: bundle)
    monkeypatch.setattr(worker, "SttSession", _Session)

    with pytest.raises(type(error)):
        await worker.entrypoint(_Job())

    assert [(topic, body["code"]) for topic, body in published] == [
        ("callbot.status", "STT_FAILED")
    ]
    assert shown in published[0][1]["message"]
    assert "lời người gọi" not in published[0][1]["message"]


async def test_unavailable_asr_report_reaches_the_page_before_the_job_shuts_down(
    monkeypatch,
) -> None:
    """Review PR #110: job shutdown ngay sau khi gửi lỗi thì kết nối đóng trước khi gói tin tới
    trình duyệt (đã gặp với STT_FAILED 12/10: trang đứng ở "Đang chờ worker"). Trang tự rời phòng
    khi nhận lỗi; job chờ việc đó rồi mới dừng."""
    import asyncio
    from types import SimpleNamespace

    from callbot.transports.livekit import worker

    room = SimpleNamespace(remote_participants={"caller": object()})
    present_at_shutdown: list[int] = []

    class _Bot:
        async def publish_data(self, payload, *, reliable, topic):
            # Trình duyệt nhận lỗi rồi rời phòng một lúc sau.
            asyncio.get_running_loop().call_later(0.2, room.remote_participants.clear)

        async def set_attributes(self, attributes):
            raise AssertionError("không được báo ASR khi chưa có ASR đã chọn")

    room.local_participant = _Bot()

    class _Job:
        proc = SimpleNamespace(userdata={worker._PREWARMED_ASR: _PrewarmedZipFormer()})

        def __init__(self) -> None:
            self.room = room

        async def connect(self):
            pass

        async def wait_for_participant(self):
            return SimpleNamespace(
                kind=rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD,
                identity="caller",
                attributes={worker.ASR_ATTRIBUTE: "gemini_live"},
            )

        def shutdown(self, reason=""):
            present_at_shutdown.append(len(room.remote_participants))

    monkeypatch.setattr(worker, "create_asr_gateway", _missing_key)

    await worker.entrypoint(_Job())

    assert present_at_shutdown == [0]
