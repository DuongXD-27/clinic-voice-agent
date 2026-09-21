from dataclasses import dataclass, field
from typing import Optional

from speech.types import Transcript, TranscriptEvent


@dataclass
class TranscriptAggregator:
    """Gộp event partial/final thành transcript của một lượt nói.

    Partial chỉ dùng cho early intent / barge-in; engine chỉ nhận bản final.
    """

    finals: list[TranscriptEvent] = field(default_factory=list)
    partial: Optional[TranscriptEvent] = None

    def add(self, event: TranscriptEvent) -> None:
        if event.is_final:
            self.finals.append(event)
            self.partial = None
        else:
            self.partial = event

    def result(self) -> Transcript:
        text = " ".join(e.text.strip() for e in self.finals if e.text.strip())
        scores = [e.confidence for e in self.finals if e.confidence is not None]
        return Transcript(
            text=text, confidence=min(scores) if scores else None, is_silence=not text
        )

    def reset(self) -> None:
        self.finals.clear()
        self.partial = None
