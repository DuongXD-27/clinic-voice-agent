from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

CallState = Literal[
    "AWAITING_IDENTITY",
    "AWAITING_INTENT",
    "AWAITING_CONFIRMATION",
    "OFFERING_SLOTS",
    "CLOSING",
    "ENDED",
]

Outcome = Literal[
    "CONFIRMED",
    "CANCELLED",
    "RESCHEDULED",
    "TRANSFERRED",
    "UNREACHABLE",
    "BOOKED",
    "SCHEDULED",
]


class StartCallRequest(BaseModel):
    call_id: str
    direction: Literal["inbound", "outbound"]
    appointment_id: Optional[str]
    caller_number: Optional[str]
    locale: str
    mode: Literal["text", "audio"]
    max_turns: int = Field(strict=True, gt=0)

    @model_validator(mode="after")
    def _check_direction_fields(self) -> "StartCallRequest":
        # §1.1.8: outbound gắn với một lịch hẹn; inbound không có appointment_id. `caller_number` được
        # phép null (Listing 1) — harness gửi null ở mọi case inbound; engine tự xử lý khi thiếu số.
        if self.direction == "outbound" and not self.appointment_id:
            raise ValueError("outbound yêu cầu appointment_id")
        if self.direction == "inbound" and self.appointment_id is not None:
            raise ValueError("inbound không được có appointment_id")
        return self


class StartCallResponse(BaseModel):
    call_id: str
    utterance: str
    audio_url: Optional[str]
    state: CallState
    turn: int


class TurnRequest(BaseModel):
    turn: int = Field(strict=True, ge=1)
    audio_url: Optional[str]
    text: Optional[str]
    silence_ms: int = Field(strict=True, ge=0)

    @model_validator(mode="after")
    def _check_has_input(self) -> "TurnRequest":
        # text=null chỉ hợp lệ khi lượt im lặng hoặc có audio
        if self.text is None and self.audio_url is None and self.silence_ms == 0:
            raise ValueError("text=null chỉ hợp lệ khi silence_ms > 0")
        return self


class ExtractionDebug(BaseModel):
    """Non-PII extraction diagnostics exposed by the interactive demo."""

    question_id: Optional[str]
    source: Literal["RULE", "NER", "LLM", "NONE"]
    provenance: Literal["EXACT", "NORMALIZED", "FALLBACK", "NONE"]


class TurnResponse(BaseModel):
    utterance: str
    audio_url: Optional[str]
    state: CallState
    ended: bool
    outcome: Optional[Outcome]
