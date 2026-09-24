from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class UserTurnCompleted:
    """Output của TurnController — transport chuyển thành CallerInput (engine.types) để
    gọi orchestrator.handle_turn(); KHÔNG phải type của engine (Core không biết VAD/ASR).
    """

    text: str
    confidence: Optional[float] = None
    silence_ms: int = 0
