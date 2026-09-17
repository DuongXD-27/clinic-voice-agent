"""Information Extraction — thiết kế docs/reference/information-extraction-design.md v1.1.

Một file cho mỗi trường ở §1 của thiết kế; `extractor.InformationExtractor` điều phối theo `question_id`.
"""

from callbot.engine.extraction.extractor import IDENTITY_SAFE_INTENTS, InformationExtractor
from callbot.engine.extraction.fallback import FallbackExtractor
from callbot.engine.extraction.schema import (
    INVALID,
    Agreement,
    ClinicalLevel,
    ExtractionResult,
    Field,
    Intent,
    LineSignal,
    Provenance,
    QuestionId,
    SlotChoice,
    SlotCriteria,
    TurnContext,
)
from callbot.engine.extraction.slot_choice import filter_slots, parse_slot_criteria

__all__ = [
    "IDENTITY_SAFE_INTENTS",
    "INVALID",
    "Agreement",
    "ClinicalLevel",
    "ExtractionResult",
    "FallbackExtractor",
    "Field",
    "InformationExtractor",
    "Intent",
    "LineSignal",
    "Provenance",
    "QuestionId",
    "SlotChoice",
    "SlotCriteria",
    "TurnContext",
    "filter_slots",
    "parse_slot_criteria",
]
