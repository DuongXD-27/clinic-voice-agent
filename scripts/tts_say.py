"""TTS-1.1: sinh một câu bằng provider trong .env (hoặc --provider), ghi WAV 8 kHz, in số đo.

    python scripts/tts_say.py "Dạ em xin chào anh chị."
    python scripts/tts_say.py "..." --provider elevenlabs --voice EXAVITQu4vr4xnSDxMaL --out temp/tts/x.wav

`--provider` / `--voice` ghi đè TTS_PROVIDER và mã giọng của provider đó, không sửa .env. Chỉ
`elevenlabs` có `synthesize_timed`/`stream` (đo TTFA); `openai`/`vbee` chỉ đo tổng thời gian.

`--stream` chạy `synthesize_stream` (đường LiveKit) và in thời điểm từng chunk về, để thấy chunk
đầu tới trước khi provider sinh xong cả câu:

    python scripts/tts_say.py "Dạ em xin chào anh chị." --stream
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

from inference.tts.base import TTSResult
from inference.tts.config import ElevenLabsTTSConfig, OpenAITTSConfig, VbeeTTSConfig
from inference.tts.providers.elevenlabs import ElevenLabsTTS
from inference.tts.providers.openai import OpenAITTS
from inference.tts.providers.vbee import VbeeTTS
from speech.audio.codec import encode_wav
from speech.settings import SpeechSettings
from speech.types import AudioSegment

_VOICE_FIELD = {"elevenlabs": "voice_id", "openai": "voice", "vbee": "voice_code"}
_PROVIDER_TYPE = {
    "elevenlabs": (ElevenLabsTTSConfig, ElevenLabsTTS),
    "openai": (OpenAITTSConfig, OpenAITTS),
    "vbee": (VbeeTTSConfig, VbeeTTS),
}


def _timing_trace(chars: int, total_ms: int) -> dict:
    return {"chars": chars, "total_ms": total_ms}


async def _stream(provider_obj, text: str) -> tuple[TTSResult, dict]:
    """Đọc `synthesize_stream`, in thời điểm (ms từ lúc gửi) và cỡ từng chunk khi nó về."""
    started = time.perf_counter()
    pcm = bytearray()
    first_ms = None
    chunks = 0
    try:
        async for chunk in provider_obj.synthesize_stream(text):
            elapsed = int((time.perf_counter() - started) * 1000)
            first_ms = elapsed if first_ms is None else first_ms
            chunks += 1
            pcm.extend(chunk)
            print(f"  chunk {chunks:>3}: {elapsed:>5} ms  {len(chunk):>6} B")
    finally:
        aclose = getattr(provider_obj, "aclose", None)
        if aclose is not None:
            await aclose()
    total_ms = int((time.perf_counter() - started) * 1000)
    timing = {
        "chars": len(text),
        "chunks": chunks,
        "first_chunk_ms": first_ms,
        "total_ms": total_ms,
    }
    return TTSResult(pcm=bytes(pcm), sample_rate=provider_obj.stream_sample_rate), timing


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("text")
    parser.add_argument("--out", default="temp/tts/say.wav")
    parser.add_argument("--provider", choices=sorted(_VOICE_FIELD), default=None)
    parser.add_argument("--voice", default=None, help="ghi đè mã giọng của provider")
    parser.add_argument(
        "--stream", action="store_true", help="chạy synthesize_stream, in thời điểm từng chunk"
    )
    args = parser.parse_args()

    provider = args.provider or SpeechSettings().tts_provider
    if provider not in _VOICE_FIELD:
        print(f"provider không hỗ trợ: {provider!r}", file=sys.stderr)
        return 2
    overrides = {_VOICE_FIELD[provider]: args.voice} if args.voice else {}
    config_type, provider_type = _PROVIDER_TYPE[provider]
    config = config_type(**overrides)

    try:
        provider_obj = provider_type(config)
        if args.stream:
            if not hasattr(provider_obj, "synthesize_stream"):
                print(f"provider {provider!r} không có synthesize_stream", file=sys.stderr)
                return 2
            result, timing = asyncio.run(_stream(provider_obj, args.text))
        elif hasattr(provider_obj, "synthesize_timed"):
            result, timing_obj = provider_obj.synthesize_timed(args.text)
            timing = timing_obj.to_trace()
        else:
            started = time.perf_counter()
            result = provider_obj.synthesize(args.text)
            timing = _timing_trace(len(args.text), int((time.perf_counter() - started) * 1000))
    except ValueError as exc:
        print(f"Cấu hình: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — CLI chẩn đoán: in mọi lỗi provider, không phân loại
        print(f"TTS lỗi [{type(exc).__name__}]: {exc}", file=sys.stderr)
        return 1
    if result is None:
        print(f"provider {provider!r} không sinh audio", file=sys.stderr)
        return 1

    segment = AudioSegment(pcm=result.pcm, sample_rate=result.sample_rate)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(encode_wav(segment))
    voice = getattr(config, _VOICE_FIELD[provider], "")
    print(f"provider={provider} voice={voice} -> {out} ({segment.duration_ms} ms audio)")
    print("timing:", timing)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
