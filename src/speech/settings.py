from typing import Literal, Optional

from pydantic import field_validator

from appconfig import YamlSettings, yaml_config
from inference.asr import ProviderName as ASRProviderName
from inference.tts import ProviderName as TTSProviderName


class SpeechSettings(YamlSettings):
    """Giá trị mặc định: config/speech.yaml.

    Không có tần số mẫu ở đây: HTTP giữ tần số gốc của clip (ASR tự resample), LiveKit dùng
    `input_sample_rate` của config/livekit.yaml.
    """

    model_config = yaml_config("speech.yaml")

    # Chỉ chọn provider; model/API key của từng provider do inference.asr.config /
    # inference.tts.config đọc (config/asr.yaml, config/tts.yaml, key từ env).
    asr_provider: ASRProviderName
    tts_provider: TTSProviderName
    # Provider dự phòng khi provider chính lỗi (vd. vbee -> elevenlabs); None = không fallback
    tts_fallback_provider: Optional[TTSProviderName]

    @field_validator("tts_fallback_provider", mode="before")
    @classmethod
    def _blank_fallback_is_none(cls, value: object) -> object:
        # `TTS_FALLBACK_PROVIDER=` rỗng trong .env nghĩa là tắt fallback
        return None if isinstance(value, str) and not value.strip() else value

    # --- VAD (chỉ đường LiveKit; đường HTTP không dùng VAD) ---
    # Một bộ phân loại theo vad_provider, dùng chung cho VAD chính và bộ chốt câu của ASR.
    # energy: RMS, dễ nhầm nhiễu thành lời. webrtc: cần extra "vad-webrtc".
    # silero: cần silero_vad_model_path; ít nhầm nhiễu nhất (docs/reference/livekit-architecture.md §5.4).
    vad_provider: Literal["energy", "webrtc", "silero"]
    vad_rms_threshold: float  # chỉ cho energy
    vad_webrtc_aggressiveness: int  # chỉ cho webrtc
    vad_end_silence_ms: int
    # Luôn dùng cho SNR của Validator (WebRTC/energy làm SNR sai), và cho vad_provider=silero.
    silero_vad_model_path: str
    # Silero giữ "đang nói" thêm chừng này sau khi hết tiếng — cộng vào độ trễ chốt lượt.
    silero_min_silence_ms: int

    # --- Chốt lượt (TurnController) ---
    # Lượt ngắn hơn ngưỡng này bị coi là tiếng động/backchannel.
    turn_min_speech_ms: int
    turn_max_wait_after_vad_end_ms: int
    # ASR decode chậm còn tồn audio của câu: chờ tối đa chừng này rồi mới chốt bằng partial.
    turn_max_wait_for_asr_ms: int
    # Lời bắt đầu quá sát lúc bot dứt lời phải dài thêm phần còn thiếu — chống tiếng vọng.
    turn_post_bot_guard_ms: int

    # --- Turn Validator: lọc lượt ảo giác theo SNR + độ ổn định transcript ---
    turn_validator_enabled: bool
    turn_validator_min_snr_db: float
    # Ngưỡng SNR riêng cho ngắt lời (barge-in), áp cho mọi độ dài câu — chặn tiếng bot vọng
    # qua loa/mic. None = tắt.
    interruption_min_snr_db: Optional[float]

    # URL công khai để dựng audio_url trả về cho harness
    public_base_url: str
    audio_dir: str
