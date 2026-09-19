from typing import Protocol


class FrameClassifier(Protocol):
    """Phân loại một frame PCM là có tiếng nói hay không."""

    def is_speech(self, frame: bytes) -> bool: ...
