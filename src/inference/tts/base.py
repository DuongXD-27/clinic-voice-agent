"""Provider-neutral contract used by the TTS gateway."""

from dataclasses import dataclass
from typing import Literal, Protocol

ProviderName = Literal["openai", "elevenlabs"]


@dataclass(frozen=True)
class TTSResult:
    """PCM 16-bit little-endian mono ở tần số `sample_rate` của provider."""

    pcm: bytes
    sample_rate: int


class TTSProvider(Protocol):
    @property
    def model(self) -> str: ...

    def synthesize(self, text: str) -> TTSResult:
        """`text` đã strip, khác rỗng."""
        ...
