"""7/7 flow qua HTTP, cùng transcript và Core thật; provider giả chỉ điều khiển input/output."""

import io
import wave
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from tests.transports.http.fakes import make_speech_bundle
from tests.transports.http.test_calls import _call_mode_factory, _start, _turn

from callbot.engine import EngineSettings
from callbot.engine.extraction.schema import VN_TZ
from callbot.transports.http.main import create_app
from clinic_mock_sim import FakeClinicAPI

SCENARIOS = [
    ("identity", {}, ["Nguyễn Văn A", "14/03/1978"], None),
    ("confirm", {}, ["Nguyễn Văn A", "14/03/1978", "Có, tôi đến được"], "CONFIRMED"),
    (
        "cancel",
        {},
        ["Nguyễn Văn A", "14/03/1978", "Tôi muốn hủy lịch vì bận", "Hủy giúp tôi"],
        "CANCELLED",
    ),
    ("transfer", {}, ["Tôi nên uống thuốc gì"], "TRANSFERRED"),
    (
        "reschedule",
        {},
        ["Nguyễn Văn A", "14/03/1978", "Cho tôi đổi lịch", "10 giờ sáng", "Được"],
        "RESCHEDULED",
    ),
    ("no_answer", {}, [None, None, None], "UNREACHABLE"),
    (
        "book",
        {"direction": "inbound", "appointment_id": None, "caller_number": "0912345600"},
        ["Nguyễn Văn A", "14/03/1978", "Tôi muốn đặt lịch khám", "khung 1", "Đồng ý"],
        "BOOKED",
    ),
    ("voicemail", {}, ["Quý khách vui lòng để lại lời nhắn sau tiếng bíp"], "UNREACHABLE"),
    (
        "inbound_silence",
        {"direction": "inbound", "appointment_id": None, "caller_number": "0912345600"},
        [None, None, None],
        "TRANSFERRED",
    ),
    ("wrong_identity", {}, ["Nguyễn Văn B", "14/03/1978"], "TRANSFERRED"),
    ("not_understood", {}, ["xyz", "xyz"], "TRANSFERRED"),
    ("spoken_busy", {}, ["đường dây bận", "không có người trả lời"], None),
]


def _records(clinic):
    fields = {
        "status",
        "version",
        "attempt_count",
        "cancel_reason",
        "unreachable_reason",
        "new_slot_id",
        "slot_id",
        "starts_at",
        "confirmed_via",
        "transfer_reason",
    }
    return {
        appointment_id: {key: value for key, value in record.items() if key in fields}
        for appointment_id, record in clinic.appointments.items()
    }


@pytest.mark.parametrize(
    "scenario,start,lines,outcome", SCENARIOS, ids=[row[0] for row in SCENARIOS]
)
def test_audio_and_text_share_state_actions_and_clinic_records(
    tmp_path, redis_store_factory, redis_server, scenario, start, lines, outcome
):
    results = []
    for mode in ("text", "audio"):
        clinic = FakeClinicAPI()
        speech = make_speech_bundle(tmp_path / mode, base_url="http://testserver")
        app = create_app(
            clinic_factory=lambda clinic=clinic: clinic,
            engine_settings=EngineSettings(semantic_fallback_enabled=False),
            session_store_factory=redis_store_factory,
            speech_factory=lambda speech=speech: speech,
            call_mode_factory=_call_mode_factory(redis_server),
        )
        with TestClient(app) as client:
            bot = app.state.orchestrator
            bot.sessions._clock = lambda: datetime(2026, 9, 29, 10, tzinfo=VN_TZ)
            call_id = f"c_parity_{scenario}_{mode}"
            opening = _start(client, call_id, mode=mode, **start)
            assert opening.status_code == 200
            bodies = [opening.json()]
            snapshots = []
            for turn, text in enumerate(lines, start=1):
                speech.asr.transcript = text or ""
                response = _turn(
                    client,
                    call_id,
                    turn,
                    text if mode == "text" else None,
                    silence_ms=2000 if text is None else 0,
                    audio_url=f"https://clip/{turn}"
                    if mode == "audio" and text is not None
                    else None,
                )
                assert response.status_code == 200, response.text
                bodies.append(response.json())
                session = app.state.session_store.get_session(call_id)
                ctx = session.context
                snapshots.append(
                    {
                        key: ctx.get(key)
                        for key in (
                            "state",
                            "turn",
                            "identity_verified",
                            "silent_turns",
                            "failed_understandings",
                            "selected_slot_id",
                            "pending_action",
                            "presented_slot_ids",
                        )
                    }
                )
                if mode == "audio":
                    audio = client.get(response.json()["audio_url"])
                    assert audio.status_code == 200
                    with wave.open(io.BytesIO(audio.content)) as wav:
                        assert wav.getnframes() > 0 and wav.getframerate() == 8000
            assert bodies[-1]["outcome"] == outcome
            assert bodies[-1]["ended"] == (outcome is not None)
            if mode == "audio":
                assert speech.tts.spoken == [body["utterance"] for body in bodies]
                assert client.get(bodies[0]["audio_url"]).status_code == 200
            else:
                assert speech.tts.spoken == []
            if scenario == "inbound_silence":
                assert clinic.writes == []
            if scenario == "book":
                assert (
                    len(
                        [
                            record
                            for record in clinic.appointments.values()
                            if record["status"] == "BOOKED"
                        ]
                    )
                    == 1
                )
            results.append(
                {
                    "bodies": [
                        {
                            key: value
                            for key, value in body.items()
                            if key not in ("call_id", "audio_url")
                        }
                        for body in bodies
                    ],
                    "snapshots": snapshots,
                    "writes": clinic.writes,
                    "records": _records(clinic),
                    "api": [
                        (call.operation, call.method, call.path, call.status, call.code)
                        for call in clinic.calls
                    ],
                }
            )
    assert results[0] == results[1]


def test_output_guard_replacement_is_the_only_utterance_sent_to_tts(client, clinic, monkeypatch):
    from dataclasses import replace

    from callbot.engine.types import BotAction

    _start(client, "c_guard_tts", mode="audio")
    bot = client.app.state.orchestrator
    respond = bot._dialogue.respond
    forbidden = "Lịch khám ngày 14 tháng 10 lúc 9 giờ"

    def leaked(ctx, extraction, now):
        reply = respond(ctx, extraction, now)
        return replace(reply, action=BotAction(forbidden, reply.action.state))

    monkeypatch.setattr(bot._dialogue, "respond", leaked)
    speech = client.app.state.speech
    speech.asr.transcript = "Nguyễn Văn A"
    response = _turn(client, "c_guard_tts", 1, None, audio_url="https://clip/1")
    assert response.status_code == 200
    assert response.json()["utterance"] != forbidden
    assert speech.tts.spoken[-1] == response.json()["utterance"]
    assert forbidden not in speech.tts.spoken
    assert response.json()["outcome"] == "TRANSFERRED"
