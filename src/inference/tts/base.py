"""Provider-neutral contract used by the TTS gateway."""

from dataclasses import dataclass
from typing import Awaitable, Callable, Literal, Optional, Protocol

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
    `error_code` có giá trị khi provider lỗi giữa câu: stream đã dừng, không đọc lại, người gọi
    chỉ nghe được một phần câu — CallBridge ghi span ERROR + truncated, không tính tiền.
    """

    provider_actual: str
    voice: str | None
    sample_rate: int
    fallback_used: bool = False
    ttfa_ms: float | None = None
    error_code: str | None = None
    cache_hit: bool = False
    cache_key: str | None = None
    catalog_version: str | None = None
    billed_characters: int | None = None


@dataclass
class StreamHandle:
    """State của MỘT lần stream: cờ hủy và cách đóng kết nối đang mở.

    Gateway/provider sống cả cuộc gọi, còn generator của câu cũ có thể dọn dẹp muộn (finalizer
    chạy khi câu mới đã bắt đầu). State nằm trên handle riêng mỗi câu thì phần dọn dẹp muộn chỉ
    chạm handle của nó, không xoá kết nối của câu đang phát — barge-in vẫn đóng được request.
    """

    cancelled: bool = False
    close: Optional[Callable[[], Awaitable[object]]] = None

    async def cancel(self) -> None:
        self.cancelled = True
        close = self.close
        if close is not None:
            await close()


class TTSProvider(Protocol):
    @property
    def model(self) -> str: ...

    def synthesize(self, text: str) -> TTSResult:
        """`text` đã strip, khác rỗng."""
        ...
