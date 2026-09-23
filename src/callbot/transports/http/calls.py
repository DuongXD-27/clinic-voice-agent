"""Đổi request/response HTTP sang kiểu của engine — không chứa logic hội thoại (§1.3.2)."""

import json
import logging
from collections.abc import Callable
from time import perf_counter_ns
from typing import Annotated, Any, Optional, TypeVar
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from callbot.engine import (
    CallBusy,
    CallConflict,
    CallEnded,
    CallerInput,
    CallOrchestrator,
    CallStart,
    ReconciliationRequired,
    SessionNotFound,
    SessionStoreUnavailable,
    TurnConflict,
    TurnOutOfOrder,
)
from callbot.engine.diagnostics import TurnDiagnostics, summarize_extraction
from callbot.tracing import Tracer, null_tracer
from callbot.transports.http.call_mode import CallModeStore
from callbot.transports.http.schemas import (
    ExtractionDebug,
    StartCallRequest,
    StartCallResponse,
    TurnRequest,
    TurnResponse,
)
from speech.bundle import SpeechBundle
from speech.types import Transcript

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/calls", tags=["calls"])

T = TypeVar("T")


def get_orchestrator(request: Request) -> CallOrchestrator:
    """Orchestrator tạo một lần trong lifespan (main.py); session nằm trong session store."""
    return request.app.state.orchestrator


def get_speech(request: Request) -> SpeechBundle:
    return request.app.state.speech


def get_call_mode(request: Request) -> CallModeStore:
    return request.app.state.call_mode


Orchestrator = Annotated[CallOrchestrator, Depends(get_orchestrator)]
Speech = Annotated[SpeechBundle, Depends(get_speech)]
CallMode = Annotated[CallModeStore, Depends(get_call_mode)]


def _tracer(orchestrator: object) -> Tracer:
    candidate = getattr(orchestrator, "tracer", None)
    return candidate if isinstance(candidate, Tracer) else null_tracer()


def _safe_speech_label(component: object, attribute: str) -> Optional[str]:
    try:
        value = getattr(component, attribute, None)
        return value if isinstance(value, str) and value else None
    except Exception:
        return None


def _elapsed_ms(start_ns: int) -> float:
    return max(0.0, (perf_counter_ns() - start_ns) / 1_000_000)


def _enrich_audio(span: Any, segment: Any, *, include_bytes: bool = False) -> None:
    try:
        attributes: dict[str, object] = {
            "audio_duration_ms": segment.duration_ms,
            "sample_rate_hz": segment.sample_rate,
        }
        if include_bytes:
            attributes.update(bytes=len(segment.pcm), chunks=1)
        span.enrich(**attributes)
    except Exception:
        logger.warning("TRACE_SPEECH_METADATA_REJECTED")


def _set_speech_error(span: Any, exc: BaseException, *, stage: str) -> None:
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        code = "STT_TIMEOUT" if stage.startswith("STT") else "TTS_TIMEOUT"
        span.set_error_code("TIMEOUT", code)
    elif stage == "STT_LOAD":
        span.set_error_code("UPSTREAM", "STT_DECODE_ERROR")
    elif stage == "STT_PROVIDER":
        span.set_error_code("PROVIDER", "STT_PROVIDER_ERROR")
    elif stage == "TTS_STORAGE":
        span.set_error_code("STORAGE", "TTS_STORAGE_ERROR")
    else:
        span.set_error_code("PROVIDER", "TTS_PROVIDER_ERROR")


def _transcribe(tracer: Tracer, speech: SpeechBundle, audio_url: str) -> Transcript:
    with tracer.span(component="STT", operation="speech.stt.transcribe") as span:
        span.enrich(
            provider=_safe_speech_label(speech.asr, "name"),
            model=_safe_speech_label(speech.asr, "model"),
            streaming=False,
        )
        try:
            segment = speech.audio_loader(audio_url)
        except Exception as exc:
            _set_speech_error(span, exc, stage="STT_LOAD")
            raise
        _enrich_audio(span, segment)
        started = perf_counter_ns()
        try:
            transcript = speech.asr.transcribe(segment)
        except Exception as exc:
            span.enrich(latency_ms=_elapsed_ms(started))
            _set_speech_error(span, exc, stage="STT_PROVIDER")
            raise
        span.enrich(
            latency_ms=_elapsed_ms(started),
            silence_detected=transcript.is_silence,
            transcript_empty=not bool(transcript.text.strip()),
        )
        return transcript


def _error(status_code: int, code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"code": code, "message": message, **extra}
    )


def _run_engine(call_id: str, operation: Callable[[], T], *, debug: bool = False) -> T:
    """`debug`: response lỗi vẫn mang header chẩn đoán (extraction đã trích trước khi lỗi)."""
    try:
        return _translate_errors(call_id, operation)
    except HTTPException as exc:
        if debug:
            cause = exc.__cause__
            diagnostics = getattr(cause, "diagnostics", None)
            if diagnostics is not None:
                headers = _debug_headers(diagnostics, getattr(cause, "extraction", None))
                exc.headers = {**(exc.headers or {}), **headers}
        raise


def _translate_errors(call_id: str, operation: Callable[[], T]) -> T:
    # Không trả chi tiết exception cho client: có thể chứa URL/header của clinic mock
    try:
        return operation()
    except SessionNotFound as exc:
        raise _error(404, "CALL_NOT_FOUND", f"Không tìm thấy cuộc gọi {call_id}") from exc
    except CallConflict as exc:
        raise _error(409, "CALL_CONFLICT", "call_id đã mở với cấu hình khác") from exc
    except TurnConflict as exc:
        raise _error(409, "TURN_CONFLICT", "Lượt này đã nhận với đầu vào khác") from exc
    except TurnOutOfOrder as exc:
        raise _error(
            409,
            "TURN_OUT_OF_ORDER",
            f"Đang chờ lượt {exc.expected_turn}",
            expected_turn=exc.expected_turn,
        ) from exc
    except CallEnded as exc:
        raise _error(409, "CALL_ENDED", "Cuộc gọi đã kết thúc") from exc
    except CallBusy as exc:
        raise _error(409, "CALL_BUSY", "Cuộc gọi đang xử lý một lượt khác") from exc
    except ReconciliationRequired as exc:
        logger.error("Phiên %s cần đối soát (lượt %s)", call_id, exc.turn)
        raise _error(
            409,
            "CALL_RECONCILIATION_REQUIRED",
            "Kết quả ghi Clinic chưa xác định, phiên bị chặn chờ đối soát",
            turn=exc.turn,
        ) from exc
    except SessionStoreUnavailable as exc:
        logger.error("Session store không sẵn sàng khi xử lý %s", call_id)
        raise _error(503, "SESSION_STORE_UNAVAILABLE", "Kho phiên không sẵn sàng") from exc
    except httpx.TimeoutException as exc:
        logger.warning("Clinic mock timeout khi xử lý %s", call_id)
        raise _error(504, "UPSTREAM_TIMEOUT", "Clinic API không phản hồi kịp") from exc
    except httpx.HTTPError as exc:
        logger.warning("Clinic mock lỗi khi xử lý %s: %s", call_id, type(exc).__name__)
        raise _error(502, "UPSTREAM_ERROR", "Clinic API trả lỗi") from exc
    except Exception as exc:
        # Chỉ ghi tên lớp exception: nội dung có thể chứa transcript hoặc phản hồi của provider
        logger.error("Lỗi ngoài dự kiến khi xử lý %s: %s", call_id, type(exc).__name__)
        raise _error(500, "INTERNAL_ERROR", "Lỗi hệ thống") from exc


@router.post("", response_model=StartCallResponse)
def start_call(
    payload: StartCallRequest,
    orchestrator: Orchestrator,
    speech: Speech,
    call_mode: CallMode,
) -> StartCallResponse:
    tracer = _tracer(orchestrator)
    with tracer.start_trace(
        call_id=payload.call_id, turn=0, component="TURN", operation="http.start_call"
    ) as span:
        span.enrich(route_template="/v1/calls", http_method="POST")
        try:
            result = _start_call_impl(payload, orchestrator, speech, call_mode)
            span.enrich(http_status=200, final_state=result.state)
            return result
        except HTTPException as exc:
            span.enrich(http_status=exc.status_code)
            span.set_error(exc.__cause__ or exc)
            raise


def _start_call_impl(
    payload: StartCallRequest,
    orchestrator: Orchestrator,
    speech: Speech,
    call_mode: CallMode,
) -> StartCallResponse:
    call = CallStart(
        call_id=payload.call_id,
        direction=payload.direction,
        appointment_id=payload.appointment_id,
        caller_number=payload.caller_number,
        locale=payload.locale,
        max_turns=payload.max_turns,
    )

    def _open() -> tuple:
        action = orchestrator.start_call(call)
        audio_url = None
        if payload.mode == "audio":
            call_mode.set_audio(payload.call_id)
            audio_url = _synthesize(
                _tracer(orchestrator), speech, payload.call_id, 0, action.utterance
            )
        return action, audio_url

    action, audio_url = _run_engine(payload.call_id, _open)
    return StartCallResponse(
        call_id=payload.call_id,
        utterance=action.utterance,
        audio_url=audio_url,
        state=action.state,
        turn=0,
    )


@router.post("/{call_id}/turn", response_model=TurnResponse, response_model_exclude_unset=True)
def call_turn(
    request: Request,
    response: Response,
    call_id: str,
    payload: TurnRequest,
    orchestrator: Orchestrator,
    speech: Speech,
    call_mode: CallMode,
) -> TurnResponse:
    tracer = _tracer(orchestrator)
    with tracer.start_trace(
        call_id=call_id, turn=payload.turn, component="TURN", operation="http.call_turn"
    ) as span:
        span.enrich(route_template="/v1/calls/{call_id}/turn", http_method="POST")
        try:
            result = _call_turn_impl(
                request, response, call_id, payload, orchestrator, speech, call_mode
            )
            span.enrich(http_status=200, final_state=result.state, outcome=result.outcome)
            return result
        except HTTPException as exc:
            span.enrich(http_status=exc.status_code)
            span.set_error(exc.__cause__ or exc)
            raise


def _call_turn_impl(
    request: Request,
    response: Response,
    call_id: str,
    payload: TurnRequest,
    orchestrator: Orchestrator,
    speech: Speech,
    call_mode: CallMode,
) -> TurnResponse:
    is_audio = call_mode.is_audio(call_id)
    if is_audio and payload.text is not None:
        raise _error(422, "TEXT_NOT_ALLOWED", "Cuộc gọi audio mode không nhận text")
    if not is_audio and payload.audio_url is not None:
        raise _error(422, "AUDIO_URL_NOT_ALLOWED", "Cuộc gọi text mode không nhận audio_url")

    def _turn() -> tuple:
        text = payload.text
        confidence = None
        if payload.audio_url is not None:
            transcript = _transcribe(_tracer(orchestrator), speech, payload.audio_url)
            text = transcript.text
            confidence = transcript.confidence
        # silence_ms giữ nguyên giá trị harness gửi (§1.1.7) — không suy diễn lại từ ASR
        caller = CallerInput(
            turn=payload.turn,
            text=text,
            silence_ms=payload.silence_ms,
            audio_url=payload.audio_url,
            asr_confidence=confidence,
        )
        run = orchestrator.handle_turn_with_details(call_id, caller)
        action = run.action
        audio_url = (
            _synthesize(_tracer(orchestrator), speech, call_id, payload.turn, action.utterance)
            if is_audio
            else None
        )
        return action, audio_url, run

    debug = request.headers.get("X-Demo-Debug") == "1"
    action, audio_url, run = _run_engine(call_id, _turn, debug=debug)
    if debug and run.diagnostics is not None:
        response.headers.update(_debug_headers(run.diagnostics, run.extraction))
    return TurnResponse(
        utterance=action.utterance,
        audio_url=audio_url,
        state=action.state,
        ended=action.ended,
        outcome=action.outcome,
    )


def _extraction_debug(extraction: Optional[dict[str, Any]]) -> ExtractionDebug:
    """Summarize the extraction path without returning transcript values or spans."""
    question_id, source, provenance = summarize_extraction(extraction)
    return ExtractionDebug(question_id=question_id, source=source, provenance=provenance)


def _debug_headers(
    diagnostics: TurnDiagnostics, extraction: Optional[dict[str, Any]] = None
) -> dict[str, str]:
    """Demo-only diagnostics, never in the JSON contract. Values are allow-listed by the engine.

    `X-Demo-Transfer-Reason` is the transfer that was requested, not proof that Clinic recorded it.
    `X-Demo-Extraction-Fields` is the one exception to the allow-list: it carries the transcript and
    the extracted values / spans so the demo can show what was read from the sentence. It is only
    sent to a client that asked for `X-Demo-Debug: 1`, never logged and never stored.
    """
    headers = {
        "X-Demo-Extraction-Source": diagnostics.extraction_source,
        "X-Demo-Extraction-Provenance": diagnostics.extraction_provenance,
    }
    optional = {
        "X-Demo-Extraction-Question-Id": diagnostics.question_id,
        "X-Demo-Transfer-Reason": diagnostics.transfer_reason,
        "X-Demo-Error-Type": diagnostics.error_type,
        "X-Demo-Error-Code": diagnostics.error_code,
    }
    headers.update({name: value for name, value in optional.items() if value is not None})
    fields = _extraction_fields(extraction)
    if fields is not None:
        headers["X-Demo-Extraction-Fields"] = fields
    return headers


def _extraction_fields(extraction: Optional[dict[str, Any]]) -> Optional[str]:
    """Transcript + fields actually extracted, as percent-encoded JSON (headers are latin-1 only)."""
    if not extraction:
        return None
    fields = [
        {
            "field": name,
            "value": field.get("value"),
            "span": field.get("span"),
            "provenance": field.get("provenance"),
        }
        for name, field in extraction.items()
        if isinstance(field, dict) and field.get("provenance") not in (None, "NONE")
    ]
    payload = {
        "transcript": extraction.get("transcript") or "",
        "silent": bool(extraction.get("silent")),
        "fields": fields,
    }
    return quote(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), safe="")


def _synthesize(
    tracer: Tracer, speech: SpeechBundle, call_id: str, turn: int, text: str
) -> Optional[str]:
    # Lượt đã ghi vào session: TTS lỗi chỉ mất audio, vẫn trả utterance (audio_url=None).
    # Trả 500 ở đây khiến client gửi lại một lượt đã được engine nhận.
    with tracer.span(component="TTS", operation="speech.tts.synthesize") as span:
        span.enrich(
            provider=_safe_speech_label(speech.tts, "name"),
            model=_safe_speech_label(speech.tts, "model"),
        )
        started = perf_counter_ns()
        try:
            segment = speech.tts.synthesize(text)
        except Exception as exc:
            span.enrich(latency_ms=_elapsed_ms(started))
            _set_speech_error(span, exc, stage="TTS_PROVIDER")
            logger.warning("TTS lỗi khi xử lý %s lượt %s: %s", call_id, turn, type(exc).__name__)
            return None
        span.enrich(latency_ms=_elapsed_ms(started))
        if segment is None:
            return None
        _enrich_audio(span, segment, include_bytes=True)
        try:
            return speech.audio_store.save(call_id, turn, segment)
        except Exception as exc:
            _set_speech_error(span, exc, stage="TTS_STORAGE")
            raise
