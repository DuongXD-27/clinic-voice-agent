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
    # Xác suất tiếng nói tối thiểu để Silero bắt đầu / giữ "đang nói" (0,5 = mặc định của model).
    silero_threshold: float
    # v4: silero_vad_model_path qua sherpa-onnx. v6: silero_vad_v6_model_path (Silero v6.2.3 chính
    # thức) qua onnxruntime — speech/asr/vad/silero_onnx.py, cùng máy trạng thái (sherpa chạy v6 lệch
    # bản chính thức, mất âm đầu câu nhiều hơn). Thiếu file v6 thì cảnh báo và dùng v4. Dùng cho bộ
    # phân loại của LiveKit và cho /v1/stt.
    silero_vad_version: Literal["v4", "v6"]
    silero_vad_v6_model_path: str
    # Audio riêng cho bộ phân loại tiếng nói (speech/audio/vad_frontend.py): khử nhiễu chỉ để
    # Silero quyết định có/không tiếng nói, ASR vẫn nghe audio gốc. Chỉ dùng với vad_provider=silero.
    vad_frontend: Literal["off", "webrtc", "webrtc_agc", "gtcrn", "dpdfnet"]
    vad_frontend_model_path: str
    # Tăng âm sau khi khử nhiễu, chỉ cho bộ phân loại (Silero phụ thuộc mức âm tuyệt đối).
    vad_frontend_gain_db: float
    # Nhiễu trắng nền (RMS, dBFS) cộng vào sau khi khử nhiễu: Silero không bao giờ nghe im lặng
    # tuyệt đối. None = không cộng.
    vad_frontend_floor_dbfs: Optional[float]

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
    # Bỏ chữ bot vọng lại khỏi lượt người gọi: text | acoustic | three_state
    # (speech.turn.interruption.EchoPolicy).
    turn_echo_policy: Literal["text", "acoustic", "three_state"]
    # Lời người gọi nói chen lúc bot nói mà chưa được xác nhận ngắt lời: giữ riêng, decode khi bot
    # dứt lời, thành lượt nếu còn chữ sau khi bỏ tiếng vọng. False = bỏ (trước 08/10).
    turn_keep_unconfirmed_barge_in: bool
    # Tăng âm giọng người gọi quá nhỏ trước VAD/ASR (speech/audio/quiet_gain.py). Giọng đủ to thì
    # luồng giữ nguyên; nền nhiễu sau khi tăng không vượt -50 dBFS.
    quiet_speech_gain_enabled: bool

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
