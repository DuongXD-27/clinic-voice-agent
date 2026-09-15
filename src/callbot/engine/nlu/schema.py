from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional

from callbot.engine.types import CancelReason


class Intent(str, Enum):
    CONFIRM_ATTENDANCE = "CONFIRM_ATTENDANCE"
    CANCEL = "CANCEL"
    RESCHEDULE = "RESCHEDULE"
    BOOK = "BOOK"
    AFFIRM = "AFFIRM"
    DENY = "DENY"
    CLINICAL_QUESTION = "CLINICAL_QUESTION"
    REQUEST_HUMAN = "REQUEST_HUMAN"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    ABUSIVE = "ABUSIVE"
    UNKNOWN = "UNKNOWN"


@dataclass
class Entities:
    full_name: Optional[str] = None
    dob: Optional[date] = None
    preferred_date: Optional[date] = None
    preferred_period: Optional[str] = None  # "MORNING" | "AFTERNOON" | "EVENING"
    slot_choice_index: Optional[int] = None
    cancel_reason: Optional[CancelReason] = None


@dataclass
class NLUResult:
    intent: Intent
    entities: Entities = field(default_factory=Entities)
    confidence: float = 1.0
    raw_text: str = ""

    @property
    def understood(self) -> bool:
        return self.intent is not Intent.UNKNOWN
