from typing import Optional

from callbot.speech.types import AudioSegment


class NullTTS:
    """Do not synthesize audio; callers receive no audio artifact."""

    name = "none"

    def synthesize(self, text: str) -> Optional[AudioSegment]:
        return None
