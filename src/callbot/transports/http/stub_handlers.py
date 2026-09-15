"""Handler giả, luôn chuyển máy — giữ nguyên hành vi cũ của app/core/state_machine.py.

Xoá khi nối endpoint vào CallOrchestrator (Bước 1 của docs/core-logic-plan.md).
"""

from callbot.transports.http.schemas import StartCallRequest, StartCallResponse, TurnRequest, TurnResponse

_calls: dict[str, dict] = {}


def handle_call_start(payload: StartCallRequest) -> StartCallResponse:
    _calls[payload.call_id] = {
        "direction": payload.direction,
        "appointment_id": payload.appointment_id,
        "turn": 0,
        "state": "AWAITING_IDENTITY",
    }
    return StartCallResponse(
        call_id=payload.call_id,
        utterance=(
            "Xin chào, đây là tổng đài Vinmec. "
            "Cho em hỏi em đang nói chuyện với anh chị nào ạ?"
        ),
        audio_url=None,
        state="AWAITING_IDENTITY",
        turn=0,
    )


def handle_turn(call_id: str, payload: TurnRequest) -> TurnResponse:
    call = _calls.setdefault(call_id, {"turn": 0, "state": "AWAITING_IDENTITY"})
    call["turn"] = payload.turn

    return TurnResponse(
        utterance=(
            "Dạ, em xin phép chuyển máy cho nhân viên để hỗ trợ anh chị thêm ạ."
        ),
        audio_url=None,
        state="CLOSING",
        ended=True,
        outcome="TRANSFERRED",
    )
