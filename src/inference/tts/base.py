from typing import Optional, Protocol

from callbot.speech.types import AudioSegment


class TTSProvider(Protocol):
    name: str

    def synthesize(self, text: str) -> Optional[AudioSegment]: ...
