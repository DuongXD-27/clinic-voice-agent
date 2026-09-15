from typing import Optional, Protocol

from callbot.speech.types import AudioSegment


class TTSProvider(Protocol):
    name: str

    def synthesize(self, text: str) -> Optional[AudioSegment]: ...


class NullTTS:
    """Không sinh audio — audio_url trả về null.

    TODO: tích hợp Viettel AI / FPT.AI / Vbee khi cần audio thật (Appendix B.1).
    """

    name = "none"

    def synthesize(self, text: str) -> Optional[AudioSegment]:
        return None
