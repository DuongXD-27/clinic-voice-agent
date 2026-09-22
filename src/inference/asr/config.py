"""Provider configuration; instantiate only the selected provider's settings."""

from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Asset ZipFormer đi kèm repo (bị .gitignore, tải tay theo docs/reference/zipformer-model-setup.md).
_ZIPFORMER_ASSETS = Path(__file__).parent / "providers" / "assets" / "zipformer"


class ASRConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        hide_input_in_errors=True,
    )

    @field_validator("*", mode="before")
    @classmethod
    def empty_uses_provider_default(cls, value, info):
        if isinstance(value, str) and not value.strip():
            return cls.model_fields[info.field_name].get_default()
        return value.strip() if isinstance(value, str) else value


class GeminiASRConfig(ASRConfig):
    api_key: SecretStr = Field(default=SecretStr(""), validation_alias="GEMINI_API_KEY")
    model: str = Field(default="gemini-2.5-flash", validation_alias="GEMINI_ASR_MODEL")


class PhoWhisperConfig(ASRConfig):
    model: str = Field(default="vinai/PhoWhisper-large", validation_alias="PHOWHISPER_MODEL")


class ElevenLabsRealtimeConfig(ASRConfig):
    api_key: SecretStr = Field(default=SecretStr(""), validation_alias="ELEVENLABS_API_KEY")
    model: str = Field(
        default="scribe_v2_realtime", validation_alias="ELEVENLABS_REALTIME_STT_MODEL"
    )
    language_code: str = Field(default="vie", validation_alias="ELEVENLABS_STT_LANGUAGE_CODE")
    base_url: str = Field(
        default="wss://api.elevenlabs.io", validation_alias="ELEVENLABS_REALTIME_WS_URL"
    )
    # Server tự đóng phiên (commit) sau khoảng lặng này khi vad_commit_strategy được server
    # bật — ta dùng CommitStrategy.MANUAL (commit tường minh khi VAD của pipeline báo
    # speech_end, xem provider) nên giá trị này chỉ ảnh hưởng ngưỡng partial_transcript nội
    # bộ của model, không phải endpoint hoá turn (đó là việc của TurnController).
    vad_silence_threshold_secs: float = Field(
        default=1.5, validation_alias="ELEVENLABS_REALTIME_VAD_SILENCE_SECS"
    )
    keyterms: str = Field(default="", validation_alias="ELEVENLABS_STT_KEYTERMS")


class ZipFormerConfig(ASRConfig):
    model: str = "csukuangfj/sherpa-onnx-zipformer-vi-int8-2025-04-20"
    encoder_path: str = Field(
        default=str(_ZIPFORMER_ASSETS / "encoder-epoch-12-avg-8.int8.onnx"),
        validation_alias="ZIPFORMER_ENCODER_PATH",
    )
    decoder_path: str = Field(
        default=str(_ZIPFORMER_ASSETS / "decoder-epoch-12-avg-8.onnx"),
        validation_alias="ZIPFORMER_DECODER_PATH",
    )
    joiner_path: str = Field(
        default=str(_ZIPFORMER_ASSETS / "joiner-epoch-12-avg-8.int8.onnx"),
        validation_alias="ZIPFORMER_JOINER_PATH",
    )
    tokens_path: str = Field(
        default=str(_ZIPFORMER_ASSETS / "tokens.txt"), validation_alias="ZIPFORMER_TOKENS_PATH"
    )
    num_threads: int = Field(default=2, gt=0)
    # stream() (chunked-offline, xem docstring module provider) không decode buffer speech
    # ngắn hơn ngưỡng này — chống ZipFormer hallucinate ra cả cụm từ từ audio siêu ngắn
    # như "à"/"ờm"/hắng giọng (VAD đúng khi coi đó là speech, nhưng ASR không tin cậy trên
    # input quá ngắn để cung cấp đủ context cho transducer greedy_search).
    min_decode_ms: int = Field(default=400, validation_alias="ZIPFORMER_MIN_DECODE_MS")
    # stream() flush cưỡng bức buffer khi speech liên tục vượt ngưỡng này, dù chưa có
    # end_silence_ms đủ dài — chống memory leak thật đã xác nhận (60s audio giả lập liên
    # tục không speech_end -> 127s xử lý, 1551MB RAM): buffer chunked-offline tăng vô hạn
    # nếu VAD không bao giờ báo đủ khoảng lặng liên tục (docs/reference/
    # livekit-architecture.md §5.5).
    max_turn_speech_ms: int = Field(default=15_000, validation_alias="ZIPFORMER_MAX_TURN_SPEECH_MS")
