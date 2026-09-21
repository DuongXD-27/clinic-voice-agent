"""Realtime STT pipeline + TTS, xử lý ở băng hẹp điện thoại 8 kHz."""

from typing import TYPE_CHECKING, Any

from callbot.speech.settings import SpeechSettings
from callbot.speech.storage import AudioArtifactStore
from callbot.speech.types import AudioSegment, Transcript, TranscriptEvent
from callbot.speech.vad import EnergyFrameClassifier, StreamingVAD

if TYPE_CHECKING:
    from callbot.speech.pipeline import STTPipeline
    from inference.tts.base import TTSProvider


def create_stt_pipeline(settings: SpeechSettings) -> "STTPipeline":
    from callbot.speech.pipeline import STTPipeline
    from inference.asr import create_asr

    vad = StreamingVAD(
        EnergyFrameClassifier(settings.vad_rms_threshold),
        end_silence_ms=settings.vad_end_silence_ms,
    )
    return STTPipeline(asr=create_asr(settings), vad=vad, sample_rate=settings.sample_rate)


def create_tts(settings: SpeechSettings) -> "TTSProvider":
    from inference.tts import create_tts as create_inference_tts

    return create_inference_tts(settings)


def __getattr__(name: str) -> Any:
    if name == "STTPipeline":
        from callbot.speech.pipeline import STTPipeline

        return STTPipeline
    raise AttributeError(name)


__all__ = [
    "AudioArtifactStore",
    "AudioSegment",
    "STTPipeline",
    "SpeechSettings",
    "Transcript",
    "TranscriptEvent",
    "create_stt_pipeline",
    "create_tts",
]
