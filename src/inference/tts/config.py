"""Provider configuration; instantiate only the selected provider's settings.

Giá trị mặc định ở config/tts.yaml (mỗi provider một section); API key/token chỉ đặt qua env.
"""

from typing import Optional

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import SettingsConfigDict

from appconfig import YamlSettings, yaml_config


class TTSConfig(YamlSettings):
    model_config = SettingsConfigDict(populate_by_name=True, hide_input_in_errors=True)

    @field_validator("*", mode="before")
    @classmethod
    def strip_strings(cls, value):
        return value.strip() if isinstance(value, str) else value


class OpenAITTSConfig(TTSConfig):
    model_config = yaml_config("tts.yaml", "openai")

    # Secret: chỉ từ env, rỗng = chưa cấu hình
    api_key: SecretStr = Field(default=SecretStr(""), validation_alias="OPENAI_API_KEY")
    model: str = Field(validation_alias="OPENAI_TTS_MODEL")
    voice: str = Field(validation_alias="OPENAI_TTS_VOICE")


class VbeeTTSConfig(TTSConfig):
    model_config = yaml_config("tts.yaml", "vbee")

    # Secret: chỉ từ env, rỗng = chưa cấu hình
    api_token: SecretStr = Field(default=SecretStr(""), validation_alias="VBEE_API_TOKEN")
    app_id: str = Field(default="", validation_alias="VBEE_APP_ID")
    endpoint: str = Field(validation_alias="VBEE_ENDPOINT")
    voice_code: str = Field(validation_alias="VBEE_VOICE_CODE")
    speed: float = Field(validation_alias="VBEE_SPEED")
    bitrate: int = Field(validation_alias="VBEE_BITRATE")
    # Xin PCM 8 kHz: khớp băng hẹp, không phải resample (benchmark 23/9)
    sample_rate: int = Field(validation_alias="VBEE_SAMPLE_RATE")
    # Trần tổng cho một câu. Giữ thấp: lỗi thì còn thời gian cho ElevenLabs dự phòng trong 8 s/lượt
    timeout_s: float = Field(validation_alias="VBEE_TIMEOUT_S")
    connect_timeout_s: float = Field(validation_alias="VBEE_CONNECT_TIMEOUT_S")
    # Giữ kết nối rảnh bao lâu để lượt sau dùng lại; phải ngắn hơn thời gian server Vbee tự đóng
    keepalive_s: float = Field(validation_alias="VBEE_KEEPALIVE_S")


class ElevenLabsTTSConfig(TTSConfig):
    model_config = yaml_config("tts.yaml", "elevenlabs")

    # Secret: chỉ từ env, rỗng = chưa cấu hình
    api_key: SecretStr = Field(default=SecretStr(""), validation_alias="ELEVENLABS_API_KEY")
    voice_id: str = Field(validation_alias="ELEVENLABS_VOICE_ID")
    model: str = Field(validation_alias="ELEVENLABS_MODEL")
    timeout_s: float = Field(validation_alias="ELEVENLABS_TIMEOUT_S")
    # pcm_8000 khớp băng hẹp, không phải resample; tuần 5 điện thoại có thể dùng ulaw_8000
    output_format: str = Field(validation_alias="ELEVENLABS_OUTPUT_FORMAT")
    # Ép model đọc tiếng Việt kể cả câu ngắn dễ đoán nhầm ngôn ngữ; None = để model tự đoán.
    # Env rỗng ("") bị bỏ qua nên vẫn ra giá trị trong tts.yaml, không phải auto-detect — muốn
    # auto-detect thì đặt `language_code: null` trong tts.yaml hoặc truyền None trực tiếp.
    language_code: Optional[str] = Field(validation_alias="ELEVENLABS_LANGUAGE_CODE")
