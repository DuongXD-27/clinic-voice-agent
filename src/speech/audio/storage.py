import hashlib
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from speech.audio.codec import encode_wav, to_sample_rate
from speech.types import NARROWBAND_RATE, AudioSegment

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
# Audio tĩnh đã duyệt, phục vụ từ RAM theo cache key (transports/http/main.py). Không nằm dưới
# /audio/ để không trùng thư mục audio theo cuộc gọi.
STATIC_AUDIO_PATH = "/audio-static"


class AudioArtifactStore:
    """Lưu audio của bot (TTS) và clip demo upload tại <audio_dir>/<call_id>/<turn>.wav và dựng audio_url công khai.

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
        path.with_suffix(".sha256").unlink(missing_ok=True)
        self._atomic_write(path, encode_wav(to_sample_rate(segment, self._sample_rate)))
        return f"{self._base_url}/audio/{call_id}/{turn}.wav"

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def remember_utterance(self, call_id: str, turn: int, text: str) -> None:
        path = self.path_for(call_id, turn).with_suffix(".sha256")
        self._atomic_write(path, hashlib.sha256(text.encode("utf-8")).hexdigest().encode("ascii"))

    def cached_url(self, call_id: str, turn: int, text: str) -> str | None:
        path = self.path_for(call_id, turn)
        try:
            digest = path.with_suffix(".sha256").read_text(encoding="ascii")
            if path.is_file() and digest == hashlib.sha256(text.encode("utf-8")).hexdigest():
                return f"{self._base_url}/audio/{call_id}/{turn}.wav"
        except FileNotFoundError:
            pass
        return None

    def static_url(self, cache_key: str) -> str:
        return f"{self._base_url}{STATIC_AUDIO_PATH}/{cache_key}.wav"

    def path_for(self, call_id: str, turn: int) -> Path:
        if not _SAFE_ID.match(call_id):
            raise ValueError(f"call_id không hợp lệ: {call_id!r}")
        return self.directory / call_id / f"{turn}.wav"

    def purge_older_than(self, max_age_s: float) -> int:
        """Xoá thư mục cuộc gọi không được ghi thêm trong `max_age_s` giây; trả về số đã xoá.

        Quét cả `demo-input/<call_id>` (clip upload từ trang demo). Dùng mtime của thư mục —
        cập nhật mỗi khi có lượt mới ghi file vào — nên cuộc gọi đang diễn ra không bị xoá.
        """
        cutoff = time.time() - max_age_s
        removed = 0
        for root in (self.directory, self.directory / "demo-input"):
            if not root.is_dir():
                continue
            for call_dir in root.iterdir():
                if not call_dir.is_dir() or call_dir.name == "demo-input":
                    continue
                try:
                    if call_dir.stat().st_mtime < cutoff:
                        shutil.rmtree(call_dir)
                        removed += 1
                except FileNotFoundError:
                    # Worker khác vừa xoá cùng thư mục.
                    continue
        return removed
