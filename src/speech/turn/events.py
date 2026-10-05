from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class UserTurnCompleted:
    """Output của TurnController — transport chuyển thành CallerInput (engine.types) để
    gọi orchestrator.handle_turn(); KHÔNG phải type của engine (Core không biết VAD/ASR).
    """

    text: str
    confidence: Optional[float] = None
    silence_ms: int = 0
    audio_duration_ms: Optional[float] = field(default=None, compare=False)
    first_partial_ms: Optional[float] = field(default=None, compare=False)
    final_ms: Optional[float] = field(default=None, compare=False)
    partial_count: int = field(default=0, compare=False)
    vad_end_reason: Optional[str] = field(default=None, compare=False)
