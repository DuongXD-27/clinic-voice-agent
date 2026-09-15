"""Realtime STT pipeline + TTS, xử lý ở băng hẹp điện thoại 8 kHz."""

from callbot.speech.asr import create_asr
from callbot.speech.pipeline import STTPipeline
from callbot.speech.settings import SpeechSettings
from callbot.speech.tts import AudioArtifactStore, create_tts
from callbot.speech.types import AudioSegment, Transcript, TranscriptEvent
from callbot.speech.vad import EnergyFrameClassifier, StreamingVAD


def create_stt_pipeline(settings: SpeechSettings) -> STTPipeline:
    vad = StreamingVAD(
        EnergyFrameClassifier(settings.vad_rms_threshold),
        end_silence_ms=settings.vad_end_silence_ms,
    )
    return STTPipeline(asr=create_asr(settings), vad=vad, sample_rate=settings.sample_rate)


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
