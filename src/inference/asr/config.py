"""Provider configuration; instantiate only the selected provider's settings.

Giá trị mặc định ở config/asr.yaml (mỗi provider một section); API key chỉ đặt qua env.
"""

from typing import Optional

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import SettingsConfigDict

from appconfig import YamlSettings, yaml_config


class ASRConfig(YamlSettings):
    model_config = SettingsConfigDict(populate_by_name=True, hide_input_in_errors=True)

    @field_validator("*", mode="before")
    @classmethod
    def strip_strings(cls, value):
        return value.strip() if isinstance(value, str) else value


class GeminiASRConfig(ASRConfig):
    model_config = yaml_config("asr.yaml", "gemini")

    # Secret: chỉ từ env, rỗng = chưa cấu hình
    api_key: SecretStr = Field(default=SecretStr(""), validation_alias="GEMINI_API_KEY")
    model: str = Field(validation_alias="GEMINI_ASR_MODEL")


class PhoWhisperConfig(ASRConfig):
    model_config = yaml_config("asr.yaml", "phowhisper")

    model: str = Field(validation_alias="PHOWHISPER_MODEL")


class GeminiLiveASRConfig(ASRConfig):
    model_config = yaml_config("asr.yaml", "gemini_live")

    api_key: SecretStr = Field(default=SecretStr(""), validation_alias="GEMINI_API_KEY")
    model: str = Field(validation_alias="GEMINI_LIVE_ASR_MODEL")
    language_code: str = Field(validation_alias="GEMINI_LIVE_LANGUAGE_CODE")
    connect_timeout_s: float = Field(gt=0, validation_alias="GEMINI_LIVE_CONNECT_TIMEOUT_S")
    final_timeout_s: float = Field(gt=0, validation_alias="GEMINI_LIVE_FINAL_TIMEOUT_S")
    chunk_ms: int = Field(ge=20, le=200, validation_alias="GEMINI_LIVE_CHUNK_MS")
    max_turn_speech_ms: int = Field(gt=0, validation_alias="GEMINI_LIVE_MAX_TURN_SPEECH_MS")
    # Audio giữ lại trước frame đầu tiên bộ phân loại báo tiếng nói, gửi kèm khi mở đoạn.
    pre_speech_ms: int = Field(ge=0, validation_alias="GEMINI_LIVE_PRE_SPEECH_MS")


class ElevenLabsRealtimeConfig(ASRConfig):
    model_config = yaml_config("asr.yaml", "elevenlabs_realtime")

    # Secret: chỉ từ env, rỗng = chưa cấu hình
    api_key: SecretStr = Field(default=SecretStr(""), validation_alias="ELEVENLABS_API_KEY")
    model: str = Field(validation_alias="ELEVENLABS_REALTIME_STT_MODEL")
    language_code: str = Field(validation_alias="ELEVENLABS_STT_LANGUAGE_CODE")
    base_url: str = Field(validation_alias="ELEVENLABS_REALTIME_WS_URL")
    # Server tự đóng phiên (commit) sau khoảng lặng này khi vad_commit_strategy được server
    # bật — ta dùng CommitStrategy.MANUAL (commit tường minh khi VAD của pipeline báo
    # speech_end, xem provider) nên giá trị này chỉ ảnh hưởng ngưỡng partial_transcript nội
    # bộ của model, không phải endpoint hoá turn (đó là việc của TurnController).
    vad_silence_threshold_secs: float = Field(
        validation_alias="ELEVENLABS_REALTIME_VAD_SILENCE_SECS"
    )
    keyterms: str = Field(validation_alias="ELEVENLABS_STT_KEYTERMS")


class ZipFormerConfig(ASRConfig):
    model_config = yaml_config("asr.yaml", "zipformer")

    model: str = Field(validation_alias="ZIPFORMER_MODEL")
    encoder_path: str = Field(validation_alias="ZIPFORMER_ENCODER_PATH")
    decoder_path: str = Field(validation_alias="ZIPFORMER_DECODER_PATH")
    joiner_path: str = Field(validation_alias="ZIPFORMER_JOINER_PATH")
    tokens_path: str = Field(validation_alias="ZIPFORMER_TOKENS_PATH")
    num_threads: int = Field(gt=0, validation_alias="ZIPFORMER_NUM_THREADS")
    # stream() (chunked-offline, xem docstring module provider) không decode buffer speech
    # ngắn hơn ngưỡng này — chống ZipFormer hallucinate ra cả cụm từ từ audio siêu ngắn
    # như "à"/"ờm"/hắng giọng (VAD đúng khi coi đó là speech, nhưng ASR không tin cậy trên
    # input quá ngắn để cung cấp đủ context cho transducer greedy_search).
    min_decode_ms: int = Field(validation_alias="ZIPFORMER_MIN_DECODE_MS")
    # stream() flush cưỡng bức buffer khi speech liên tục vượt ngưỡng này, dù chưa có
    # end_silence_ms đủ dài — chống memory leak thật đã xác nhận (60s audio giả lập liên
    # tục không speech_end -> 127s xử lý, 1551MB RAM): buffer chunked-offline tăng vô hạn
    # nếu VAD không bao giờ báo đủ khoảng lặng liên tục (docs/reference/
    # livekit-architecture.md §5.5).
    max_turn_speech_ms: int = Field(validation_alias="ZIPFORMER_MAX_TURN_SPEECH_MS")
    # Giãn nhịp decode partial theo độ dài buffer: khoảng cách giữa hai lần decode partial =
    # max(300 ms, tỉ lệ này x độ dài buffer). 0 = tắt (luôn 300 ms). Câu 10 s decode lại ~33 lần
    # (~2,5 s CPU); 0,1 giữ nguyên câu < 3 s, còn ~1/2 số lần decode cho câu dài. Final không đổi.
    partial_interval_ratio: float = Field(ge=0, validation_alias="ZIPFORMER_PARTIAL_INTERVAL_RATIO")
    # Audio giữ lại trước frame đầu tiên bộ phân loại báo tiếng nói, decode cùng câu. Phải phủ
    # được độ trễ nhận ra đầu câu của Silero (min_speech_duration mặc định 0,25 s), nếu không
    # mất âm tiết đầu ("Vâng," của golden STT_CF_02 bị Silero bật cờ trễ ~700 ms).
    pre_speech_ms: int = Field(ge=0, validation_alias="ZIPFORMER_PRE_SPEECH_MS")
    # Final chỉ decode tới frame cuối được báo là tiếng nói + chừng này (Silero đã giữ cờ thêm
    # ~0,5 s sau khi hết tiếng). None = decode cả ~1,1 s im lặng đuôi như trước — đuôi im lặng
    # làm câu ngắn đổi chữ: partial "BÂY GIỜ" 0,94 -> final "ĐƯỢC" 0,28; "OK" -> "Ừ/ĐÂY".
    final_tail_ms: Optional[int] = Field(
        default=None, ge=0, validation_alias="ZIPFORMER_FINAL_TAIL_MS"
    )
    # Đầu câu: ngoài `pre_speech_ms` cố định, lần ngược tối đa chừng này ms tới chỗ năng lượng
    # thật sự bắt đầu (Silero báo trễ: trên 870 câu thật, trễ so với điểm năng lượng p50 360 ms,
    # p90 720 ms; 85% câu > 300 ms). None = tắt (chỉ `pre_speech_ms`).
    onset_lookback_ms: Optional[int] = Field(
        default=None, ge=0, validation_alias="ZIPFORMER_ONSET_LOOKBACK_MS"
    )
