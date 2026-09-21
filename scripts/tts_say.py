"""TTS-1.1: sinh một câu bằng provider trong .env, ghi WAV 8 kHz, in số đo.

    python scripts/tts_say.py "Dạ em xin chào anh chị."
    python scripts/tts_say.py "..." --provider elevenlabs --voice EXAVITQu4vr4xnSDxMaL --out temp/tts/x.wav

`--provider` / `--voice` ghi đè TTS_PROVIDER và mã giọng của provider đó, không sửa .env.
"""

import argparse
import sys
import time
from pathlib import Path

from callbot.speech.audio.codec import encode_wav
from callbot.speech.settings import SpeechSettings
from callbot.speech.tts import create_tts
from callbot.speech.tts.base import TTSTiming
from callbot.speech.tts.errors import TTSError

_VOICE_FIELD = {"elevenlabs": "elevenlabs_voice_id"}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("text")
    parser.add_argument("--out", default="temp/tts/say.wav")
    parser.add_argument("--provider", choices=sorted(_VOICE_FIELD), default=None)
    parser.add_argument("--voice", default=None, help="ghi đè mã giọng của provider")
    args = parser.parse_args()

    settings = SpeechSettings()
    overrides: dict[str, object] = {}
    if args.provider:
        overrides["tts_provider"] = args.provider
    provider = args.provider or settings.tts_provider
    if args.voice:
        if provider not in _VOICE_FIELD:
            print(f"--voice không áp dụng cho provider {provider!r}", file=sys.stderr)
            return 2
        overrides[_VOICE_FIELD[provider]] = args.voice
    settings = settings.model_copy(update=overrides)

    try:
        tts = create_tts(settings)
        if hasattr(tts, "synthesize_timed"):
            segment, timing = tts.synthesize_timed(args.text)
        else:
            started = time.perf_counter()
            segment = tts.synthesize(args.text)
            timing = TTSTiming(
                chars=len(args.text), total_ms=int((time.perf_counter() - started) * 1000)
            )
    except ValueError as exc:
        print(f"Cấu hình: {exc}", file=sys.stderr)
        return 2
    except TTSError as exc:
        print(f"TTS lỗi [{exc.code}]: {exc}", file=sys.stderr)
        return 1
    if segment is None:
        print(f"provider {tts.name!r} không sinh audio", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(encode_wav(segment))
    voice = getattr(settings, _VOICE_FIELD.get(tts.name, ""), "")
    print(f"provider={tts.name} voice={voice} -> {out} ({segment.duration_ms} ms audio)")
    print("timing:", timing.to_trace())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
