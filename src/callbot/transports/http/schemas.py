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
    appointment_id: Optional[str] = None
    caller_number: Optional[str] = None
    locale: str = "vi-VN"
    mode: Literal["text", "audio"] = "text"
    max_turns: int = 20


class StartCallResponse(BaseModel):
    call_id: str
    utterance: str
    audio_url: Optional[str] = None
    state: CallState
    turn: int = 0


class TurnRequest(BaseModel):
    turn: int
    audio_url: Optional[str] = None
    text: Optional[str] = None
    silence_ms: int = Field(default=0, ge=0)


class TurnResponse(BaseModel):
    utterance: str
    audio_url: Optional[str] = None
    state: CallState
    ended: bool = False
    outcome: Optional[Outcome] = None
