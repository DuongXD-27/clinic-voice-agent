"""Read-only, approved static audio. Load and verify once per process/configuration.

Only exact utterances can hit. PCM is immutable in memory after verification;
release files are replaced by deploying a new version, never by a runtime writer.
Missing/invalid assets remain misses and use the existing provider gateway.
"""

import io
import json
import logging
import re
import wave
from functools import lru_cache
from pathlib import Path

from appconfig import CONFIG_DIR, YamlSettings, yaml_config
from inference.tts import TTSGateway
from inference.tts.static_identity import SCHEMA_VERSION, cache_key, canonical_json, digest
from speech.types import AudioSegment

logger = logging.getLogger(__name__)


class StaticCacheSettings(YamlSettings):
    model_config = yaml_config("tts_static.yaml", env_prefix="TTS_STATIC_")

    enabled: bool
    directory: str


class StaticAudioCache:
    def __init__(self, directory: Path, identity: dict):
        self._audio: dict[str, AudioSegment] = {}
        self.catalog_version: str | None = None
        try:
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            if (
                manifest["schema_version"] != SCHEMA_VERSION
                or manifest["release_ready"] is not True
                or manifest["status"] != "RELEASED"
                or manifest["audio_config"] != identity
            ):
                logger.warning("TTS_STATIC_MANIFEST_MISMATCH")
                return
            version = manifest["catalog_version"]
            if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", version):
                raise ValueError("Invalid catalog version")
            self.catalog_version = version
            entries = manifest["assets"]
            keys = [e["cache_key"] for e in entries]
            if len(keys) != len(set(keys)):
                raise ValueError("Duplicate cache keys")
            for entry in entries:
                try:
                    self._load_entry(directory, identity, entry)
                except (OSError, ValueError, KeyError, TypeError, wave.Error, EOFError):
                    logger.warning("TTS_STATIC_ASSET_INVALID")
            logger.info("TTS static catalog %s: %d verified assets", version, len(self._audio))
        except (OSError, ValueError, KeyError, TypeError):
            logger.warning("TTS_STATIC_MANIFEST_UNAVAILABLE")

    def _load_entry(self, directory: Path, identity: dict, entry: dict) -> None:
        text = entry["utterance"]
        if (
            not isinstance(text, str)
            or not text
            or len(text) >= 300
            or text != text.strip()
            or entry["listening_status"] != "PASS"
            or entry["audio_config"] != identity
            or entry["cache_key"] != cache_key(text, identity)
            or entry["text_sha256"] != digest(text.encode("utf-8"))
        ):
            raise ValueError("Unapproved or mismatched entry")
        name = entry["file"]
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+\.wav", name):
            raise ValueError("Invalid asset filename")
        path = (directory / name).resolve()
        if not path.is_relative_to(directory.resolve()):
            raise ValueError("Asset escapes catalog")
        raw = path.read_bytes()
        if digest(raw) != entry["audio_sha256"]:
            raise ValueError("Audio checksum mismatch")
        with wave.open(io.BytesIO(raw), "rb") as clip:
            if (
                clip.getnchannels(),
                clip.getsampwidth(),
                clip.getframerate(),
                clip.getcomptype(),
            ) != (1, 2, identity["sample_rate"], "NONE"):
                raise ValueError("Unsupported WAV")
            frames = clip.getnframes()
            pcm = clip.readframes(frames)
        if frames != entry["frame_count"] or not pcm or len(pcm) != frames * 2 or not any(pcm):
            raise ValueError("Truncated or empty WAV")
        self._audio[text] = AudioSegment(
            pcm=pcm,
            sample_rate=identity["sample_rate"],
            provider_actual=identity["provider"],
            voice=identity["voice"],
            cache_hit=True,
            cache_key=entry["cache_key"],
            catalog_version=self.catalog_version,
            billed_characters=0,
        )

    def lookup(self, text: str) -> AudioSegment | None:
        return self._audio.get(text)

    def __len__(self) -> int:
        return len(self._audio)


@lru_cache(maxsize=8)
def _shared_cache(directory: str, identity_json: bytes) -> StaticAudioCache:
    return StaticAudioCache(Path(directory), json.loads(identity_json))


def create_static_cache(
    gateway: TTSGateway, settings: StaticCacheSettings | None = None
) -> StaticAudioCache | None:
    settings = settings or StaticCacheSettings()
    if not settings.enabled or gateway.provider_name != "vbee":
        return None
    identity = getattr(gateway.provider, "audio_identity", None)
    if not isinstance(identity, dict):
        return None
    directory = Path(settings.directory)
    if not directory.is_absolute():
        directory = CONFIG_DIR.parent / directory
    return _shared_cache(str(directory.resolve()), canonical_json(identity))
