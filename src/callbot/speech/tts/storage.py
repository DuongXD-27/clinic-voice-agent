import re
from pathlib import Path

from callbot.speech.audio.codec import encode_wav, to_sample_rate
from callbot.speech.types import NARROWBAND_RATE, AudioSegment

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


class AudioArtifactStore:
    """Lưu audio của bot tại <audio_dir>/<call_id>/<turn>.wav và dựng audio_url công khai.

    TTS thường trả 16–24 kHz; audio được hạ về băng hẹp để nghe giống hệt trên đường dây.
    """

    def __init__(
        self, audio_dir: str, public_base_url: str, sample_rate: int = NARROWBAND_RATE
    ) -> None:
        self.directory = Path(audio_dir)
        self._base_url = public_base_url.rstrip("/")
        self._sample_rate = sample_rate

    def save(self, call_id: str, turn: int, segment: AudioSegment) -> str:
        path = self.path_for(call_id, turn)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encode_wav(to_sample_rate(segment, self._sample_rate)))
        return f"{self._base_url}/audio/{call_id}/{turn}.wav"

    def path_for(self, call_id: str, turn: int) -> Path:
        if not _SAFE_ID.match(call_id):
            raise ValueError(f"call_id không hợp lệ: {call_id!r}")
        return self.directory / call_id / f"{turn}.wav"
