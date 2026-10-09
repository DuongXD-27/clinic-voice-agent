"""Check Gemini live STT setup using env/config; sends no microphone or WAV audio.

Run: PYTHONPATH=src python eval/streaming-bench/check_connection.py
"""

import asyncio

from inference.asr.config import GeminiLiveASRConfig
from inference.asr.providers.gemini_live import GeminiLiveASR


async def main() -> None:
    provider = GeminiLiveASR(GeminiLiveASRConfig())
    try:
        await provider.check_connection()
    except Exception as exc:
        # Transport exception strings may contain request metadata. Only display
        # our sanitized errors; never print the API key or upstream message.
        if isinstance(exc, RuntimeError):
            print(str(exc))
        else:
            print(f"Gemini Live setup failed ({type(exc).__name__})")
        raise SystemExit(1) from None
    print(
        f"Gemini Live setup OK: {provider.model}; vi-VN; VERBATIM; manual activity; no audio sent"
    )


if __name__ == "__main__":
    asyncio.run(main())
