from fastapi import APIRouter

from app.core.state_machine import handle_call_start, handle_turn
from app.schemas.calls import (
    StartCallRequest,
    StartCallResponse,
    TurnRequest,
    TurnResponse,
)

router = APIRouter(prefix="/v1/calls", tags=["calls"])


@router.post("", response_model=StartCallResponse)
def start_call(payload: StartCallRequest) -> StartCallResponse:
    return handle_call_start(payload)


@router.post("/{call_id}/turn", response_model=TurnResponse)
def call_turn(call_id: str, payload: TurnRequest) -> TurnResponse:
    return handle_turn(call_id, payload)
