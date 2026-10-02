"""Provider-neutral contract used by the TTS gateway."""

from dataclasses import dataclass
from typing import Literal, Protocol

ProviderName = Literal["openai", "elevenlabs", "vbee"]


@dataclass(frozen=True)
class TTSResult:
    """PCM 16-bit little-endian mono ở tần số `sample_rate` của provider."""

    pcm: bytes
    sample_rate: int
    provider_actual: str | None = None
    voice: str | None = None
    ttfa_ms: float | None = None
    fallback_used: bool = False


@dataclass
class TTSStreamInfo:
    """Câu đang/vừa stream qua gateway: ai đọc, ở tần số nào, có phải dự phòng không.

    Gateway điền khi có chunk đầu; observability (CallBridge) đọc qua `last_stream_result`.
    `error_code` có giá trị khi provider lỗi giữa câu: stream đã dừng, không đọc lại.
    """

    provider_actual: str
    voice: str | None
    sample_rate: int
    fallback_used: bool = False
    ttfa_ms: float | None = None
    error_code: str | None = None


class TTSProvider(Protocol):
    @property
    def model(self) -> str: ...

    def synthesize(self, text: str) -> TTSResult:
        """`text` đã strip, khác rỗng."""
        ...
