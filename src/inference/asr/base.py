"""Provider-neutral contract used by the ASR gateway."""

from dataclasses import dataclass
from typing import Literal, Protocol

ProviderName = Literal["gemini", "phowhisper", "zipformer"]


@dataclass(frozen=True)
class ASRResult:
    text: str
    confidence: float | None = None


class ASRProvider(Protocol):
    # Tần số model cần; gateway chỉ nhận audio đã ở đúng tần số này.
    input_sample_rate: int

    @property
    def model(self) -> str: ...

    def transcribe(self, pcm: bytes) -> ASRResult:
        """PCM 16-bit little-endian mono, ở `input_sample_rate`, khác rỗng."""
        ...
