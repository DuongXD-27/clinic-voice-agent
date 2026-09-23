"""Tiện ích cho trang demo thủ công của đường HTTP chấm điểm.

Harness thật tự host clip và chỉ gửi ``audio_url``. Trình duyệt thì chỉ tạo được
``blob:`` URL cục bộ, backend không thể tải URL đó, nên trang demo cần upload WAV
vào một thư mục public trước khi gọi endpoint ``turn``. Module này chỉ làm nhiệm
vụ transport; audio và logic demo không đi vào business core.

``POST /demo-api/clinic-reset`` là nút reset clinic mock cho người test thủ công: mock
không bật CORS nên trình duyệt không gọi thẳng ``/_harness/reset`` được, và API key chỉ
nằm ở server. Engine (``ClinicMockClient``) vẫn không bao giờ gọi ``/_harness/*`` (§4.2.4).
"""

import asyncio
import logging
import re
import struct
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from callbot.transports.http.config import settings
from speech.audio.codec import decode_wav, encode_wav
from speech.types import NARROWBAND_RATE

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo-api", tags=["demo"])

_SAFE_CALL_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MAX_WAV_BYTES = 8 * 1024 * 1024
# Test thay bằng httpx.MockTransport; None = mạng thật
_clinic_transport: Optional[httpx.AsyncBaseTransport] = None


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


class ClinicResetRequest(BaseModel):
    # Lịch đọc lại sau reset để trang demo báo trạng thái — mặc định lịch outbound mẫu của mock
    appointment_id: str = Field(default="apt_00417", pattern=r"^[A-Za-z0-9_-]{1,128}$")


def _harness_origin(base_url: str) -> str:
    """CLINIC_MOCK_BASE_URL trỏ tới ``.../v1``; ``/_harness/*`` nằm ở gốc domain."""
    return base_url.rstrip("/").removesuffix("/v1")


@router.post("/clinic-reset")
async def reset_clinic_mock(body: Optional[ClinicResetRequest] = None) -> dict[str, Any]:
    """Reset clinic mock dùng chung (xóa dữ liệu của MỌI người test) rồi đọc lại một lịch hẹn."""
    if not settings.demo_clinic_reset_enabled:
        raise _error(404, "RESET_DISABLED", "Nút reset đã tắt (DEMO_CLINIC_RESET_ENABLED=false)")
    if settings.clinic_backend != "mock":
        raise _error(
            409, "RESET_UNAVAILABLE", "CLINIC_BACKEND=sim: restart server để nạp lại dữ liệu"
        )
    appointment_id = (body or ClinicResetRequest()).appointment_id
    base = settings.clinic_mock_base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.clinic_mock_api_key}"}

    async with httpx.AsyncClient(
        headers=headers, timeout=httpx.Timeout(10.0, connect=3.0), transport=_clinic_transport
    ) as client:
        try:
            reset = await client.post(f"{_harness_origin(base)}/_harness/reset")
        except httpx.HTTPError as exc:
            logger.error("Không gọi được /_harness/reset (%s)", type(exc).__name__)
            raise _error(502, "CLINIC_UNREACHABLE", "Không kết nối được clinic mock") from exc
        if reset.status_code >= 400:
            code = _mock_error_code(reset)
            raise _error(502, "RESET_FAILED", f"Clinic mock trả HTTP {reset.status_code} ({code})")

        # Reset đã xong; đọc lại chỉ để hiển thị, lỗi ở bước này không làm hỏng kết quả reset
        appointment = None
        try:
            read = await client.get(f"{base}/appointments/{appointment_id}")
            if read.status_code == 200:
                data = read.json()
                appointment = {
                    "appointment_id": data.get("appointment_id"),
                    "status": data.get("status"),
                    "version": data.get("version"),
                }
        except (httpx.HTTPError, ValueError):
            logger.warning("Reset xong nhưng không đọc lại được %s", appointment_id)
    return {"reset": True, "appointment": appointment}


def _mock_error_code(response: httpx.Response) -> str:
    try:
        return str(response.json()["error"]["code"])
    except (ValueError, KeyError, TypeError):
        return "UNKNOWN"
