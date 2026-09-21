from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class VadEvent:
    kind: Literal["speech_start", "speech", "speech_end"]
    pcm: bytes = b""


class FrameClassifier(Protocol):
    """Phân loại một frame PCM là có tiếng nói hay không."""

    def is_speech(self, frame: bytes) -> bool: ...
