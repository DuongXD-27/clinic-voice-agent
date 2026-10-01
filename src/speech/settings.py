from typing import Literal, Optional

from pydantic import field_validator, model_validator

from appconfig import YamlSettings, yaml_config
from inference.asr import ProviderName as ASRProviderName
from inference.tts import ProviderName as TTSProviderName
from speech.types import SampleRate


class SpeechSettings(YamlSettings):
    """Giá trị mặc định: config/speech.yaml."""

    model_config = yaml_config("speech.yaml")

    # Tần số chuẩn của pipeline. Mặc định băng hẹp 8 kHz như đường dây điện thoại;
    # đặt 16000 chỉ để so sánh WER, không dùng cho số liệu báo cáo.
    sample_rate: SampleRate

    @field_validator("sample_rate", mode="before")
    @classmethod
    def _coerce_sample_rate(cls, value: object) -> object:
        # pydantic không tự coerce string "8000" từ .env thành Literal[int] — ép tay.
        return int(value) if isinstance(value, str) else value

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

    # "energy": RMS đơn thuần, baseline, không phân biệt giọng nói với tiếng ồn.
    # "webrtc": Google WebRTC's VAD (cần extra "vad-webrtc"), phân biệt tốt hơn nhiều —
    # khuyến nghị cho đường LiveKit streaming (energy dễ hiểu nhầm noise thành turn).
    # "silero": ONNX model (silero_vad_model_path, cần extra "vad-silero"/sherpa-onnx) —
    # từng chỉ dùng riêng cho NoiseTracker (evidence của Turn Validator), giờ có thể
    # chọn làm VAD chính. Đối chiếu thực nghiệm qua ASR trên audio LiveKit thật
    # (docs/reference/livekit-architecture.md §5.4): trên MỌI file kiểm tra, Silero không
    # bỏ sót giọng nói thật (kể cả câu dài, nội dung nghiệp vụ), và từ chối đúng các đoạn
    # thuần noise mà WebRTC liên tục hiểu nhầm thành speech (mẫu hallucination "ĐÂY"/"Ừ"
    # lặp lại nhiều phút liền dù không ai nói gì). Chưa đổi mặc định — cần benchmark thêm
    # trên tập audio đa dạng hơn trước khi áp dụng cho mọi call.
    vad_provider: Literal["energy", "webrtc", "silero"]
    vad_rms_threshold: float
    vad_webrtc_aggressiveness: int
    vad_end_silence_ms: int
    # Turn Controller (transports/livekit/call_bridge.py): turn ngắn hơn ngưỡng này
    # (từ VAD speech_start) bị coi là tiếng động/backchannel, không emit thành turn —
    # lớp phòng thủ thứ 2 bên cạnh vad_provider, chống "dạ dạ" liên tục do nhiễu ngoài.
    turn_min_speech_ms: int
    turn_max_wait_after_vad_end_ms: int
    # VAD không còn bị ASR chặn: khi decode chậm, VAD có thể báo hết câu lúc ASR còn tồn
    # audio của câu. Chờ ASR xử lý hết tối đa chừng này rồi mới chốt bằng partial.
    turn_max_wait_for_asr_ms: int
    # Candidate bắt đầu quá gần thời điểm bot vừa dứt lời (< ngưỡng này) bị discard —
    # chống dư âm/tiếng vọng phòng (loa ngoài, browser echo-cancellation không hoàn hảo)
    # đủ dài để WebRTC VAD coi là speech_start thật ngay sau khi is_bot_speaking chuyển
    # False, khiến ASR hallucinate 1 cụm từ "có nghĩa" và TurnController chốt turn giả dù
    # user không hề nói gì (bug thật đã gặp qua LiveKit demo).
    turn_post_bot_guard_ms: int

    # Turn Validator (docs/reference/livekit-architecture.md §5.4, §6): lớp quyết định
    # cuối trước khi chốt turn, dựa trên acoustic evidence (NoiseTracker) + transcript
    # stability (TranscriptEvidenceTracker). Mặc định TẮT — cần benchmark thêm trước khi
    # bật cho mọi call.
    turn_validator_enabled: bool
    turn_validator_min_snr_db: float
    # Ngưỡng SNR RIÊNG cho InterruptionController (barge-in) — KHÔNG dùng chung
    # turn_validator_min_snr_db, xem docstring InterruptionController.__init__. Bug thật
    # đã gặp: echo giọng bot qua loa/mic (browser echo cancellation không loại hết) tạo
    # candidate text DÀI, mạch lạc (stability=CONVERGING) nên né được luật SNR của
    # TurnValidator (chỉ áp dụng cho text <=2 từ) — candidate 5 từ vẫn ACCEPT dù
    # snr_db=-25.56 (rất thấp, đặc trưng echo qua loa-mic khác giọng nói trực tiếp). Kiểm
    # tra này không phân biệt độ dài text. `None` tắt hẳn (giữ hành vi cũ) — mặc định để
    # tắt vì cần benchmark thêm trước khi áp dụng cho mọi call, cùng tinh thần các cờ
    # turn_validator_enabled khác trong file này.
    interruption_min_snr_db: Optional[float]
    # Bug thật đã gặp: dùng WebRTC (`vad_provider`) làm classifier cho NoiseTracker khiến
    # noise_floor không được cập nhật đúng — WebRTC báo speech=True gần như LIÊN TỤC trên
    # noise phòng thuần (0 false-negative nhưng rất nhiều false-positive), nên
    # NoiseTracker._is_speech=False hiếm khi trigger cập nhật, SNR tính ra dao động hỗn
    # loạn (-150dB tới +34dB trên CHÍNH noise, không phải speech thật) — khiến
    # TurnValidator thỉnh thoảng thấy SNR "cao giả" và cho qua turn giả.
    # Silero VAD (silero_vad_model_path) đã xác nhận qua benchmark thực nghiệm KHÔNG bị
    # lừa bởi cùng loại noise này (0/400 false-positive) — dùng riêng cho NoiseTracker,
    # tách biệt khỏi `vad_provider` (vẫn WebRTC cho turn-taking chính, chưa đổi mặc định).
    silero_vad_model_path: str
    # Hangover của Silero (giữ "đang nói" sau khi hết tiếng) — cộng vào độ trễ chốt lượt cùng
    # vad_end_silence_ms. Mặc định 500 ms của sherpa-onnx.
    silero_min_silence_ms: int
    # Đường LiveKit: MỘT bản Silero phân loại mỗi frame một lần, dùng chung cho VAD chính, bộ chốt
    # câu của ASR và evidence của Validator (speech/asr/vad/shared.py) thay cho 3 bản độc lập. Bật thì VAD chính là Silero bất kể `vad_provider` (evidence bắt buộc Silero, xem
    # trên); `vad_provider` khi đó chỉ còn áp dụng cho đường HTTP batch.
    speech_shared_detector: bool
    # Chẩn đoán đường streaming (speech/diagnostics.py): chạy thêm Silero ONNX song song để ghi
    # xác suất giọng của mỗi đoạn vào log. Chỉ quan sát — tắt thì vẫn có log kết cục từng đoạn,
    # chỉ thiếu xác suất (đỡ một lần suy luận Silero mỗi 32 ms).
    speech_diagnostics_probe: bool = True
    # Pre-speech của ASR lùi thêm tối đa chừng này qua phần giọng mà bộ phân loại báo trễ, theo
    # xác suất Silero thô (`_PreSpeech` trong inference/asr/providers/zipformer.py). 0 = tắt,
    # giữ cửa sổ cố định 300 ms. Cần speech_shared_detector (probe chạy trong bộ phân loại chung).
    asr_voice_lookback_ms: int = 0

    # URL công khai để dựng audio_url trả về cho harness
    public_base_url: str
    audio_dir: str

    @model_validator(mode="after")
    def _lookback_needs_shared_detector(self) -> "SpeechSettings":
        if self.asr_voice_lookback_ms < 0:
            raise ValueError("asr_voice_lookback_ms không được âm")
        if self.asr_voice_lookback_ms and not self.speech_shared_detector:
            raise ValueError("asr_voice_lookback_ms cần speech_shared_detector=true")
        return self
