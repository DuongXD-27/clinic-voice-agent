from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from inference.asr import ProviderName as ASRProviderName
from inference.tts import ProviderName as TTSProviderName
from speech.types import NARROWBAND_RATE, SampleRate


class SpeechSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Tần số chuẩn của pipeline. Mặc định băng hẹp 8 kHz như đường dây điện thoại;
    # đặt 16000 chỉ để so sánh WER, không dùng cho số liệu báo cáo.
    sample_rate: SampleRate = NARROWBAND_RATE

    @field_validator("sample_rate", mode="before")
    @classmethod
    def _coerce_sample_rate(cls, value: object) -> object:
        # pydantic không tự coerce string "8000" từ .env thành Literal[int] — ép tay.
        return int(value) if isinstance(value, str) else value

    # Chỉ chọn provider; model/API key của từng provider do inference.asr.config /
    # inference.tts.config đọc từ env (GEMINI_ASR_MODEL, ZIPFORMER_*_PATH, OPENAI_TTS_MODEL...).
    asr_provider: ASRProviderName = "gemini"
    tts_provider: TTSProviderName = "openai"

    # "energy": RMS đơn thuần, baseline, không phân biệt giọng nói với tiếng ồn.
    # "webrtc": Google WebRTC's VAD (cần extra "vad-webrtc"), phân biệt tốt hơn nhiều —
    # khuyến nghị cho đường LiveKit streaming (energy dễ hiểu nhầm noise thành turn).
    # "silero": ONNX model (silero_vad_model_path, cần extra "vad-silero"/sherpa-onnx) —
    # từng chỉ dùng riêng cho NoiseTracker (Speech Admission/Turn Validator), giờ có thể
    # chọn làm VAD chính. Đối chiếu thực nghiệm qua ASR trên audio LiveKit thật
    # (docs/reference/livekit-architecture.md §5.4): trên MỌI file kiểm tra, Silero không
    # bỏ sót giọng nói thật (kể cả câu dài, nội dung nghiệp vụ), và từ chối đúng các đoạn
    # thuần noise mà WebRTC liên tục hiểu nhầm thành speech (mẫu hallucination "ĐÂY"/"Ừ"
    # lặp lại nhiều phút liền dù không ai nói gì). Chưa đổi mặc định — cần benchmark thêm
    # trên tập audio đa dạng hơn trước khi áp dụng cho mọi call.
    vad_provider: Literal["energy", "webrtc", "silero"] = "energy"
    vad_rms_threshold: float = 500.0
    vad_webrtc_aggressiveness: int = 2
    vad_end_silence_ms: int = 600
    # Turn Controller (transports/livekit/call_bridge.py): turn ngắn hơn ngưỡng này
    # (từ VAD speech_start) bị coi là tiếng động/backchannel, không emit thành turn —
    # lớp phòng thủ thứ 2 bên cạnh vad_provider, chống "dạ dạ" liên tục do nhiễu ngoài.
    turn_min_speech_ms: int = 250
    turn_max_wait_after_vad_end_ms: int = 300
    # Candidate bắt đầu quá gần thời điểm bot vừa dứt lời (< ngưỡng này) bị discard —
    # chống dư âm/tiếng vọng phòng (loa ngoài, browser echo-cancellation không hoàn hảo)
    # đủ dài để WebRTC VAD coi là speech_start thật ngay sau khi is_bot_speaking chuyển
    # False, khiến ASR hallucinate 1 cụm từ "có nghĩa" và TurnController chốt turn giả dù
    # user không hề nói gì (bug thật đã gặp qua LiveKit demo).
    turn_post_bot_guard_ms: int = 500

    # Speech Admission (docs/reference/livekit-architecture.md §5.4): lớp lọc TRƯỚC asr_queue
    # dựa trên SNR liên tục (NoiseTracker), chặn sớm noise phòng không đồng đều mà VAD đôi
    # khi hiểu nhầm thành speech_start — nguyên nhân gốc hallucination ("ĐÂY"/"TẠI" lặp lại)
    # đã xác nhận qua LIVEKIT_DEBUG_DUMP_AUDIO. Mặc định TẮT: cần benchmark thêm trên audio
    # thật đa dạng trước khi bật mặc định cho mọi call.
    speech_admission_enabled: bool = False
    speech_admission_min_snr_db: float = 6.0
    speech_admission_min_speech_ms: int = 150

    # Turn Validator (docs/reference/livekit-architecture.md §5.4, §6): lớp quyết định
    # cuối trước khi chốt turn, dựa trên acoustic evidence (NoiseTracker) + transcript
    # stability (TranscriptEvidenceTracker) — ĐỘC LẬP với speech_admission_enabled (2
    # tracker riêng, không dùng chung). Mặc định TẮT — cần benchmark thêm trước khi bật
    # cho mọi call.
    turn_validator_enabled: bool = False
    turn_validator_min_snr_db: float = 3.0
    # Bug thật đã gặp: dùng WebRTC (`vad_provider`) làm classifier cho NoiseTracker khiến
    # noise_floor không được cập nhật đúng — WebRTC báo speech=True gần như LIÊN TỤC trên
    # noise phòng thuần (0 false-negative nhưng rất nhiều false-positive), nên
    # NoiseTracker._is_speech=False hiếm khi trigger cập nhật, SNR tính ra dao động hỗn
    # loạn (-150dB tới +34dB trên CHÍNH noise, không phải speech thật) — khiến
    # TurnValidator/SpeechAdmission thỉnh thoảng thấy SNR "cao giả" và cho qua turn giả.
    # Silero VAD (silero_vad_model_path) đã xác nhận qua benchmark thực nghiệm KHÔNG bị
    # lừa bởi cùng loại noise này (0/400 false-positive) — dùng riêng cho NoiseTracker,
    # tách biệt khỏi `vad_provider` (vẫn WebRTC cho turn-taking chính, chưa đổi mặc định).
    silero_vad_model_path: str = "src/speech/asr/vad/assets/silero_vad.onnx"

    # URL công khai để dựng audio_url trả về cho harness
    public_base_url: str = "http://localhost:8000"
    audio_dir: str = "temp/audio"
