from fastapi import APIRouter

from callbot.transports.http.schemas import (
    StartCallRequest,
    StartCallResponse,
    TurnRequest,
    TurnResponse,
)
# TODO(Bước 1, docs/core-logic-plan.md): thay stub bằng CallOrchestrator
from callbot.transports.http.stub_handlers import handle_call_start, handle_turn

router = APIRouter(prefix="/v1/calls", tags=["calls"])


@router.post("", response_model=StartCallResponse)
def start_call(payload: StartCallRequest) -> StartCallResponse:
    return handle_call_start(payload)


@router.post("/{call_id}/turn", response_model=TurnResponse)
def call_turn(call_id: str, payload: TurnRequest) -> TurnResponse:
    return handle_turn(call_id, payload)
