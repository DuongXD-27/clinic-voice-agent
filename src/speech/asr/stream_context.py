"""Per-stream state for remote ASR; never stored on a shared provider instance."""

import asyncio
from dataclasses import dataclass

from speech.types import TranscriptEvent


@dataclass(frozen=True)
class StreamingFrame:
    pcm: bytes
    generation: int
    segment_id: int


class ASRStreamContext:
    def __init__(self) -> None:
        self.generation = 0
        self.segment_id = 0
        self.invalidated = asyncio.Event()
        self.pending: set[tuple[int, int]] = set()

    def start_utterance(self) -> None:
        self.segment_id += 1

    def invalidate(self) -> None:
        self.invalidated.set()
        self.invalidated = asyncio.Event()
        self.generation += 1
        self.pending.clear()

    def accepts(self, event: TranscriptEvent) -> bool:
        return event.generation == self.generation and event.segment_id == self.segment_id
