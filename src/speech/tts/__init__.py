"""Chiều ra: text của bot -> TTS gateway -> `AudioSegment` -> file wav phục vụ qua `audio_url`."""

from speech.tts.storage import AudioArtifactStore
from speech.tts.synthesizer import SpeechSynthesizer, Synthesizer

__all__ = ["AudioArtifactStore", "SpeechSynthesizer", "Synthesizer"]
