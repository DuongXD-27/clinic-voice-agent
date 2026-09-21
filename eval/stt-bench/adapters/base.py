"""Minimal interface implemented by an STT system under evaluation."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class STTResult:
    """One final transcription returned by an STT adapter."""

    text: str
    latency_ms: float | None = None
    is_final: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class STTAdapter(Protocol):
    """Contract for connecting an STT implementation to the evaluator."""

    name: str

    def transcribe(self, audio_path: Path) -> STTResult:
        """Transcribe one audio file without changing it."""
        ...
