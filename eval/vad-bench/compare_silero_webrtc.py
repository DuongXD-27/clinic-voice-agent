"""So sánh WebRtcVadClassifier vs SileroVadClassifier trên audio thật — chạy tay, KHÔNG
tự động đổi VAD_PROVIDER (xem docs/reference/livekit-architecture.md §5.4). In số lần
speech_start/speech_end mỗi VAD trigger qua StreamingVAD trên cùng file WAV, để đánh giá
tỷ lệ false-positive trên noise thật trước khi quyết định có chuyển default hay không.

Dùng:
    PYTHONPATH=src .venv/bin/python eval/vad-bench/compare_silero_webrtc.py <file.wav> [file2.wav ...]

Không có file nào truyền vào: mặc định quét toàn bộ `temp/audio/livekit_debug_*.wav` nếu có.
"""

from __future__ import annotations

import sys
import wave
from pathlib import Path

from speech.asr.vad.silero import SileroVadClassifier
from speech.asr.vad.streaming import StreamingVAD, split_frames
from speech.asr.vad.webrtc import WebRtcVadClassifier

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SILERO_MODEL = _REPO_ROOT / "src/speech/asr/vad/assets/silero_vad.onnx"


def _count_events(pcm: bytes, rate: int, classifier) -> tuple[int, int]:
    vad = StreamingVAD(classifier, end_silence_ms=600)
    starts = ends = 0
    for event in vad.process(split_frames(pcm, rate)):
        if event.kind == "speech_start":
            starts += 1
        elif event.kind == "speech_end":
            ends += 1
    return starts, ends


def _run_one(path: Path) -> None:
    with wave.open(str(path), "rb") as w:
        pcm = w.readframes(w.getnframes())
        rate = w.getframerate()
        duration_s = w.getnframes() / rate

    webrtc = WebRtcVadClassifier(aggressiveness=2, sample_rate=rate)
    w_starts, w_ends = _count_events(pcm, rate, webrtc)

    silero = SileroVadClassifier(str(_SILERO_MODEL), sample_rate=rate)
    s_starts, s_ends = _count_events(pcm, rate, silero)

    print(f"{path.name}  ({duration_s:.1f}s)")
    print(f"  WebRTC (aggr=2): speech_start={w_starts:3d}  speech_end={w_ends:3d}")
    print(f"  Silero          : speech_start={s_starts:3d}  speech_end={s_ends:3d}")
    print()


def main() -> None:
    if not _SILERO_MODEL.exists():
        print(f"BLOCKED: model asset thiếu — tải {_SILERO_MODEL} (xem silero_vad_model_path trong config/speech.yaml)")
        sys.exit(1)

    paths = [Path(p) for p in sys.argv[1:]]
    if not paths:
        paths = sorted((_REPO_ROOT / "temp/audio").glob("livekit_debug_*.wav"))
    if not paths:
        print("Không có file .wav nào để so sánh — truyền path hoặc để sẵn "
              "temp/audio/livekit_debug_*.wav (bật LIVEKIT_DEBUG_DUMP_AUDIO=1 khi test LiveKit).")
        sys.exit(1)

    for path in paths:
        _run_one(path)


if __name__ == "__main__":
    main()
