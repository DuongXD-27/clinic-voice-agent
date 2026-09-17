"""Đổi request/response HTTP sang kiểu của engine — không chứa logic hội thoại (§1.3.2)."""

import logging
from collections.abc import Callable
from typing import Annotated, TypeVar

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from callbot.engine import CallerInput, CallOrchestrator, CallStart, SessionNotFound
from callbot.transports.http.schemas import (
    StartCallRequest,
    StartCallResponse,
    TurnRequest,
    TurnResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/calls", tags=["calls"])

T = TypeVar("T")


def get_orchestrator(request: Request) -> CallOrchestrator:
    """Orchestrator tạo một lần trong lifespan (main.py) — session sống qua các lượt."""
    return request.app.state.orchestrator


Orchestrator = Annotated[CallOrchestrator, Depends(get_orchestrator)]


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _run_engine(call_id: str, operation: Callable[[], T]) -> T:
    # Không trả chi tiết exception cho client: có thể chứa URL/header của clinic mock
    try:
        return operation()
    except SessionNotFound as exc:
        raise _error(404, "CALL_NOT_FOUND", f"Không tìm thấy cuộc gọi {call_id}") from exc
    except httpx.TimeoutException as exc:
        logger.warning("Clinic mock timeout khi xử lý %s", call_id)
        raise _error(504, "UPSTREAM_TIMEOUT", "Clinic API không phản hồi kịp") from exc
    except httpx.HTTPError as exc:
        logger.warning("Clinic mock lỗi khi xử lý %s: %s", call_id, type(exc).__name__)
        raise _error(502, "UPSTREAM_ERROR", "Clinic API trả lỗi") from exc
    except Exception as exc:
        logger.exception("Lỗi ngoài dự kiến khi xử lý %s", call_id)
        raise _error(500, "INTERNAL_ERROR", "Lỗi hệ thống") from exc


@router.post("", response_model=StartCallResponse)
def start_call(
    payload: StartCallRequest,
    orchestrator: Orchestrator,
) -> StartCallResponse:
    if payload.mode == "audio":
        # Chặn trước khi mở session: chưa có STT/TTS nối vào đường HTTP
        raise _error(501, "AUDIO_NOT_IMPLEMENTED", "mode=audio chưa được hỗ trợ")

    call = CallStart(
        call_id=payload.call_id,
        direction=payload.direction,
        appointment_id=payload.appointment_id,
        caller_number=payload.caller_number,
        locale=payload.locale,
        max_turns=payload.max_turns,
    )
    action = _run_engine(payload.call_id, lambda: orchestrator.start_call(call))
    return StartCallResponse(
        call_id=payload.call_id,
        utterance=action.utterance,
        audio_url=None,
        state=action.state,
        turn=0,
    )


@router.post("/{call_id}/turn", response_model=TurnResponse)
def call_turn(
    call_id: str,
    payload: TurnRequest,
    orchestrator: Orchestrator,
) -> TurnResponse:
    # Session audio không mở được (501 ở trên) nên mọi cuộc gọi đang có đều là text mode
    if payload.audio_url is not None:
        raise _error(422, "AUDIO_URL_NOT_ALLOWED", "Cuộc gọi text mode không nhận audio_url")

    is_silence = payload.silence_ms > 0
    caller = CallerInput(
        turn=payload.turn,
        text="" if is_silence else (payload.text or ""),
        is_silence=is_silence,
    )
    action = _run_engine(call_id, lambda: orchestrator.handle_turn(call_id, caller))
    return TurnResponse(
        utterance=action.utterance,
        audio_url=None,
        state=action.state,
        ended=action.ended,
        outcome=action.outcome,
    )
