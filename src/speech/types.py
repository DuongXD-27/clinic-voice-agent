from dataclasses import dataclass
from typing import Literal, Optional

# Băng hẹp điện thoại (300–3400 Hz): pipeline xử lý đúng chất lượng audio mà
# đường dây thật mang lại, không phải 16 kHz sạch của benchmark (Appendix B.1).
NARROWBAND_RATE = 8_000
WIDEBAND_RATE = 16_000
SAMPLE_WIDTH_BYTES = 2
CHANNELS = 1

SampleRate = Literal[8_000, 16_000]


@dataclass(frozen=True)
class AudioSegment:
    """PCM 16-bit little-endian, mono."""

    pcm: bytes
    sample_rate: int = NARROWBAND_RATE

    @property
    def duration_ms(self) -> int:
        return int(len(self.pcm) / SAMPLE_WIDTH_BYTES / self.sample_rate * 1000)


@dataclass(frozen=True)
class TranscriptEvent:
    """Một event từ ASR streaming — partial (chưa chốt) hoặc final."""

    text: str
    is_final: bool
    confidence: Optional[float] = None
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None


@dataclass(frozen=True)
class Transcript:
    """Transcript đã chốt của một lượt nói — đầu vào cho engine."""

    text: str = ""
    confidence: Optional[float] = None
    is_silence: bool = False
