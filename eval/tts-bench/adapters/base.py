"""Minimal interface implemented by a TTS system under evaluation."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class TTSResult:
    """Result of synthesizing one golden utterance."""

    audio_path: Path
    latency_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class TTSAdapter(Protocol):
    """Contract for connecting a TTS implementation to the evaluator."""

    name: str

    def synthesize(self, text: str, output_path: Path) -> TTSResult:
        """Synthesize text into the requested output path."""
        ...
