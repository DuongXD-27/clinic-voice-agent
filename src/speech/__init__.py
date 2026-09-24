"""Realtime STT pipeline + audio storage, xử lý ở băng hẹp điện thoại 8 kHz.

Model ASR/TTS được gọi qua gateway `inference.asr` / `inference.tts`; `speech.asr` chuyển
`AudioSegment` thành `Transcript`, `speech.bundle` bọc PCM của TTS thành `AudioSegment`,
`speech.audio.storage` ghi WAV phục vụ qua `audio_url`.
"""

from typing import TYPE_CHECKING, Any

from speech.asr.vad import EnergyFrameClassifier, StreamingVAD
from speech.audio.storage import AudioArtifactStore
from speech.settings import SpeechSettings

if TYPE_CHECKING:
    from speech.asr.pipeline import STTPipeline


def create_stt_pipeline(settings: SpeechSettings) -> "STTPipeline":
    from inference.asr import create_asr_gateway
    from speech.asr.pipeline import STTPipeline
    from speech.asr.recognizer import SpeechRecognizer

    vad = StreamingVAD(
        EnergyFrameClassifier(settings.vad_rms_threshold),
        end_silence_ms=settings.vad_end_silence_ms,
    )
    return STTPipeline(
        asr=SpeechRecognizer(create_asr_gateway(settings.asr_provider)),
        vad=vad,
        sample_rate=settings.sample_rate,
    )


def __getattr__(name: str) -> Any:
    if name == "STTPipeline":
        from speech.asr.pipeline import STTPipeline

        return STTPipeline
    raise AttributeError(name)


__all__ = [
    "AudioArtifactStore",
    "STTPipeline",
    "SpeechSettings",
    "create_stt_pipeline",
]
