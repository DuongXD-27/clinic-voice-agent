"""Phát lại một bản ghi LiveKit (LIVEKIT_DEBUG_DUMP_AUDIO) qua đúng STTPipeline, theo thời
gian thực, in mọi sự kiện: VAD, tín hiệu AsrSegmentEnd, partial/final ASR,
quyết định TurnValidator, turn gửi lên core. Dùng để tái hiện lỗi của một cuộc gọi thật.

Cấu hình lấy từ `.env` (biến môi trường đã đặt sẵn được ưu tiên), vd.:
    TURN_VALIDATOR_ENABLED=false .venv/bin/python eval/noise-bench/replay_dump.py <wav>

Bản ghi không có trạng thái bot nói; `--bot 19.35:on,28.75:off` giả lập bot bắt đầu/dừng
nói tại các mốc (giây trong file). `--offline` chỉ decode batch từng đoạn Silero, không qua
pipeline — xem người dùng thực sự nói gì so với lượt nói pipeline tạo ra.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)
for _line in (ROOT / ".env").read_text().splitlines():
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        _key, _value = _line.split("=", 1)
        os.environ.setdefault(_key.strip(), _value.strip().strip('"').strip("'"))

from inference.asr import create_asr_gateway  # noqa: E402
from speech.asr.recognizer import SpeechRecognizer  # noqa: E402
from speech.bundle import build_streaming_bundle  # noqa: E402
from speech.settings import SpeechSettings  # noqa: E402
from speech.turn.validator import TurnValidator  # noqa: E402
from speech.types import AudioSegment  # noqa: E402

RATE = 16_000
FRAME = RATE * 30 // 1000
_now = [0.0]  # giây audio của frame đang xử lý — đóng dấu cho mọi dòng in


def _stamp() -> str:
    return f"[t={_now[0]:6.2f}]"


class _AudioTime(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.t = f"{_now[0]:6.2f}"
        return True


def _spy_validator() -> None:
    original = TurnValidator.evaluate

    def evaluate(self, text, *, noise_evidence=None, stability=None):
        decision = original(self, text, noise_evidence=noise_evidence, stability=stability)
        snr = None if noise_evidence is None else round(noise_evidence.snr_db, 1)
        print(f"{_stamp()}   validator {text!r} snr={snr} {stability} -> {decision}")
        return decision

    TurnValidator.evaluate = evaluate


class _Tap:
    """Bọc recognizer: in tín hiệu AsrSegmentEnd và mọi TranscriptEvent, ghi chỉ số frame
    tới ASR để phát hiện frame trùng/đảo thứ tự."""

    def __init__(self, inner: SpeechRecognizer, index_of: dict[int, int]) -> None:
        self._inner = inner
        self.name = inner.name
        self.input_sample_rate = inner.input_sample_rate
        self._index_of = index_of
        self.fed: list[int] = []

    def transcribe(self, segment):
        return self._inner.transcribe(segment)

    async def stream(self, frames, **kwargs):
        async def tapped():
            async for item in frames:
                if isinstance(item, bytes):
                    self.fed.append(self._index_of.get(id(item), -1))
                else:
                    print(f"{_stamp()} ASR <- {item}")
                yield item

        async for event in self._inner.stream(tapped(), **kwargs):
            print(f"{_stamp()} ASR {'FINAL  ' if event.is_final else 'partial'} {event.text!r}")
            yield event


def offline(pcm: np.ndarray, settings: SpeechSettings, asr: SpeechRecognizer) -> None:
    from speech.asr.vad.silero import SileroVadClassifier

    classifier = SileroVadClassifier(settings.silero_vad_model_path, sample_rate=RATE)
    flags = [
        classifier.is_speech(pcm[i : i + FRAME].tobytes())
        for i in range(0, len(pcm) - FRAME + 1, FRAME)
    ]
    regions, start, gap = [], None, 0
    for index, is_speech in enumerate(flags):
        if is_speech:
            start = index if start is None else start
            gap = 0
        elif start is not None:
            gap += 1
            if gap * 30 >= 700:
                regions.append((start, index - gap + 1))
                start, gap = None, 0
    if start is not None:
        regions.append((start, len(flags)))
    for s, e in regions:
        a, b = max(0, (s - 10) * FRAME), min(len(pcm), (e + 10) * FRAME)
        text = asr.transcribe(AudioSegment(pcm=pcm[a:b].tobytes(), sample_rate=RATE)).text
        print(f"speech {s * 0.03:6.2f}-{e * 0.03:6.2f}s  offline: {text!r}")


async def replay(
    pcm: np.ndarray,
    settings: SpeechSettings,
    asr: SpeechRecognizer,
    bot_events: list[tuple[float, bool]],
) -> None:
    index_of: dict[int, int] = {}
    keep: list[bytes] = []  # giữ tham chiếu để id(frame) không bị tái sử dụng
    tap = _Tap(asr, index_of)
    bundle = build_streaming_bundle(settings, sample_rate=RATE, asr=tap, frame_ms=30)
    controller = bundle.turn_controller
    loop = asyncio.get_running_loop()
    started = loop.time()

    async def frames():
        for n, i in enumerate(range(0, len(pcm) - FRAME + 1, FRAME)):
            frame = pcm[i : i + FRAME].tobytes()
            keep.append(frame)
            index_of[id(frame)] = n
            _now[0] = n * 0.03
            for at, speaking in bot_events:
                if abs(_now[0] - at) < 0.015:
                    print(f"{_stamp()} --- bot_speaking={speaking}")
                    controller.on_bot_speaking_changed(speaking)
            yield frame
            await asyncio.sleep(max(0.0, started + (n + 1) * 0.03 - loop.time()))
        await asyncio.sleep(1.5)

    async for turn in bundle.stt_pipeline.stream(frames(), turn_controller=controller):
        print(f"{_stamp()} >>> TURN {turn.text!r}")

    fed = tap.fed
    duplicates = len(fed) - len(set(fed))
    out_of_order = sum(1 for a, b in zip(fed, fed[1:], strict=False) if b <= a)
    print(f"frame tới ASR: {len(fed)}; trùng={duplicates}; đảo thứ tự={out_of_order}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("wav")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--bot", default="", help="vd. 19.35:on,28.75:off")
    args = parser.parse_args()

    with wave.open(args.wav) as w:
        if w.getframerate() != RATE or w.getnchannels() != 1:
            raise SystemExit(f"cần WAV mono {RATE} Hz")
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    settings = SpeechSettings(vad_provider="silero")
    print(
        f"duration={len(pcm) / RATE:.2f}s vad={settings.vad_provider} "
        f"validator={settings.turn_validator_enabled}"
    )
    asr = SpeechRecognizer(create_asr_gateway(settings.asr_provider))
    if args.offline:
        offline(pcm, settings, asr)
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_AudioTime())
    handler.setFormatter(logging.Formatter("[t=%(t)s] %(name)s: %(message)s"))
    for name in ("speech.asr.pipeline", "speech.turn.controller"):
        logging.getLogger(name).setLevel(logging.DEBUG)
        logging.getLogger(name).addHandler(handler)
    _spy_validator()
    bot_events = [
        (float(at), state == "on")
        for at, state in (item.split(":") for item in args.bot.split(",") if item)
    ]
    asyncio.run(replay(pcm, settings, asr, bot_events))


if __name__ == "__main__":
    main()
