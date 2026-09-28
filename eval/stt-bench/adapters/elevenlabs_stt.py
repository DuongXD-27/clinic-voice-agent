"""Adapter cho ElevenLabs Speech-to-Text (scribe_v2) — dùng để so sánh model local
(ZipFormer/gipformer1.5) với một STT thương mại nổi tiếng, trên cùng bộ 40 golden case,
qua cùng evaluate.py. Đọc key/model từ .env production (ELEVENLABS_API_KEY,
ELEVENLABS_STT_MODEL, ELEVENLABS_STT_LANGUAGE_CODE) — không tạo config riêng.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from adapters.base import STTResult
from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs

load_dotenv()


class ElevenLabsSTTAdapter:
    name = "elevenlabs-scribe_v2"

    def __init__(self) -> None:
        api_key = os.environ["ELEVENLABS_API_KEY"]
        self._model_id = os.environ.get("ELEVENLABS_STT_MODEL", "scribe_v2")
        self._language_code = os.environ.get("ELEVENLABS_STT_LANGUAGE_CODE") or None
        self._client = ElevenLabs(api_key=api_key)

    def transcribe(self, audio_path: Path) -> STTResult:
        start = time.monotonic()
        with open(audio_path, "rb") as f:
            response = self._client.speech_to_text.convert(
                model_id=self._model_id,
                file=f,
                language_code=self._language_code,
            )
        latency_ms = (time.monotonic() - start) * 1000
        return STTResult(text=response.text or "", latency_ms=latency_ms)


adapter = ElevenLabsSTTAdapter
