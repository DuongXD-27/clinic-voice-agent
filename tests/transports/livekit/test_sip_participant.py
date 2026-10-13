"""SIP boundary regressions. No server, carrier, ASR or TTS provider is invoked."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from tests.transports.livekit_support import require_livekit

require_livekit()

from livekit import rtc  # noqa: E402

from callbot.transports.livekit import participant as participant_module  # noqa: E402
from callbot.transports.livekit.participant import (  # noqa: E402
    ParticipantCall,
    hangup_sip_caller,
    participant_call,
)


def sip_participant(**attrs):
    return SimpleNamespace(
        kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP,
        identity="sip-caller",
        attributes=attrs,
    )


def test_sip_uses_originating_number_and_ignores_web_outbound_context():
    caller = sip_participant(
        **{
            "sip.phoneNumber": "+84912345600",
            "sip.trunkPhoneNumber": "+842800000000",
            "direction": "outbound",
            "appointment_id": "wrong-appointment",
            "caller_number": "wrong-caller",
        }
    )
    assert participant_call(caller) == ParticipantCall("inbound", "+84912345600", None, True)


@pytest.mark.parametrize("number", [None, ""])
def test_hidden_sip_number_never_falls_back_to_called_did_or_web_caller(number):
    caller = sip_participant(
        **{"sip.phoneNumber": number, "sip.trunkPhoneNumber": "+842800000000", "caller_number": "x"}
    )
    assert participant_call(caller).caller_number is None


def test_browser_context_still_supports_inbound_and_outbound():
    caller = SimpleNamespace(kind=rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD, attributes={})
    caller.attributes = {"caller_number": "0912345600", "sip.phoneNumber": "spoofed"}
    assert participant_call(caller) == ParticipantCall("inbound", "0912345600", None, False)
    caller.attributes = {"direction": "outbound", "appointment_id": "apt_00417"}
    assert participant_call(caller) == ParticipantCall("outbound", None, "apt_00417", False)


async def test_hangup_removes_only_caller_and_skips_already_disconnected():
    remove = AsyncMock()
    ctx = SimpleNamespace(
        room=SimpleNamespace(name="sip-booking", remote_participants={"sip-caller": object()}),
        api=SimpleNamespace(room=SimpleNamespace(remove_participant=remove)),
    )
    await hangup_sip_caller(ctx, "sip-caller")
    request = remove.call_args.args[0]
    assert (request.room, request.identity) == ("sip-booking", "sip-caller")
    ctx.room.remote_participants.clear()
    await hangup_sip_caller(ctx, "sip-caller")
    assert remove.await_count == 1


async def test_hangup_api_failure_deletes_dedicated_room():
    delete_room = AsyncMock()
    ctx = SimpleNamespace(
        room=SimpleNamespace(name="sip-booking", remote_participants={"sip-caller": object()}),
        api=SimpleNamespace(
            room=SimpleNamespace(remove_participant=AsyncMock(side_effect=ConnectionError))
        ),
        delete_room=delete_room,
    )
    await hangup_sip_caller(ctx, "sip-caller")
    delete_room.assert_awaited_once()


async def test_hangup_ignores_not_found_race(monkeypatch):
    class TwirpError(Exception):
        code = participant_module.api.TwirpErrorCode.NOT_FOUND

    monkeypatch.setattr(participant_module.api, "TwirpError", TwirpError)
    delete_room = AsyncMock()
    ctx = SimpleNamespace(
        room=SimpleNamespace(name="sip-booking", remote_participants={"sip-caller": object()}),
        api=SimpleNamespace(
            room=SimpleNamespace(remove_participant=AsyncMock(side_effect=TwirpError()))
        ),
        delete_room=delete_room,
    )
    await hangup_sip_caller(ctx, "sip-caller")
    delete_room.assert_not_awaited()


@pytest.mark.parametrize("caller_disconnects", [False, True])
async def test_sip_bye_waits_for_remote_playout_and_rechecks_caller(
    monkeypatch, caller_disconnects
):
    entered, release = asyncio.Event(), asyncio.Event()
    remove = AsyncMock()
    ctx = SimpleNamespace(
        room=SimpleNamespace(name="sip-booking", remote_participants={"sip-caller": object()}),
        api=SimpleNamespace(room=SimpleNamespace(remove_participant=remove)),
    )

    async def remote_playout_delay(seconds):
        assert seconds == 2
        entered.set()
        await release.wait()

    monkeypatch.setattr(participant_module.asyncio, "sleep", remote_playout_delay)
    closing = asyncio.create_task(hangup_sip_caller(ctx, "sip-caller", playout_grace_ms=2000))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        remove.assert_not_awaited()
        if caller_disconnects:
            ctx.room.remote_participants.clear()
        release.set()
        await asyncio.wait_for(closing, timeout=1)
        assert remove.await_count == (0 if caller_disconnects else 1)
    finally:
        release.set()
        if not closing.done():
            closing.cancel()
            await asyncio.gather(closing, return_exceptions=True)


async def test_disconnected_caller_needs_no_playout_delay(monkeypatch):
    delay = AsyncMock()
    monkeypatch.setattr(participant_module.asyncio, "sleep", delay)
    remove = AsyncMock()
    ctx = SimpleNamespace(
        room=SimpleNamespace(name="sip-booking", remote_participants={}),
        api=SimpleNamespace(room=SimpleNamespace(remove_participant=remove)),
    )
    await hangup_sip_caller(ctx, "sip-caller", playout_grace_ms=2000)
    delay.assert_not_awaited()
    remove.assert_not_awaited()


@pytest.mark.parametrize("kind", [rtc.ParticipantKind.PARTICIPANT_KIND_SIP, 0])
async def test_worker_maps_caller_and_hangs_up_after_bridge_playout(monkeypatch, kind):
    from callbot.transports.livekit import worker

    events = []
    caller = SimpleNamespace(
        kind=kind,
        identity="caller",
        attributes={"sip.phoneNumber": "+84912345600", "caller_number": "0912345600"},
    )
    ctx = SimpleNamespace(
        connect=AsyncMock(),
        wait_for_participant=AsyncMock(return_value=caller),
        proc=SimpleNamespace(userdata={}),
        room=SimpleNamespace(name="sip-booking", remote_participants={"caller": caller}),
        shutdown=lambda **kw: events.append("job_shutdown"),
    )

    async def remove(request):
        assert request.identity == "caller"
        events.append("hangup")

    ctx.api = SimpleNamespace(
        room=SimpleNamespace(remove_participant=AsyncMock(side_effect=remove))
    )
    bundle = SimpleNamespace(
        stt_pipeline=object(),
        tts=SimpleNamespace(aclose=AsyncMock()),
        turn_controller=object(),
        validator=None,
    )
    clinic = SimpleNamespace(close=lambda: events.append("clinic_closed"))
    monkeypatch.setattr(worker, "build_streaming_bundle", lambda *a, **kw: bundle)
    monkeypatch.setattr(worker, "build_clinic", lambda *a: clinic)
    monkeypatch.setattr(worker, "create_orchestrator", lambda *a, **kw: object())
    monkeypatch.setattr(worker, "create_tracer", lambda: SimpleNamespace(close=lambda *a: None))
    monkeypatch.setattr(worker, "_recognizer_for", AsyncMock(return_value=object()))

    class Bridge:
        def __init__(self, *args, **kwargs):
            assert kwargs["is_sip"] == (kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP)
            assert kwargs["caller_number"] == ("+84912345600" if kind == 3 else "0912345600")
            assert kwargs["direction"] == "inbound"
            self.on_close = kwargs["on_close"]

        async def run(self):
            events.append("final_audio_drained")
            if self.on_close:
                await self.on_close()

    monkeypatch.setattr(worker, "CallBridge", Bridge)
    await worker.entrypoint(ctx)
    assert events == (
        ["final_audio_drained", "hangup", "clinic_closed", "job_shutdown"]
        if kind == 3
        else ["final_audio_drained", "clinic_closed", "job_shutdown"]
    )
    bundle.tts.aclose.assert_awaited_once()


@pytest.mark.parametrize("kind", [rtc.ParticipantKind.PARTICIPANT_KIND_SIP, 0])
async def test_worker_without_asr_hangs_up_the_sip_caller(monkeypatch, kind):
    """ASR không tạo được thì job dừng; bot rời phòng không gửi BYE nên người gọi SIP phải được gỡ
    khỏi phòng, không bị bỏ lại trong im lặng. Trang gọi thử (web) thì chỉ báo lỗi."""
    from callbot.transports.livekit import worker

    events = []
    caller = SimpleNamespace(
        kind=kind, identity="caller", attributes={"sip.phoneNumber": "+84912345600"}
    )

    async def publish_data(*args, **kwargs):
        events.append("status")

    async def remove(request):
        assert request.identity == "caller"
        events.append("hangup")

    ctx = SimpleNamespace(
        connect=AsyncMock(),
        wait_for_participant=AsyncMock(return_value=caller),
        proc=SimpleNamespace(userdata={}),
        room=SimpleNamespace(
            name="sip-booking",
            remote_participants={"caller": caller},
            local_participant=SimpleNamespace(publish_data=publish_data),
        ),
        api=SimpleNamespace(room=SimpleNamespace(remove_participant=AsyncMock(side_effect=remove))),
        shutdown=lambda **kw: events.append("job_shutdown"),
    )
    monkeypatch.setattr(worker, "_recognizer_for", AsyncMock(return_value=None))

    await worker.entrypoint(ctx)

    assert events == (
        ["status", "hangup", "job_shutdown"] if kind == 3 else ["status", "job_shutdown"]
    )
