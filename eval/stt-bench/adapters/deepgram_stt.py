"""Adapter cho Deepgram Speech-to-Text (REST /v1/listen) — so sánh model local
(ZipFormer/gipformer1.5) với một STT thương mại khác, trên cùng bộ 40 golden case.
Dùng REST trực tiếp qua httpx (SDK `deepgram-sdk` chưa có trong dependency, và REST
đủ đơn giản cho batch transcribe) thay vì thêm phụ thuộc mới chỉ để benchmark.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import httpx
from adapters.base import STTResult
from dotenv import load_dotenv

load_dotenv()

_ENDPOINT = "https://api.deepgram.com/v1/listen"


class DeepgramSTTAdapter:
    name = "deepgram-nova-3"

    def __init__(self, model: str = "nova-3") -> None:
        self._api_key = os.environ["DEEPGRAM_SECRET_KEY"]
        self._model = model
        self._client = httpx.Client(timeout=30)

    def transcribe(self, audio_path: Path) -> STTResult:
        with open(audio_path, "rb") as f:
            audio = f.read()
        start = time.monotonic()
        resp = self._client.post(
            _ENDPOINT,
            params={
                "model": self._model,
                "language": "vi",
                "encoding": "linear16",
                "sample_rate": "8000",
                "smart_format": "true",
            },
            headers={
                "Authorization": f"Token {self._api_key}",
                "Content-Type": "audio/wav",
            },
            content=audio,
        )
        latency_ms = (time.monotonic() - start) * 1000
        resp.raise_for_status()
        data = resp.json()
        transcript = data["results"]["channels"][0]["alternatives"][0]["transcript"]
        return STTResult(text=transcript, latency_ms=latency_ms)


adapter = DeepgramSTTAdapter
