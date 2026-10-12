"""Trang thử STT: chữ từng lượt (tạm thời → chốt, lượt bị bỏ) đi qua data channel, đúng thứ tự."""

import asyncio
import json

import pytest

from callbot.transports.livekit.stt_session import STT_TOPIC, ObservedTurnController, SttSession
from speech.asr.vad.base import VadEvent
from speech.turn.events import UserTurnCompleted
from speech.types import TranscriptEvent


def _observed(**options):
    live: list[str] = []
    dropped: list[str] = []
    controller = ObservedTurnController(
        on_live=live.append, on_dropped=dropped.append, min_speech_ms=0, **options
    )
    return controller, live, dropped


async def test_partials_of_the_turn_being_spoken_are_reported_until_it_is_committed() -> None:
    controller, live, _ = _observed()
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="tôi muốn", is_final=False))
    await controller.on_transcript_event(TranscriptEvent(text="tôi muốn đổi lịch", is_final=False))
    await controller.on_transcript_event(TranscriptEvent(text="tôi muốn đổi lịch", is_final=True))
    turn = await asyncio.wait_for(controller.get_turn(), timeout=1.0)
    # Partial tới muộn sau khi lượt đã chốt không được mở lại dòng đang nói.
    await controller.on_transcript_event(TranscriptEvent(text="tôi muốn đổi", is_final=False))

    assert live == ["tôi muốn", "tôi muốn đổi lịch"]
    assert turn.text == "tôi muốn đổi lịch"


async def test_a_turn_the_pipeline_drops_is_reported_as_dropped() -> None:
    """ASR nghe ra "Ừ" nhưng pipeline bỏ (chỉ có từ đệm): trang vẫn thấy model nghe gì."""
    controller, _, dropped = _observed()
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="ừ", is_final=True))
    await controller.on_vad_event(VadEvent("speech_end"))
    await controller.on_vad_event(VadEvent("speech_start"))

    assert dropped == ["ừ"]


class _Participant:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def publish_data(self, payload: str, *, reliable: bool, topic: str) -> None:
        assert reliable and topic == STT_TOPIC
        self.sent.append(json.loads(payload))


class _Room:
    name = "web-stt-1"

    def __init__(self) -> None:
        self.local_participant = _Participant()
        self.remote_participants: dict = {}
        self.handlers: dict = {}

    def on(self, event: str, handler) -> None:
        self.handlers[event] = handler


class _Pipeline:
    """Một lượt: hai partial rồi chốt, rồi room ngắt."""

    def __init__(self, room: _Room) -> None:
        self._room = room

    async def stream(self, frames, turn_controller, **_kwargs):
        await turn_controller.on_vad_event(VadEvent("speech_start"))
        await turn_controller.on_transcript_event(TranscriptEvent(text="xin", is_final=False))
        await turn_controller.on_transcript_event(TranscriptEvent(text="xin chào", is_final=False))
        yield UserTurnCompleted(
            text="xin chào", confidence=0.9, first_partial_ms=300.0, final_ms=900.0
        )
        self._room.handlers["disconnected"]()
        async for _frame in frames:
            pass


async def test_session_sends_partials_then_the_committed_turn_and_ends_with_the_room() -> None:
    room = _Room()
    session = SttSession(
        room,  # type: ignore[arg-type]
        _Pipeline(room),  # type: ignore[arg-type]
        turn_controller_options={"min_speech_ms": 0},
        sample_rate=16_000,
        frame_ms=30,
        input_queue_ms=600,
    )

    await asyncio.wait_for(session.run(), timeout=2.0)

    assert [(m["kind"], m["turn"], m["text"]) for m in room.local_participant.sent] == [
        ("partial", 1, "xin"),
        ("partial", 1, "xin chào"),
        ("final", 1, "xin chào"),
    ]
    final = room.local_participant.sent[-1]
    assert final["confidence"] == 0.9 and final["final_ms"] == 900.0


class _GatingPipeline:
    """Lượt 1 (tiếng TV) bị cổng giọng chặn; trong lúc cổng còn chấm, người gọi đã nói lượt 2."""

    def __init__(self, room: _Room) -> None:
        self._room = room

    async def stream(self, frames, turn_controller, on_turn_blocked=None):
        controller = turn_controller
        await controller.on_vad_event(VadEvent("speech_start"))
        await controller.on_transcript_event(TranscriptEvent(text="tivi nói", is_final=False))
        await controller.on_transcript_event(TranscriptEvent(text="tivi nói", is_final=True))
        blocked = await asyncio.wait_for(controller.get_turn(), timeout=1.0)
        await controller.on_vad_event(VadEvent("speech_start"))
        await controller.on_transcript_event(TranscriptEvent(text="tôi muốn", is_final=False))
        if on_turn_blocked is not None:
            on_turn_blocked(blocked)
        await controller.on_transcript_event(
            TranscriptEvent(text="tôi muốn đặt lịch", is_final=True)
        )
        yield await asyncio.wait_for(controller.get_turn(), timeout=1.0)
        self._room.handlers["disconnected"]()
        async for _frame in frames:
            pass


async def test_turn_blocked_by_the_speaker_gate_is_shown_and_keeps_its_own_number() -> None:
    """Review PR #110: cổng giọng (enforce, mặc định) bỏ lượt mà không có `final`; partial của
    lượt sau mang cùng số và đè lên dòng của lượt bị chặn."""
    room = _Room()
    session = SttSession(
        room,  # type: ignore[arg-type]
        _GatingPipeline(room),  # type: ignore[arg-type]
        turn_controller_options={"min_speech_ms": 0},
        sample_rate=16_000,
        frame_ms=30,
        input_queue_ms=600,
    )

    await asyncio.wait_for(session.run(), timeout=2.0)

    assert [(m["kind"], m["turn"], m["text"]) for m in room.local_participant.sent] == [
        ("partial", 1, "tivi nói"),
        ("partial", 2, "tôi muốn"),
        ("dropped", 1, "tivi nói"),
        ("final", 2, "tôi muốn đặt lịch"),
    ]


async def test_stt_page_uses_the_call_audio_path_including_krisp(monkeypatch) -> None:
    """Review PR #110: trang thử STT chép phần nhận mic của CallBridge nhưng thiếu Krisp và audio
    dump — bật Krisp thì trang không còn chạy đúng pipeline cuộc gọi. Giờ dùng chung
    `caller_audio.pump_caller_track`."""
    from types import SimpleNamespace

    rtc = pytest.importorskip("livekit.rtc")
    from callbot.transports.livekit import stt_session

    pumped: list[dict] = []

    async def fake_pump(track, **kwargs):
        pumped.append(kwargs)

    monkeypatch.setattr(stt_session, "pump_caller_track", fake_pump)
    room = _Room()
    session = SttSession(
        room,  # type: ignore[arg-type]
        _Pipeline(room),  # type: ignore[arg-type]
        turn_controller_options={"min_speech_ms": 0},
        sample_rate=16_000,
        frame_ms=30,
        input_queue_ms=600,
        krisp_enabled=True,
    )
    mic = SimpleNamespace(kind=rtc.TrackKind.KIND_AUDIO)
    publication = SimpleNamespace(source=rtc.TrackSource.SOURCE_MICROPHONE)

    session._on_track_subscribed(mic, publication, SimpleNamespace(identity="caller"))
    await asyncio.sleep(0)

    assert pumped and pumped[0]["krisp_enabled"] is True
    assert pumped[0]["room_name"] == room.name
