"""Bundle speech (ASR/TTS/audio storage) cho đường HTTP `mode="audio"` (§4.1.2).

Sống ở tầng transport, không phải `engine/`: Core không được biết khái niệm
audio/text (nguyên tắc đã áp dụng cho STT/TTS provider — xem `engine/orchestrator.py`
không import gì từ `speech/`). `CallModeStore` cũng vì lý do đó không nằm trong
`CallStart`/`CallContext` của engine.
"""

import logging
from dataclasses import dataclass
from typing import Callable

from redis import Redis

from callbot.speech.asr import create_asr
from callbot.speech.asr.base import ASRProvider
from callbot.speech.audio.loader import load_from_url
from callbot.speech.settings import SpeechSettings
from callbot.speech.tts import create_tts
from callbot.speech.tts.base import TTSProvider
from callbot.speech.tts.storage import AudioArtifactStore
from callbot.speech.types import AudioSegment

logger = logging.getLogger(__name__)


@dataclass
class SpeechBundle:
    asr: ASRProvider
    tts: TTSProvider
    audio_store: AudioArtifactStore
    # Seam cho test — mặc định tải thật qua HTTP như harness gửi.
    audio_loader: Callable[[str], AudioSegment] = load_from_url


def build_speech_bundle(settings: SpeechSettings) -> SpeechBundle:
    return SpeechBundle(
        asr=create_asr(settings),
        tts=create_tts(settings),
        audio_store=AudioArtifactStore(settings.audio_dir, settings.public_base_url),
    )


def warm_up(bundle: SpeechBundle) -> None:
    """Buộc ASR load model (vd. ZipFormer ~1.8s lần đầu) trước khi nhận traffic thật.

    Không để lượt đầu tiên của cuộc gọi đầu tiên gánh chi phí này trong ngân sách
    8 giây/lượt (§4.1.2). Không fail startup nếu provider không warm-up được (vd.
    provider hosted cần API key chưa cấu hình) — chỉ log, mode=audio khi đó vẫn sẽ
    lỗi rõ ràng ở lượt gọi thật thay vì im lặng chặn app khởi động.
    """
    try:
        segment = AudioSegment(pcm=b"\x00\x00" * 1600, sample_rate=bundle.asr.input_sample_rate)
        bundle.asr.transcribe(segment)
    except Exception:
        logger.warning("Không warm-up được ASR provider %s", getattr(bundle.asr, "name", "?"))


class CallModeStore:
    """Nhớ cuộc gọi nào đang `mode=audio` — Redis riêng, không đụng `RedisSessionStore`.

    Cần Redis (không phải dict trong process) vì `WEB_CONCURRENCY` chạy nhiều worker
    process; lượt `turn` có thể rơi vào worker khác với lượt `start_call`. Nhận thẳng
    `client` (không tự tạo từ URL) để test có thể tiêm `fakeredis` giống `RedisSessionStore`.
    """

    def __init__(self, client: Redis, *, key_prefix: str = "callbot", ttl_s: int = 7200) -> None:
        self._client = client
        self._prefix = key_prefix.rstrip(":")
        self._ttl_s = ttl_s

    def _key(self, call_id: str) -> str:
        return f"{self._prefix}:audio_mode:{call_id}"

    def set_audio(self, call_id: str) -> None:
        self._client.set(self._key(call_id), "1", ex=self._ttl_s)

    def is_audio(self, call_id: str) -> bool:
        return self._client.get(self._key(call_id)) is not None

    def close(self) -> None:
        self._client.close()
