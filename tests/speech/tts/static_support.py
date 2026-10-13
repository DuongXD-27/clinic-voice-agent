"""Offline provider and the shipped, owner-approved catalog for integration checks."""

import json
from pathlib import Path

from inference.tts import TTSGateway, TTSResult
from speech.bundle import SpeechSynthesizer
from speech.tts.static_cache import StaticAudioCache, StaticCacheSettings

# Release đang chọn trong config/tts_static.yaml: đổi release không phải sửa test
RELEASE = Path(__file__).resolve().parents[3] / StaticCacheSettings().directory


def release_manifest():
    return json.loads((RELEASE / "manifest.json").read_text(encoding="utf-8"))


class CountingProvider:
    def __init__(self, identity=None):
        self.audio_identity = identity or release_manifest()["audio_config"]
        self.stream_sample_rate = self.audio_identity["sample_rate"]
        self.model = self.voice = self.audio_identity["voice"]
        self.calls = []
        self.cancel_calls = 0

    def synthesize(self, text):
        self.calls.append(text)
        return TTSResult(
            pcm=b"\x01\x00" * 800, sample_rate=self.stream_sample_rate, voice=self.voice
        )

    async def synthesize_stream(self, text):
        yield self.synthesize(text).pcm

    async def cancel(self):
        self.cancel_calls += 1

    def close(self):
        pass


def cached_synthesizer():
    provider = CountingProvider()
    fallback = CountingProvider()
    gateway = TTSGateway(
        provider,
        provider_name="vbee",
        fallback=TTSGateway(fallback, provider_name="elevenlabs"),
    )
    store = StaticAudioCache(RELEASE, provider.audio_identity)
    return SpeechSynthesizer(gateway, store), provider, fallback
