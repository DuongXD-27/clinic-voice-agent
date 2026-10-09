"""Exact text and non-secret Vbee settings identify a prerecorded asset."""

import hashlib
import json

from inference.tts.config import VbeeTTSConfig

SCHEMA_VERSION = 1


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: dict) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def cache_key(text: str, config: dict) -> str:
    return digest(canonical_json({"exact_text": text, **config}))


def vbee_audio_identity(config: VbeeTTSConfig) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": "vbee",
        "endpoint": config.endpoint,
        "api_mode": "sync",
        "model": config.voice_code,
        "voice": config.voice_code,
        "speed": config.speed,
        "bitrate": config.bitrate,
        "sample_rate": config.sample_rate,
        "output_format": "pcm",
        "encoding": "PCM_S16LE",
        "channels": 1,
    }
