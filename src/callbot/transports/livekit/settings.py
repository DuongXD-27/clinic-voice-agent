from typing import Literal

from pydantic import Field, field_validator

from appconfig import YamlSettings, yaml_config


class LiveKitSettings(YamlSettings):
    """Giá trị mặc định: config/livekit.yaml. Env: LIVEKIT_<TÊN FIELD> (vd. LIVEKIT_FRAME_MS)."""

    model_config = yaml_config("livekit.yaml", env_prefix="LIVEKIT_", populate_by_name=True)

    # Theo deploy / secret: chỉ từ env, rỗng = chưa cấu hình (/livekit/token trả 503)
    livekit_url: str = Field(default="", validation_alias="LIVEKIT_URL")
    livekit_api_key: str = Field(default="", validation_alias="LIVEKIT_API_KEY")
    livekit_api_secret: str = Field(default="", validation_alias="LIVEKIT_API_SECRET")
    # Tiền tố room cho web call — CallBridge dùng room.name làm call_id thẳng.
    room_name_prefix: str
    # Kích thước token cho browser — đủ để connect + publish mic + subscribe TTS.
    token_ttl_s: int
    # WebRTC giữ wideband 16 kHz tới boundary ZipFormer. Đường phone sau này vẫn có
    # thể đưa 8 kHz vào cùng provider vì ZipFormerASR.stream nhận sample rate tường minh.
    input_sample_rate: Literal[8_000, 16_000]
    # Một frame canonical cho VAD/endpointing. WebRTC VAD chỉ chấp nhận 10/20/30 ms;
    # toàn pipeline hiện dùng 30 ms để mọi ngưỡng thời gian có cùng ý nghĩa.
    frame_ms: Literal[10, 20, 30]
    # Backpressure: không để audio chậm tích luỹ vô hạn. 1,5 s đủ hấp thụ jitter ngắn,
    # nhưng vẫn buộc producer chậm lại nếu inference không theo kịp realtime.
    input_queue_ms: int
    # Giữ phần đầu câu nói chen trong lúc bot đang phát; chỉ replay vào ASR sau khi
    # InterruptionController xác nhận đây là barge-in thật.
    barge_in_preroll_ms: int
    # Queue phát càng dài thì barge-in càng chậm. 200 ms là biên an toàn nhỏ hơn default
    # 1.000 ms của LiveKit AudioSource.
    output_queue_ms: int
    # LiveKit `start` mặc định giữ 4 process nóng; ZipFormer được load trong mỗi process.
    # Một process idle phù hợp máy demo 2 vCPU/2 GB, tránh nhân bộ nhớ model lên 4 lần.
    worker_num_idle_processes: int

    @field_validator("input_sample_rate", "frame_ms", mode="before")
    @classmethod
    def _coerce_literal_int(cls, value: object) -> object:
        # pydantic không tự coerce string "16000" từ env thành Literal[int] — ép tay.
        return int(value) if isinstance(value, str) else value

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
