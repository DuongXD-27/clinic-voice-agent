import httpx

from callbot.speech.audio.codec import decode_wav
from callbot.speech.types import NARROWBAND_RATE, AudioSegment


def load_from_url(url: str, target_rate: int = NARROWBAND_RATE, timeout: float = 3.0) -> AudioSegment:
    """Tải clip wav của harness (audio_url mỗi lượt) và chuẩn hoá về tần số pipeline."""
    response = httpx.get(url, timeout=timeout)
    response.raise_for_status()
    return decode_wav(response.content, target_rate)
