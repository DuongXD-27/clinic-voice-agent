"""Bridge thật + Core thật dùng cùng FSM/Policy với text, không cần server LiveKit/provider."""

import asyncio
from datetime import datetime

import pytest
from tests.transports.livekit_support import require_livekit

require_livekit()

from tests.transports.http.test_audio_parity import SCENARIOS, _records  # noqa: E402
from tests.transports.livekit.bridge_factory import make_call_bridge  # noqa: E402
from tests.transports.livekit.test_call_bridge_mapping import (  # noqa: E402
    _FakeAudioSource,
    _FakeRoom,
    _FakeSTTPipeline,
    _FakeTTS,
)

from callbot.engine import CallerInput, CallStart, EngineSettings, create_orchestrator  # noqa: E402
from callbot.engine.extraction.schema import VN_TZ  # noqa: E402
from clinic_mock_sim import FakeClinicAPI  # noqa: E402
from speech.turn.events import UserTurnCompleted  # noqa: E402


@pytest.mark.parametrize(
    "scenario,start,lines,outcome", SCENARIOS[:7], ids=[row[0] for row in SCENARIOS[:7]]
)
async def test_bridge_and_text_share_core_actions_and_clinic_state(
    redis_store_factory, scenario, start, lines, outcome
):
    baseline_clinic, voice_clinic = FakeClinicAPI(), FakeClinicAPI()
    bots = [
        create_orchestrator(
            clinic, EngineSettings(semantic_fallback_enabled=False), store=redis_store_factory()
        )
        for clinic in (baseline_clinic, voice_clinic)
    ]
    for bot in bots:
        bot.sessions._clock = lambda: datetime(2026, 9, 29, 10, tzinfo=VN_TZ)
    call_id = f"c_bridge_{scenario}"
    config = {"direction": "outbound", "appointment_id": "apt_00417", **start}
    baseline_id = f"{call_id}_text"
    baseline = [bots[0].start_call(CallStart(call_id=baseline_id, **config))]
    for turn, text in enumerate(lines, 1):
        baseline.append(
            bots[0].handle_turn(
                baseline_id, CallerInput(turn, text=text, silence_ms=2000 if text is None else 0)
            )
        )
    room, tts = _FakeRoom(call_id), _FakeTTS()
    pipeline = _FakeSTTPipeline(
        [
            UserTurnCompleted(text=text or "", silence_ms=2000 if text is None else 0)
            for text in lines
        ]
    )
    bridge = make_call_bridge(room, bots[1], pipeline, tts, **config)
    source = _FakeAudioSource()

    async def publish():
        bridge._audio_source = source

    bridge._publish_tts_track = publish
    await asyncio.wait_for(bridge.run(), timeout=5)
    utterances = [action.utterance for action in baseline]
    assert tts.spoken == utterances
    payloads = [payload for payload, _, _ in room.local_participant.data]
    bot_lines = [payload for payload in payloads if payload.get("role") == "bot"]
    assert [payload["text"] for payload in bot_lines] == utterances
    assert [(payload["state"], payload["ended"], payload["outcome"]) for payload in bot_lines] == [
        (action.state, action.ended, action.outcome) for action in baseline
    ]
    assert voice_clinic.writes == baseline_clinic.writes
    assert _records(voice_clinic) == _records(baseline_clinic)
    assert [(call.operation, call.path, call.status) for call in voice_clinic.calls] == [
        (call.operation, call.path, call.status) for call in baseline_clinic.calls
    ]
    assert source.closed


async def test_inbound_sip_context_books_three_calls_in_shared_clinic(redis_store_factory):
    """Repeated bridge/core booking without resetting clinic; audio remains simulated."""
    from types import SimpleNamespace

    from livekit import rtc

    from callbot.transports.livekit.participant import participant_call

    clinic = FakeClinicAPI.mentor_mock()
    bot = create_orchestrator(
        clinic, EngineSettings(semantic_fallback_enabled=False), store=redis_store_factory()
    )
    bot.sessions._clock = lambda: datetime(2026, 10, 7, 10, tzinfo=VN_TZ)
    caller = SimpleNamespace(
        kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
        attributes={"sip.phoneNumber": "+84912345600"},
    )
    context = participant_call(caller)
    lines = ["Nguyễn Văn A", "14/03/1978", "Tôi muốn đặt lịch", "khung 1", "Đồng ý"]
    created = set()
    for index in range(3):
        before_ids = set(clinic.appointments)
        before_calls = len(clinic.calls)
        room, tts = _FakeRoom(f"sip-booking-{index}"), _FakeTTS()
        pipeline = _FakeSTTPipeline([UserTurnCompleted(text=line) for line in lines])
        bridge = make_call_bridge(
            room,
            bot,
            pipeline,
            tts,
            direction=context.direction,
            caller_number=context.caller_number,
            appointment_id=context.appointment_id,
        )
        source = _FakeAudioSource()

        async def publish(bridge=bridge, source=source):
            bridge._audio_source = source

        bridge._publish_tts_track = publish
        await asyncio.wait_for(bridge.run(), timeout=5)
        new_ids = set(clinic.appointments) - before_ids
        assert len(new_ids) == 1
        created.update(new_ids)
        assert all(clinic.appointments[i]["status"] == "BOOKED" for i in new_ids)
        calls = clinic.calls[before_calls:]
        assert sum(c.operation == "create_appointment" for c in calls) == 1
        assert any(c.operation == "get_slots" for c in calls)
        assert clinic.patient_lookups[-1] == "0912345600"
        closing = room.local_participant.data[-1][0]
        assert closing["outcome"] == "BOOKED" and closing["ended"]
        assert source.closed and len(tts.spoken) == 6
    assert len(created) == 3
