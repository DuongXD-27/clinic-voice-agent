"""Chiều vào: audio người gọi -> VAD -> ASR gateway -> `Transcript`."""

from speech.asr.recognizer import Recognizer, SpeechRecognizer

__all__ = ["Recognizer", "SpeechRecognizer"]
