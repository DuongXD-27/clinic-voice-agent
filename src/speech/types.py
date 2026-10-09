from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

# Băng hẹp điện thoại (300–3400 Hz): pipeline xử lý đúng chất lượng audio mà
# đường dây thật mang lại, không phải 16 kHz sạch của benchmark (Appendix B.1).
NARROWBAND_RATE = 8_000
WIDEBAND_RATE = 16_000
SAMPLE_WIDTH_BYTES = 2
CHANNELS = 1


@dataclass(frozen=True)
class AudioSegment:
    """PCM 16-bit little-endian, mono."""

    pcm: bytes
    sample_rate: int = NARROWBAND_RATE
    provider_actual: Optional[str] = field(default=None, compare=False)
    voice: Optional[str] = field(default=None, compare=False)
    ttfa_ms: Optional[float] = field(default=None, compare=False)
    fallback_used: bool = field(default=False, compare=False)
    cache_hit: bool = field(default=False, compare=False)
    cache_key: Optional[str] = field(default=None, compare=False)
    catalog_version: Optional[str] = field(default=None, compare=False)
    billed_characters: Optional[int] = field(default=None, compare=False)

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
    # Cloud callbacks có thể đến sau discard hoặc speech_start của lượt tiếp theo.
    generation: Optional[int] = field(default=None, compare=False)
    segment_id: Optional[int] = field(default=None, compare=False)


class AsrSegmentEnd(Enum):
    """Tín hiệu `STTPipeline` chèn vào luồng frame của `stream()` khi NGỪNG đưa audio vào ASR.

    ASR streaming tự chốt câu bằng khoảng lặng trong CHÍNH các frame nó nhận. Khi pipeline
    ngừng đưa frame (bot bắt đầu nói giữa câu), ASR không bao giờ
    thấy đủ khoảng lặng: câu dở nằm lại trong buffer rồi thành final giả ở đầu câu sau,
    hoặc bị ghép vào câu sau. Bug thật (cuộc gọi LiveKit 2026-09-26): lượt 2 lặp lại
    nguyên văn lượt 1, lượt 3 thành "ANH SINH ANH SINH NGÀY ...".

    DISCARD: bỏ phần đang có, không phát event nào.
    FINALIZE: chốt ngay phần đang có thành final (nếu đủ tiếng nói) rồi đóng câu — lời người gọi
    bắt đầu trước khi bot nói, kết thúc giữa lúc bot nói mà chưa được xác nhận ngắt lời. Chỉ gửi
    cho provider có `supports_segment_finalize`.
    """

    DISCARD = "discard"
    FINALIZE = "finalize"


@dataclass(frozen=True)
class Transcript:
    """Transcript đã chốt của một lượt nói — đầu vào cho engine."""

    text: str = ""
    confidence: Optional[float] = None
    is_silence: bool = False
