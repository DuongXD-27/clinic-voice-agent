from typing import Literal, Optional

from pydantic import BaseModel, Field

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
    max_turns: int = Field(strict=True)


class StartCallResponse(BaseModel):
    call_id: str
    utterance: str
    audio_url: Optional[str]
    state: CallState
    turn: int


class TurnRequest(BaseModel):
    turn: int = Field(strict=True)
    audio_url: Optional[str]
    text: Optional[str]
    silence_ms: int = Field(strict=True, ge=0)


class TurnResponse(BaseModel):
    utterance: str
    audio_url: Optional[str]
    state: CallState
    ended: bool
    outcome: Optional[Outcome]
