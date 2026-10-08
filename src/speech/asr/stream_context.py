"""Per-stream state for remote ASR; never stored on a shared provider instance."""

import asyncio
from dataclasses import dataclass

from speech.types import TranscriptEvent


@dataclass(frozen=True)
class StreamingFrame:
    pcm: bytes
    generation: int
    segment_id: int
    # Audio replayed by the transport must survive the provider's smaller onset buffer.
    is_preroll: bool = False


class ASRStreamContext:
    def __init__(self) -> None:
        self.generation = 0
        self.segment_id = 0
        self.turn_first_segment_id = 0
        self.invalidated = asyncio.Event()
        self.pending: set[tuple[int, int]] = set()

    def start_utterance(self, *, continues_turn: bool = False) -> None:
        """Mở đoạn mới. `continues_turn`: đoạn thuộc cùng lượt với đoạn trước (TurnController
        nối các đoạn), nên final tới muộn của đoạn trước vẫn được nhận."""
        self.segment_id += 1
        if not continues_turn:
            self.turn_first_segment_id = self.segment_id

    def invalidate(self) -> None:
        self.invalidated.set()
        self.invalidated = asyncio.Event()
        self.generation += 1
        self.pending.clear()

    def accepts(self, event: TranscriptEvent) -> bool:
        return (
            event.generation == self.generation
            and event.segment_id is not None
            and self.turn_first_segment_id <= event.segment_id <= self.segment_id
        )
