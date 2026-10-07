from typing import Any, Literal, Optional

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
    # Lượt đủ điều kiện chốt vẫn chờ thêm chừng này để gộp phần người gọi nói tiếp. 0 = tắt.
    turn_merge_window_ms: int

    # Audio giữ trước lúc nhận ra tiếng nói, đưa kèm vào ASR streaming. None = theo asr.yaml.
    asr_pre_speech_ms: Optional[int]
    # Cuộc gọi điện thoại (participant SIP) ghi đè các khoá này — xem `for_phone`.
    phone_overrides: dict[str, Any]

    @field_validator("phone_overrides")
    @classmethod
    def _known_phone_keys(cls, value: dict[str, Any]) -> dict[str, Any]:
        unknown = set(value) - set(cls.model_fields) - {"phone_overrides"}
        if unknown or "phone_overrides" in value:
            raise ValueError(f"phone_overrides có khoá không hợp lệ: {sorted(unknown)}")
        return value

    def for_phone(self) -> "SpeechSettings":
        """Cấu hình cho cuộc gọi điện thoại: `phone_overrides` ghi đè lên chính cấu hình này."""
        return type(self).model_validate({**self.model_dump(), **self.phone_overrides})

    # Câu chỉ có từ đệm ("ừ", "à", "dạ"…): False = gửi engine (engine hiểu "ừ/ờ" là đồng ý, "dạ"
    # là hỏi lại); True = bỏ.
    turn_drop_filler_words: bool

    # THỬ NGHIỆM cổng giọng người gọi (speech/audio/speaker_gate.py): off | log | enforce.
    speaker_gate_mode: Literal["off", "log", "enforce"]
    speaker_gate_model_path: str
    speaker_gate_threshold: float
    speaker_gate_min_speech_ms: int

    # --- Turn Validator: lọc lượt ảo giác theo SNR + độ ổn định transcript ---
    turn_validator_enabled: bool
    turn_validator_min_snr_db: float
    # Ngưỡng SNR riêng cho ngắt lời (barge-in), áp cho mọi độ dài câu — chặn tiếng bot vọng
    # qua loa/mic. None = tắt.
    interruption_min_snr_db: Optional[float]

    # URL công khai để dựng audio_url trả về cho harness
    public_base_url: str
    audio_dir: str
