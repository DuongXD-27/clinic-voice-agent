"""Voice gateway MVP: mic -> VAD -> ZipFormer -> Core Agent (HTTP) -> TTS -> loa.

Thực hiện Phase 2-4 của temp/plan_mvp_zipformer.md. Không đụng `engine/` hay
`transports/` — gọi Core đúng 2 endpoint HTTP đang chạy (`POST /v1/calls`,
`POST /v1/calls/{id}/turn`, `mode="text"`), y hệt cách harness gọi.

Dùng `arecord`/`aplay` (ALSA CLI qua subprocess) thay vì `sounddevice`: máy dev đã
verify PortAudio (cả bản apt lẫn conda) không enumerate được thiết bị mic/loa thật
qua PipeWire trên máy này, trong khi `arecord`/`aplay` chạy tốt ngay lập tức.

Chuẩn bị:
    pip install -e ".[speech-zipformer]"   # sherpa-onnx, soundfile (arecord/aplay đã có sẵn qua alsa-utils)
    # Core Agent cần chạy trước (không cần cho --stt-only): docker compose up

Chạy chỉ để nghe thử STT (không cần Core/TTS, không cần Docker):
    python scripts/voice_gateway.py --stt-only

Chạy full loop (cần Core Agent + appointment_id hợp lệ):
    python scripts/voice_gateway.py --appointment-id apt_00417
"""

import argparse
import select
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Iterator, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import httpx  # noqa: E402

from callbot.speech.asr.zipformer import ZipFormerASR, default_paths  # noqa: E402
from callbot.speech.tts.base import TTSProvider  # noqa: E402
from callbot.speech.types import WIDEBAND_RATE, AudioSegment, Transcript  # noqa: E402
from callbot.speech.vad import EnergyFrameClassifier, StreamingVAD  # noqa: E402

FRAME_MS = 30
FRAME_BYTES = int(WIDEBAND_RATE * FRAME_MS / 1000) * 2  # PCM 16-bit mono
MIN_SPEECH_MS = 250  # đoạn ngắn hơn (tạp âm/blip mic) không đủ context cho ZipFormer


def _read_exact(stream, n: int) -> Optional[bytes]:
    """Đọc đúng n byte từ pipe subprocess; None nếu stream đóng giữa chừng (arecord thoát)."""
    buf = b""
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def _frame_generator(stream, frame_bytes: int = FRAME_BYTES) -> Iterator[bytes]:
    while True:
        frame = _read_exact(stream, frame_bytes)
        if frame is None:
            return
        yield frame


def drain_stale_audio(stream) -> None:
    """Xả bỏ audio đã tồn đọng trong pipe của arecord.

    arecord ghi liên tục kể cả khi không ai đọc (lúc code đang bận transcribe/gọi
    Core/TTS/phát loa — vài giây). Không xả trước khi nghe lượt tiếp theo thì đoạn
    đầu đọc được là audio cũ (tạp âm phòng, có thể lẫn tiếng loa dội ngược vào mic),
    không phải câu người dùng vừa nói — VAD/ASR sẽ ăn nhầm rác này.
    """
    while True:
        ready, _, _ = select.select([stream], [], [], 0)
        if not ready:
            return
        if not stream.read(4096):
            return


def start_mic(device: str) -> subprocess.Popen:
    """arecord streaming PCM 16-bit mono 16kHz thô ra stdout, sống suốt phiên."""
    return subprocess.Popen(
        [
            "arecord",
            "-D", device,
            "-f", "S16_LE",
            "-r", str(WIDEBAND_RATE),
            "-c", "1",
            "-t", "raw",
            "-q",
        ],
        stdout=subprocess.PIPE,
    )


def play_audio(segment: AudioSegment, device: str) -> None:
    if not segment.pcm:
        return
    subprocess.run(
        [
            "aplay",
            "-D", device,
            "-f", "S16_LE",
            "-r", str(segment.sample_rate),
            "-c", "1",
            "-t", "raw",
            "-q",
        ],
        input=segment.pcm,
        check=True,
    )


def capture_one_segment(vad: StreamingVAD, frames: Iterator[bytes]) -> Optional[AudioSegment]:
    """Chờ đến khi VAD phát speech_end, gom pcm các frame 'speech' thành một AudioSegment.

    Trả None nếu stream mic kết thúc (arecord thoát) trước khi bắt được tiếng nói.
    """
    chunks: list[bytes] = []
    for event in vad.process(frames):
        if event.kind == "speech":
            chunks.append(event.pcm)
        elif event.kind == "speech_end":
            if not chunks:
                continue
            segment = AudioSegment(pcm=b"".join(chunks), sample_rate=WIDEBAND_RATE)
            chunks = []
            if segment.duration_ms < MIN_SPEECH_MS:
                continue  # tạp âm/blip mic — bỏ qua, chờ đoạn nói thật tiếp theo
            return segment
    return None


class CoreClient:
    """Gọi đúng 2 endpoint HTTP hiện có của Core Agent — không sửa transports/."""

    def __init__(self, base_url: str, max_turns: int) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=10.0)
        self._max_turns = max_turns
        self.call_id = f"c_gw_{uuid.uuid4().hex[:8]}"
        self.turn = 0

    def start_call(self, appointment_id: str) -> dict:
        payload = {
            "call_id": self.call_id,
            "direction": "outbound",
            "appointment_id": appointment_id,
            "caller_number": None,
            "locale": "vi-VN",
            "mode": "text",
            "max_turns": self._max_turns,
        }
        r = self._client.post("/v1/calls", json=payload)
        r.raise_for_status()
        return r.json()

    def send_turn(self, text: str) -> dict:
        self.turn += 1
        payload = {"turn": self.turn, "audio_url": None, "text": text, "silence_ms": 0}
        r = self._client.post(f"/v1/calls/{self.call_id}/turn", json=payload)
        r.raise_for_status()
        return r.json()

    def close(self) -> None:
        self._client.close()


def speak(tts: Optional[TTSProvider], text: str, device: str) -> None:
    if tts is None or not text.strip():
        return
    segment = tts.synthesize(text)
    if segment is not None:
        play_audio(segment, device)


def run(args: argparse.Namespace) -> None:
    asr = ZipFormerASR(**default_paths())
    vad = StreamingVAD(EnergyFrameClassifier(args.vad_threshold), end_silence_ms=args.vad_silence_ms)

    tts: Optional[TTSProvider] = None
    if not args.stt_only:
        from callbot.speech.settings import SpeechSettings
        from callbot.speech.tts import create_tts

        tts = create_tts(SpeechSettings(tts_provider="openai"))

    core: Optional[CoreClient] = None
    if not args.stt_only:
        core = CoreClient(args.base_url, args.max_turns)
        started = core.start_call(args.appointment_id)
        print(f"[bot] {started['utterance']}")
        speak(tts, started["utterance"], args.output_device)
        if started["state"] == "ENDED":
            core.close()
            return

    mic = start_mic(args.input_device)
    frames = _frame_generator(mic.stdout)
    print("Sẵn sàng — nói vào mic (Ctrl+C để dừng)." if not args.stt_only else "STT-only — nói vào mic (Ctrl+C để dừng).")

    try:
        while True:
            drain_stale_audio(mic.stdout)
            segment = capture_one_segment(vad, frames)
            if segment is None:
                print("Mic đã dừng.")
                break

            transcript: Transcript = asr.transcribe(segment)
            if transcript.is_silence:
                continue
            print(f"[bạn] {transcript.text}")

            if args.stt_only:
                continue

            assert core is not None
            result = core.send_turn(transcript.text)
            print(f"[bot] {result['utterance']}")
            speak(tts, result["utterance"], args.output_device)
            if result["ended"]:
                print(f"Cuộc gọi kết thúc: {result['outcome']}")
                break
    except KeyboardInterrupt:
        print("\nDừng theo yêu cầu.")
    finally:
        mic.terminate()
        mic.wait(timeout=2)
        if core is not None:
            core.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stt-only", action="store_true", help="Chỉ chạy mic->VAD->ZipFormer, in transcript, không gọi Core/TTS.")
    parser.add_argument("--appointment-id", default=None, help="Bắt buộc trừ khi --stt-only. Vd. apt_00417.")
    parser.add_argument("--base-url", default="http://localhost:8002", help="Core Agent HTTP base URL (xem docker-compose.yml — 8002 trên host).")
    parser.add_argument("--max-turns", type=int, default=20)
    parser.add_argument("--input-device", default="default", help="Tên thiết bị ALSA cho arecord.")
    parser.add_argument("--output-device", default="default", help="Tên thiết bị ALSA cho aplay.")
    parser.add_argument("--vad-threshold", type=float, default=500.0, help="Ngưỡng RMS VAD — cần tinh chỉnh theo mic thật.")
    parser.add_argument("--vad-silence-ms", type=int, default=600)
    args = parser.parse_args()
    if not args.stt_only and not args.appointment_id:
        parser.error("--appointment-id bắt buộc trừ khi dùng --stt-only")
    return args


if __name__ == "__main__":
    run(parse_args())
