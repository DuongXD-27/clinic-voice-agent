"""Câu ghi sẵn phát khi TTS lỗi giữa cuộc gọi (R-39).

Lúc cần câu này thì chính provider TTS đang lỗi, nên đọc thẳng release audio tĩnh đã duyệt
(`static_cache.load_release`, kiểm checksum như cache thường), không phụ thuộc `TTS_STATIC_ENABLED`
hay provider đang dùng. Chỉ trả audio khi text trùng nguyên văn câu của asset; không ghép, không đọc
câu gần giống.
"""

import logging
from functools import lru_cache

from speech.audio.codec import resample
from speech.tts.static_cache import StaticCacheSettings, load_release

logger = logging.getLogger(__name__)


def fixed_utterance_pcm(
    text: str, track_rate: int, settings: StaticCacheSettings | None = None
) -> bytes | None:
    """PCM16 mono của câu ghi sẵn ở tần số track phát (`track_rate`), None khi không có asset.

    Asset là 8 kHz; track LiveKit tạo theo provider TTS chính (OpenAI 24 kHz) nên có thể lệch:
    resample một lần cả câu rồi mới chia frame — resample từng frame sẽ có tiếng tách ở chỗ nối.
    """
    if settings is not None:
        return _load(text, track_rate, settings)
    return _load_default(text, track_rate)


@lru_cache(maxsize=8)
def _load_default(text: str, track_rate: int) -> bytes | None:
    return _load(text, track_rate, StaticCacheSettings())


def _load(text: str, track_rate: int, settings: StaticCacheSettings) -> bytes | None:
    release = load_release(settings)
    segment = release.lookup(text) if release is not None else None
    if segment is None:
        logger.error("TTS_FALLBACK_AUDIO_MISSING")
        return None
    if segment.sample_rate == track_rate:
        return segment.pcm
    return resample(segment.pcm, segment.sample_rate, track_rate)
