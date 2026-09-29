"""Smoke test đường chấm `mode=audio` giống harness: mỗi lượt đo response + tải `audio_url` (≤ 8 s, §4.1.2).

    python scripts/audio_smoke.py                                    # prod, key đầu tiên trong BOT_API_KEYS của .env
    python scripts/audio_smoke.py --base-url http://localhost:8000 --api-key sk_...
    python scripts/audio_smoke.py --say "Alo, tôi nghe đây." --say "Tôi tên là Nguyễn Văn An."

Chế độ audio không nhận `text` (422 TEXT_NOT_ALLOWED), nên lời người gọi được sinh bằng TTS của máy
chạy script (provider trong .env), upload qua `PUT /demo-api/audio/...` rồi gửi `audio_url` như harness.
Kiểm thêm: WAV của bot là PCM16 mono 8 kHz; cuộc gọi `mode=text` trả `audio_url = null`.

Mở phiên outbound thật trên Clinic mock mà server đang trỏ tới (mặc định `apt_00417`, lịch mẫu của
trang demo): lượt nào dẫn tới chuyển máy / ghi kết quả thì mock ghi thật như khi test tay trên /demo.
Exit 1 nếu có lượt lỗi, thiếu `audio_url`, WAV sai định dạng hoặc tổng ≥ 8 s.
"""

import argparse
import io
import sys
import time
import wave
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import dotenv_values

from inference.tts.gateway import create_tts_gateway
from speech.audio.codec import encode_wav
from speech.settings import SpeechSettings
from speech.types import AudioSegment

ROOT = Path(__file__).resolve().parents[1]
TURN_BUDGET_S = 8.0
DEFAULT_LINES = ["Alo, tôi nghe đây.", "Anh chị nói lại giúp tôi được không?", "Vâng, tôi nghe rồi."]


def _default_api_key() -> str:
    keys = dotenv_values(ROOT / ".env").get("BOT_API_KEYS") or ""
    return keys.split(",")[0].strip()


def _check_wav(data: bytes) -> str:
    try:
        with wave.open(io.BytesIO(data)) as wav:
            rate, channels, width = wav.getframerate(), wav.getnchannels(), wav.getsampwidth()
            seconds = wav.getnframes() / rate
    except (wave.Error, EOFError) as exc:
        return f"WAV hỏng ({exc})"
    if (rate, channels, width) != (8000, 1, 2):
        return f"sai định dạng {rate} Hz / {channels} kênh / {width * 8} bit"
    return f"ok {seconds:.1f}s"


def _fetch_audio(audio_url: str | None) -> tuple[float, str]:
    """Tải `audio_url` bằng client riêng, không kèm key, như harness. Trả (giây tải, kết quả kiểm WAV)."""
    if not audio_url:
        return 0.0, "THIẾU audio_url"
    started = time.perf_counter()
    response = httpx.get(audio_url, timeout=30.0)
    elapsed = time.perf_counter() - started
    if response.status_code != 200:
        return elapsed, f"tải lỗi HTTP {response.status_code}"
    return elapsed, _check_wav(response.content)


def _caller_clips(lines: list[str]) -> list[bytes]:
    settings = SpeechSettings()
    gateway = create_tts_gateway(settings.tts_provider, fallback=settings.tts_fallback_provider)
    clips = []
    for line in lines:
        result = gateway.synthesize(line)
        if result is None:
            raise RuntimeError(f"TTS local không sinh được câu người gọi: {line!r}")
        clips.append(encode_wav(AudioSegment(result.pcm, result.sample_rate)))
    return clips


def _start_body(call_id: str, appointment_id: str, mode: str, max_turns: int) -> dict:
    return {
        "call_id": call_id,
        "direction": "outbound",
        "appointment_id": appointment_id,
        "caller_number": None,
        "locale": "vi-VN",
        "mode": mode,
        "max_turns": max_turns,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url", default="https://vmec-callbot.tech")
    parser.add_argument("--api-key", default=None, help="mặc định: key đầu tiên của BOT_API_KEYS trong .env")
    parser.add_argument("--appointment", default="apt_00417")
    parser.add_argument("--say", action="append", default=None, help="một câu người gọi (lặp lại cho nhiều lượt)")
    parser.add_argument("--skip-text-check", action="store_true", help="bỏ bước kiểm mode=text")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    api_key = args.api_key or _default_api_key()
    lines = args.say or DEFAULT_LINES
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    stamp = datetime.now().strftime("%m%d%H%M%S")
    call_id = f"smoke-audio-{stamp}"

    print(f"Sinh {len(lines)} câu người gọi bằng TTS local...")
    clips = _caller_clips(lines)

    rows: list[tuple[str, float, float, str, str]] = []
    failed = False
    with httpx.Client(base_url=base_url, headers=headers, timeout=30.0) as client:
        started = time.perf_counter()
        response = client.post("/v1/calls", json=_start_body(call_id, args.appointment, "audio", len(lines) + 2))
        request_s = time.perf_counter() - started
        if response.status_code != 200:
            print(f"POST /v1/calls lỗi HTTP {response.status_code}: {response.text}", file=sys.stderr)
            return 1
        body = response.json()
        download_s, wav_check = _fetch_audio(body["audio_url"])
        rows.append(("mở phiên", request_s, download_s, wav_check, body["utterance"]))

        for turn, clip in enumerate(clips, start=1):
            upload = client.put(
                f"/demo-api/audio/{call_id}/{turn}.wav", content=clip, headers={"Content-Type": "audio/wav"}
            )
            if upload.status_code != 200:
                print(f"upload lượt {turn} lỗi HTTP {upload.status_code}: {upload.text}", file=sys.stderr)
                failed = True
                break
            payload = {"turn": turn, "audio_url": upload.json()["audio_url"], "text": None, "silence_ms": 0}
            started = time.perf_counter()
            response = client.post(f"/v1/calls/{call_id}/turn", json=payload)
            request_s = time.perf_counter() - started
            if response.status_code != 200:
                print(f"lượt {turn} lỗi HTTP {response.status_code}: {response.text}", file=sys.stderr)
                failed = True
                break
            body = response.json()
            download_s, wav_check = _fetch_audio(body["audio_url"])
            rows.append((f"lượt {turn}", request_s, download_s, wav_check, body["utterance"]))
            if body["ended"]:
                print(f"Cuộc gọi kết thúc ở lượt {turn} (outcome={body['outcome']}).")
                break

        text_check = "bỏ qua"
        if not args.skip_text_check:
            response = client.post(
                "/v1/calls", json=_start_body(f"smoke-text-{stamp}", args.appointment, "text", 3)
            )
            if response.status_code != 200:
                text_check = f"lỗi HTTP {response.status_code}"
            elif response.json()["audio_url"] is None:
                text_check = "ok (audio_url = null)"
            else:
                text_check = f"SAI: audio_url = {response.json()['audio_url']}"

    print(f"\ncall_id: {call_id}  ·  {base_url}\n")
    print("| Lượt | Response (s) | Tải audio (s) | Tổng (s) | WAV | Bot nói |")
    print("|---|---|---|---|---|---|")
    for label, request_s, download_s, wav_check, utterance in rows:
        total = request_s + download_s
        over = total >= TURN_BUDGET_S
        bad_wav = not wav_check.startswith("ok")
        failed = failed or over or bad_wav
        flag = " ⚠" if over else ""
        print(f"| {label} | {request_s:.2f} | {download_s:.2f} | {total:.2f}{flag} | {wav_check} | {utterance} |")
    totals = [r[1] + r[2] for r in rows]
    if totals:
        print(f"\nTổng lớn nhất: {max(totals):.2f}s (trần {TURN_BUDGET_S:.0f}s)")
    print(f"mode=text: {text_check}")
    if not text_check.startswith(("ok", "bỏ qua")):
        failed = True
    print("KẾT QUẢ:", "FAIL" if failed else "PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
