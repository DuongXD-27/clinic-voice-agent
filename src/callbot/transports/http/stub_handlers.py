"""Handler giả, luôn chuyển máy — giữ nguyên hành vi cũ của app/core/state_machine.py.

Xoá khi nối endpoint vào CallOrchestrator (Bước 1 của docs/core-logic-plan.md).
"""

from callbot.engine.dialogue import templates as t
from callbot.transports.http.schemas import (
    StartCallRequest,
    StartCallResponse,
    TurnRequest,
    TurnResponse,
)

_calls: dict[str, dict] = {}

# A valid empty 8 kHz mono PCM WAV. The HTTP handler is still a contract stub;
# the real transport replaces this with the configured TTS artifact.
_STUB_AUDIO_URL = (
    "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA="
)


def handle_call_start(payload: StartCallRequest) -> StartCallResponse:
    _calls[payload.call_id] = {
        "direction": payload.direction,
        "appointment_id": payload.appointment_id,
        "mode": payload.mode,
        "turn": 0,
        "state": "AWAITING_IDENTITY",
    }
    return StartCallResponse(
        call_id=payload.call_id,
        utterance=t.greeting(payload.direction),
        audio_url=_STUB_AUDIO_URL if payload.mode == "audio" else None,
        state="AWAITING_IDENTITY",
        turn=0,
    )


def handle_turn(call_id: str, payload: TurnRequest) -> TurnResponse:
    call = _calls.setdefault(call_id, {"turn": 0, "state": "AWAITING_IDENTITY"})
    call["turn"] = payload.turn

    return TurnResponse(
        utterance=t.TRANSFER,
        audio_url=_STUB_AUDIO_URL if call.get("mode") == "audio" else None,
        state="CLOSING",
        ended=True,
        outcome="TRANSFERRED",
    )
