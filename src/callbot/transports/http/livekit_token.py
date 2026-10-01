"""Sinh access token cho browser connect LiveKit — chỉ transport, không chạy Agent Worker
logic trong process FastAPI này (worker chạy riêng, xem transports/livekit/worker.py)."""

import re
import uuid
from datetime import timedelta
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator, model_validator

from callbot.transports.livekit.settings import LiveKitSettings

router = APIRouter(prefix="/livekit", tags=["livekit"])

_PHONE_RE = re.compile(r"^[0-9+][0-9 .-]{5,20}$")
_APPOINTMENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class LiveKitTokenRequest(BaseModel):
    # room_name rỗng -> server tự sinh; CallBridge dùng room.name làm call_id thẳng.
    room_name: str = ""
    # Demo web không có caller ID/PBX dial-out thật (khác PSTN) — cho phép người test tự
    # khai direction + caller_number (inbound) hoặc appointment_id (outbound) để đi qua
    # đúng nhánh nghiệp vụ tương ứng, gắn vào token qua participant attribute mà
    # worker.py đọc lại khi participant join. inbound KHÔNG bắt buộc caller_number —
    # để trống là một kịch bản hợp lệ (caller không xác định được -> policy engine
    # chuyển máy ngay lượt đầu, xem policy_engine.py: LOOKUP_TRANSFER_REASON).
    direction: Literal["inbound", "outbound"] = "inbound"
    caller_number: Optional[str] = None
    appointment_id: Optional[str] = None

    @field_validator("caller_number")
    @classmethod
    def _validate_caller_number(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if not _PHONE_RE.match(value):
            raise ValueError("caller_number không hợp lệ")
        return value

    @field_validator("appointment_id")
    @classmethod
    def _validate_appointment_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if not _APPOINTMENT_ID_RE.match(value):
            raise ValueError("appointment_id không hợp lệ")
        return value

    @model_validator(mode="after")
    def _check_direction_fields(self) -> "LiveKitTokenRequest":
        # Cùng nguyên tắc StartCallRequest (transports/http/schemas.py) — outbound gắn
        # với một lịch hẹn cụ thể, inbound định danh qua số gọi đến; không trộn cả hai.
        if self.direction == "outbound":
            if not self.appointment_id:
                raise ValueError("outbound yêu cầu appointment_id")
            if self.caller_number:
                raise ValueError("outbound không được có caller_number")
        elif self.appointment_id is not None:
            raise ValueError("inbound không được có appointment_id")
        return self


class LiveKitTokenResponse(BaseModel):
    url: str
    room_name: str
    token: str
    identity: str


def get_livekit_settings(request: Request) -> LiveKitSettings:
    return request.app.state.livekit_settings


@router.post("/token", response_model=LiveKitTokenResponse)
def create_token(payload: LiveKitTokenRequest, request: Request) -> LiveKitTokenResponse:
    settings = get_livekit_settings(request)
    if not (settings.livekit_url and settings.livekit_api_key and settings.livekit_api_secret):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "LIVEKIT_NOT_CONFIGURED",
                "message": "LIVEKIT_URL/LIVEKIT_API_KEY/LIVEKIT_API_SECRET chưa cấu hình",
            },
        )

    # Import trễ, sau khi đã xác nhận có cấu hình — package `livekit` (extra [livekit])
    # không phải dependency bắt buộc của mọi môi trường (vd. CI mặc định chỉ cài
    # [dev,speech]). Có cấu hình mà chưa cài package cũng phải trả 503 có mã lỗi rõ ràng,
    # không để ModuleNotFoundError thành 500 "Internal Server Error" dạng text.
    try:
        from livekit import api
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "LIVEKIT_UNAVAILABLE",
                "message": 'Server chưa cài thư viện LiveKit (pip install -e ".[livekit]")',
            },
        ) from exc

    room_name = payload.room_name or f"{settings.room_name_prefix}{uuid.uuid4()}"
    identity = f"web-{uuid.uuid4()}"

    builder = (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(identity)
        .with_ttl(timedelta(seconds=settings.token_ttl_s))
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=False,
                # Trình duyệt gửi attribute `audio.settings` (cờ AEC/NS/AGC trình duyệt thật sự
                # áp dụng) để worker log đo đầu vào. Không mở thêm quyền gì đáng kể: các attribute
                # khác (direction, caller_number...) người test vốn đã tự khai khi xin token.
                can_update_own_metadata=True,
            )
        )
    )
    attributes = {"direction": payload.direction}
    if payload.caller_number:
        attributes["caller_number"] = payload.caller_number
    if payload.appointment_id:
        attributes["appointment_id"] = payload.appointment_id
    builder = builder.with_attributes(attributes)
    if settings.agent_name:
        # Room tạo khi browser join bằng token này sẽ gọi đúng worker mang tên đó, thay cho
        # automatic dispatch tới bất kỳ worker nào trong project (xem LiveKitSettings.agent_name).
        builder = builder.with_room_config(
            api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=settings.agent_name)])
        )
    token = builder.to_jwt()

    return LiveKitTokenResponse(
        url=settings.livekit_url, room_name=room_name, token=token, identity=identity
    )
