from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LiveKitSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    # Tiền tố room cho web call — CallBridge dùng room.name làm call_id thẳng.
    room_name_prefix: str = "web-"
    # Kích thước token cho browser — đủ để connect + publish mic + subscribe TTS.
    token_ttl_s: int = 3600
    # WebRTC giữ wideband 16 kHz tới boundary ZipFormer. Đường phone sau này vẫn có
    # thể đưa 8 kHz vào cùng provider vì ZipFormerASR.stream nhận sample rate tường minh.
    input_sample_rate: Literal[8_000, 16_000] = 16_000
    # Một frame canonical cho VAD/endpointing. WebRTC VAD chỉ chấp nhận 10/20/30 ms;
    # toàn pipeline hiện dùng 30 ms để mọi ngưỡng thời gian có cùng ý nghĩa.
    frame_ms: Literal[10, 20, 30] = 30
    # Backpressure: không để audio chậm tích luỹ vô hạn. 1,5 s đủ hấp thụ jitter ngắn,
    # nhưng vẫn buộc producer chậm lại nếu inference không theo kịp realtime.
    input_queue_ms: int = 1_500
    # Giữ phần đầu câu nói chen trong lúc bot đang phát; chỉ replay vào ASR sau khi
    # InterruptionController xác nhận đây là barge-in thật.
    barge_in_preroll_ms: int = 500
    # Queue phát càng dài thì barge-in càng chậm. 200 ms là biên an toàn nhỏ hơn default
    # 1.000 ms của LiveKit AudioSource.
    output_queue_ms: int = 200
    # LiveKit `start` mặc định giữ 4 process nóng; ZipFormer được load trong mỗi process.
    # Một process idle phù hợp máy demo 2 vCPU/2 GB, tránh nhân bộ nhớ model lên 4 lần.
    worker_num_idle_processes: int = 1

    @field_validator(
        "token_ttl_s",
        "input_queue_ms",
        "barge_in_preroll_ms",
        "output_queue_ms",
    )
    @classmethod
    def _positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("phải lớn hơn 0")
        return value

    @field_validator("worker_num_idle_processes")
    @classmethod
    def _non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("không được âm")
        return value
