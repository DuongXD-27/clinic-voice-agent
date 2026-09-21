"""Tiện ích cho trang demo thủ công của đường HTTP chấm điểm.

Harness thật tự host clip và chỉ gửi ``audio_url``. Trình duyệt thì chỉ tạo được
``blob:`` URL cục bộ, backend không thể tải URL đó, nên trang demo cần upload WAV
vào một thư mục public trước khi gọi endpoint ``turn``. Module này chỉ làm nhiệm
vụ transport; audio và logic demo không đi vào business core.
"""

import asyncio
import re
import struct
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from callbot.speech.audio.codec import decode_wav, encode_wav
from callbot.speech.types import NARROWBAND_RATE

router = APIRouter(prefix="/demo-api", tags=["demo"])

_SAFE_CALL_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MAX_WAV_BYTES = 8 * 1024 * 1024


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


@router.put("/audio/{call_id}/{turn}.wav")
async def upload_demo_audio(call_id: str, turn: int, request: Request) -> dict[str, object]:
    """Nhận WAV từ browser và trả URL mà ``POST .../turn`` có thể tải lại.

    File được chuẩn hóa về PCM16 mono 8 kHz, giống audio đi qua đường điện thoại.
    Giới hạn nhỏ và call_id allow-list tránh biến route demo thành nơi upload tùy ý.
    """
    if not _SAFE_CALL_ID.fullmatch(call_id):
        raise _error(422, "INVALID_CALL_ID", "call_id chỉ được chứa chữ, số, _ và -")
    if turn < 1:
        raise _error(422, "INVALID_TURN", "turn phải lớn hơn hoặc bằng 1")

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > _MAX_WAV_BYTES:
                raise _error(413, "AUDIO_TOO_LARGE", "WAV vượt quá giới hạn 8 MiB")
        except ValueError as exc:
            raise _error(400, "INVALID_CONTENT_LENGTH", "Content-Length không hợp lệ") from exc

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > _MAX_WAV_BYTES:
            raise _error(413, "AUDIO_TOO_LARGE", "WAV vượt quá giới hạn 8 MiB")
    if not body:
        raise _error(400, "EMPTY_AUDIO", "Không nhận được dữ liệu WAV")

    try:
        segment = decode_wav(bytes(body), target_rate=NARROWBAND_RATE)
    except (ValueError, TypeError, EOFError, struct.error) as exc:
        raise _error(422, "INVALID_WAV", "Chỉ chấp nhận WAV PCM16, G.711 A-law hoặc μ-law") from exc

    relative_path = Path("demo-input") / call_id / f"{turn}.wav"
    audio_root = Path(request.app.state.speech.audio_store.directory)
    output_path = audio_root / relative_path
    await asyncio.to_thread(output_path.parent.mkdir, parents=True, exist_ok=True)
    wav = encode_wav(segment)
    await asyncio.to_thread(output_path.write_bytes, wav)

    duration_ms = round(len(segment.pcm) / 2 / segment.sample_rate * 1000)
    audio_url = str(request.url_for("audio", path=relative_path.as_posix()))
    return {
        "audio_url": audio_url,
        "content_type": "audio/wav",
        "sample_rate": segment.sample_rate,
        "duration_ms": duration_ms,
        "size_bytes": len(wav),
    }
