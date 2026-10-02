"""Map committed caller speech to Core without making dialogue decisions."""

from typing import Optional

from callbot.engine import CallerInput


def caller_input_from_transcript(
    turn: int,
    text: Optional[str],
    *,
    silence_ms: int = 0,
    audio_url: Optional[str] = None,
    confidence: Optional[float] = None,
) -> CallerInput:
    """Explicit silence wins; empty ASR text with no silence remains speech input.

    Keep transcript spelling and source URL for session ordering/replay. Confidence
    is metadata only and cannot select identity, intent or a phone status.
    """
    return CallerInput(
        turn=turn,
        text=None if silence_ms > 0 else text,
        silence_ms=silence_ms,
        audio_url=audio_url,
        asr_confidence=None if silence_ms > 0 else confidence,
    )
