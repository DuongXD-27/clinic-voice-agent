from typing import Optional

import httpx

from speech.audio.codec import decode_wav, read_wav
from speech.types import AudioSegment


def load_from_url(
    url: str, target_rate: Optional[int] = None, timeout: float = 3.0
) -> AudioSegment:
    """Tải clip wav của harness (audio_url mỗi lượt).

    Mặc định giữ tần số gốc của file: ASR tự resample một lần về tần số model, không ép qua
    8 kHz nên clip băng rộng giữ được dải 4–8 kHz. Truyền `target_rate` khi nơi gọi cần đúng
    tần số pipeline (vd. VAD của `STTPipeline`).
    """
    response = httpx.get(url, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    if target_rate is None:
        segment, _ = read_wav(response.content)
        return segment
    return decode_wav(response.content, target_rate)
