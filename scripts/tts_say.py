"""TTS-1.1: sinh một câu bằng provider trong .env (hoặc --provider), ghi WAV 8 kHz, in số đo.

    python scripts/tts_say.py "Dạ em xin chào anh chị."
    python scripts/tts_say.py "..." --provider elevenlabs --voice EXAVITQu4vr4xnSDxMaL --out temp/tts/x.wav

`--provider` / `--voice` ghi đè TTS_PROVIDER và mã giọng của provider đó, không sửa .env. Chỉ
`elevenlabs` có `synthesize_timed`/`stream` (đo TTFA); `openai` chỉ trả PCM một lần, không streaming.
"""

import argparse
import sys
import time
from pathlib import Path

from inference.tts.config import ElevenLabsTTSConfig, OpenAITTSConfig
from inference.tts.providers.elevenlabs import ElevenLabsTTS
from inference.tts.providers.openai import OpenAITTS
from speech.audio.codec import encode_wav
from speech.settings import SpeechSettings
from speech.types import AudioSegment

_VOICE_FIELD = {"elevenlabs": "voice_id", "openai": "voice"}
_PROVIDER_TYPE = {
    "elevenlabs": (ElevenLabsTTSConfig, ElevenLabsTTS),
    "openai": (OpenAITTSConfig, OpenAITTS),
}


def _timing_trace(chars: int, total_ms: int) -> dict:
    return {"chars": chars, "total_ms": total_ms}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("text")
    parser.add_argument("--out", default="temp/tts/say.wav")
    parser.add_argument("--provider", choices=sorted(_VOICE_FIELD), default=None)
    parser.add_argument("--voice", default=None, help="ghi đè mã giọng của provider")
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
        if hasattr(provider_obj, "synthesize_timed"):
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
