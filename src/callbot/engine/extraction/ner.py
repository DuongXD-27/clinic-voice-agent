"""Name NER fallback: ground and normalize the provider result into a Field."""

import logging
from typing import Self

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from callbot.engine.extraction.fallback import guard_fallback
from callbot.engine.extraction.full_name import valid_name_span
from callbot.engine.extraction.schema import Field, Intent, Provenance, QuestionId
from callbot.engine.extraction.text import clean
from inference.common.telemetry import InferenceTimer
from inference.llm.gateway import LLMGateway
from inference.llm.prompt.ner import PROMPT_VERSION, build_messages

logger = logging.getLogger(__name__)


class NameExtraction(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    full_name: str | None
    span: str | None

    @model_validator(mode="after")
    def paired_fields(self) -> Self:
        if (self.full_name is None) != (self.span is None):
            raise ValueError("Name and span must both be null or both be strings")
        return self


class NameNER:
    def __init__(self, gateway: LLMGateway) -> None:
        self._gateway = gateway

    def intent(self, transcript: str, allowed: frozenset[Intent]) -> None:
        return None

    def agreement(self, transcript: str, question_id: QuestionId) -> None:
        return None

    def full_name(self, transcript: str) -> Field[str]:
        timer = InferenceTimer()
        status = "invalid_response"
        reply = None
        try:
            if not clean(transcript):
                status = "empty"
                return Field.nothing()
            reply = self._gateway.generate_structured(
                build_messages(transcript),
                schema=NameExtraction.model_json_schema(),
                schema_name=PROMPT_VERSION,
            )
            if reply.status != "completed" or reply.content is None:
                status = reply.status
                return Field.nothing()
            result = NameExtraction.model_validate_json(reply.content)
            if result.full_name is None:
                status = "no_name"
                return Field.nothing()

            name, span = clean(result.full_name), clean(result.span or "")
            if name != span or not valid_name_span(name):
                status = "rejected"
                return Field.nothing()
            guarded = guard_fallback(Field(name, Provenance.FALLBACK, span), transcript, None)
            status = "accepted" if guarded.found else "rejected"
            return guarded
        except ValidationError:
            status = "invalid_response"
        finally:
            # Never log exception text, response bodies, names, transcripts, or credentials.
            logger.info(
                "Name NER fallback: %s",
                status,
                extra={
                    "ner_provider": self._gateway.provider_name,
                    "ner_model": self._gateway.model,
                    "ner_prompt_version": PROMPT_VERSION,
                    "ner_status": status,
                    "ner_elapsed_ms": timer.elapsed_ms,
                    "ner_prompt_tokens": reply.prompt_tokens if reply else None,
                    "ner_completion_tokens": reply.completion_tokens if reply else None,
                },
            )
        return Field.nothing()
