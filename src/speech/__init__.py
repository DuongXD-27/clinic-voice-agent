"""Realtime STT pipeline + audio storage, xử lý ở băng hẹp điện thoại 8 kHz.

Model ASR/TTS được gọi qua gateway `inference.asr` / `inference.tts`; `speech.asr` chuyển
`AudioSegment` thành `Transcript`, `speech.bundle` bọc PCM của TTS thành `AudioSegment`,
`speech.audio.storage` ghi WAV phục vụ qua `audio_url`.
"""

from typing import Any

from speech.audio.storage import AudioArtifactStore
from speech.settings import SpeechSettings


def __getattr__(name: str) -> Any:
    if name == "STTPipeline":
        from speech.asr.pipeline import STTPipeline

        return STTPipeline
    raise AttributeError(name)


__all__ = [
    "AudioArtifactStore",
    "STTPipeline",
    "SpeechSettings",
]
