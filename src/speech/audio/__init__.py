"""Codec PCM/WAV/G.711 và tải clip audio — chuẩn hoá mọi nguồn về PCM 16-bit mono."""

from speech.audio.codec import decode_wav, encode_wav, resample, to_sample_rate
from speech.audio.g711 import alaw_to_pcm16, mulaw_to_pcm16
from speech.audio.loader import load_from_url

__all__ = [
    "alaw_to_pcm16",
    "decode_wav",
    "encode_wav",
    "load_from_url",
    "mulaw_to_pcm16",
    "resample",
    "to_sample_rate",
]
