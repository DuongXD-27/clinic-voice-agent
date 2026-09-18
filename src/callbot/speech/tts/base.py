from dataclasses import asdict, dataclass
from typing import Any, Optional, Protocol

from callbot.speech.types import AudioSegment


class TTSProvider(Protocol):
    name: str

    def synthesize(self, text: str) -> Optional[AudioSegment]: ...


@dataclass
class TTSTiming:
    """Số đo một lần sinh audio (kế hoạch TTS §2.5, TTS-1.6). Không chứa text để log không rò PII."""

    chars: int = 0
    connect_ms: Optional[int] = None  # mở kết nối tới provider
    ttfa_ms: Optional[int] = None  # time-to-first-audio: chunk PCM đầu tiên
    last_chunk_ms: Optional[int] = None  # chunk cuối / isFinal
    total_ms: Optional[int] = None
    audio_bytes: int = 0
    chunks: int = 0

    def to_trace(self) -> dict[str, Any]:
        return asdict(self)


class NullTTS:
    """Không sinh audio — audio_url trả về null (mode text, hoặc chưa cấu hình provider)."""

    name = "none"

    def synthesize(self, text: str) -> Optional[AudioSegment]:
        return None
