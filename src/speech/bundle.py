"""Bundle speech (ASR/TTS/audio storage) cho đường HTTP `mode="audio"` (§4.1.2).

Sống ngoài `callbot/`: callbot chỉ lo text và nghiệp vụ, không biết khái niệm audio.
Tầng transport của callbot chỉ nối bundle này vào request.
"""

import logging
from dataclasses import dataclass
from typing import Callable, Optional

from inference.asr import create_asr_gateway
from inference.tts import create_tts_gateway
from speech.asr.evidence import TranscriptEvidenceTracker
from speech.asr.pipeline import STTPipeline
from speech.asr.recognizer import Recognizer, SpeechRecognizer
from speech.asr.vad.async_stream import AsyncStreamingVAD
from speech.asr.vad.base import FrameClassifier
from speech.asr.vad.energy import EnergyFrameClassifier
from speech.asr.vad.streaming import StreamingVAD
from speech.audio.loader import load_from_url
from speech.audio.noise_tracker import NoiseTracker
from speech.settings import SpeechSettings
from speech.tts.storage import AudioArtifactStore
from speech.tts.synthesizer import SpeechSynthesizer, Synthesizer
from speech.turn.validator import TurnValidator
from speech.types import AudioSegment

logger = logging.getLogger(__name__)


@dataclass
class SpeechBundle:
    asr: Recognizer
    tts: Synthesizer
    audio_store: AudioArtifactStore
    # Seam cho test — mặc định tải thật qua HTTP như harness gửi.
    audio_loader: Callable[[str], AudioSegment] = load_from_url


def build_speech_bundle(settings: SpeechSettings) -> SpeechBundle:
    asr = SpeechRecognizer(create_asr_gateway(settings.asr_provider))
    tts = SpeechSynthesizer(create_tts_gateway(settings.tts_provider))
    logger.info("ASR %s (%s), TTS %s (%s)", asr.name, asr.model, tts.name, tts.model)
    return SpeechBundle(
        asr=asr,
        tts=tts,
        audio_store=AudioArtifactStore(settings.audio_dir, settings.public_base_url),
    )


@dataclass
class StreamingSpeechBundle:
    stt_pipeline: STTPipeline
    tts: SpeechSynthesizer
    # Turn Validator (docs/reference/livekit-architecture.md §5.4, §6) — None khi
    # turn_validator_enabled=False (mặc định). worker.py truyền `validator` vào
    # TurnController(); call_bridge.py truyền evidence_tracker/noise_tracker/
    # noise_classifier vào stt_pipeline.stream() để cấp dữ liệu cho validator đó.
    validator: Optional[TurnValidator] = None
    evidence_tracker: Optional[TranscriptEvidenceTracker] = None
    noise_tracker: Optional[NoiseTracker] = None
    noise_classifier: Optional[FrameClassifier] = None


def _build_vad_classifier(settings: SpeechSettings) -> FrameClassifier:
    if settings.vad_provider == "webrtc":
        from speech.asr.vad.webrtc import WebRtcVadClassifier

        return WebRtcVadClassifier(
            aggressiveness=settings.vad_webrtc_aggressiveness, sample_rate=settings.sample_rate
        )
    if settings.vad_provider == "silero":
        # Cùng classifier dùng cho NoiseTracker (_build_noise_classifier) — nhưng đây là
        # instance RIÊNG, không share: SileroVadClassifier stateful, mỗi consumer (main
        # VAD, ASR endpoint, Admission, Validator) cần instance độc lập (xem docstring
        # speech/asr/vad/silero.py).
        return _build_noise_classifier(settings)
    return EnergyFrameClassifier(settings.vad_rms_threshold)


def _build_noise_classifier(settings: SpeechSettings) -> FrameClassifier:
    """Dùng cho NoiseTracker (Speech Admission + TurnValidator) — LUÔN Silero VAD, không
    đọc `vad_provider` trực tiếp (bug thật đã gặp khi `vad_provider=webrtc`: WebRTC báo
    speech=True gần như liên tục trên noise phòng thuần, khiến noise_floor không cập
    nhật đúng và SNR dao động hỗn loạn, xem docstring `SpeechSettings.silero_vad_model_path`).
    Khi `vad_provider=silero`, `_build_vad_classifier()` cũng gọi hàm này (instance riêng
    mỗi lần, xem đó) — NoiseTracker vẫn luôn dùng Silero dù main VAD là gì."""
    from speech.asr.vad.silero import SileroVadClassifier

    return SileroVadClassifier(settings.silero_vad_model_path, sample_rate=settings.sample_rate)


def build_streaming_bundle(
    settings: SpeechSettings,
    *,
    asr: Optional[Recognizer] = None,
    frame_ms: int = 30,
    queue_max_frames: int = 50,
    barge_in_preroll_ms: int = 500,
) -> StreamingSpeechBundle:
    """Bundle cho đường LiveKit streaming (transports/livekit/worker.py) — khác
    `build_speech_bundle` (HTTP batch `mode="audio"`): cần cả VAD sync/async cùng
    classifier và ASR provider có `stream()` (chỉ ZipFormer hỗ trợ hiện tại)."""
    # 2 instance riêng cho vad/async_vad (không share) — cả WebRtcVadClassifier lẫn
    # SileroVadClassifier đều stateful (xem docstring từng module), sync/async không được
    # cho hai consumer đồng thời dùng chung. `sync_classifier` trong thực tế chỉ phục vụ
    # `transcribe_segment()` (đường HTTP batch), `async_classifier` phục vụ `stream()`
    # (đường LiveKit) — không chạy đồng thời trên cùng 1 call, nhưng tách riêng để không
    # phụ thuộc giả định đó và tránh state cũ (buffer Silero chưa flush) rò từ lần gọi
    # trước sang lần sau.
    sync_classifier = _build_vad_classifier(settings)
    async_classifier = _build_vad_classifier(settings)
    # ASR endpointing cần classifier riêng thứ 3: WebRTC/Silero đều có state nội bộ,
    # không được cho hai consumer đồng thời dùng chung một instance.
    asr_endpoint_classifier = _build_vad_classifier(settings)
    vad = StreamingVAD(sync_classifier, end_silence_ms=settings.vad_end_silence_ms)
    async_vad = AsyncStreamingVAD(async_classifier, end_silence_ms=settings.vad_end_silence_ms)
    asr = asr or SpeechRecognizer(create_asr_gateway(settings.asr_provider))
    admission = None
    admission_classifier = None
    if settings.speech_admission_enabled:
        from speech.asr.admission import SpeechAdmission

        admission = SpeechAdmission(
            min_snr_db=settings.speech_admission_min_snr_db,
            min_speech_ms=settings.speech_admission_min_speech_ms,
        )
        # Classifier riêng thứ 3 — cùng lý do asr_endpoint_classifier ở trên, không share
        # instance stateful giữa 3 consumer (VAD chính, ASR endpoint, Admission). Silero
        # (không phải _build_vad_classifier/WebRTC) — xem _build_noise_classifier.
        admission_classifier = _build_noise_classifier(settings)
    stt_pipeline = STTPipeline(
        asr,
        vad,
        settings.sample_rate,
        async_vad=async_vad,
        queue_max_frames=queue_max_frames,
        barge_in_preroll_frames=max(1, barge_in_preroll_ms // frame_ms),
        asr_stream_options={
            "audio_sample_rate": settings.sample_rate,
            "silence_classifier": asr_endpoint_classifier,
            "end_silence_ms": settings.vad_end_silence_ms,
        },
        admission=admission,
        admission_classifier=admission_classifier,
    )
    tts = SpeechSynthesizer(create_tts_gateway(settings.tts_provider))

    validator = None
    evidence_tracker = None
    noise_tracker = None
    noise_classifier = None
    if settings.turn_validator_enabled:
        validator = TurnValidator(min_snr_db=settings.turn_validator_min_snr_db)
        evidence_tracker = TranscriptEvidenceTracker()
        noise_tracker = NoiseTracker()
        # Classifier riêng thứ 4 (độc lập Admission's admission_classifier) — TurnValidator
        # và Speech Admission là 2 tính năng tách biệt, không share tracker/state. Silero
        # (không phải _build_vad_classifier/WebRTC) — xem _build_noise_classifier.
        noise_classifier = _build_noise_classifier(settings)

    return StreamingSpeechBundle(
        stt_pipeline=stt_pipeline,
        tts=tts,
        validator=validator,
        evidence_tracker=evidence_tracker,
        noise_tracker=noise_tracker,
        noise_classifier=noise_classifier,
    )


def warm_up(bundle: SpeechBundle) -> None:
    """Buộc ASR load model (vd. ZipFormer ~1.8s lần đầu) trước khi nhận traffic thật.

    Không để lượt đầu tiên của cuộc gọi đầu tiên gánh chi phí này trong ngân sách
    8 giây/lượt (§4.1.2). Không fail startup nếu provider không warm-up được (vd.
    provider hosted cần API key chưa cấu hình) — chỉ log, mode=audio khi đó vẫn sẽ
    lỗi rõ ràng ở lượt gọi thật thay vì im lặng chặn app khởi động.
    """
    try:
        segment = AudioSegment(pcm=b"\x00\x00" * 1600, sample_rate=bundle.asr.input_sample_rate)
        bundle.asr.transcribe(segment)
    except Exception:
        logger.warning("Không warm-up được ASR provider %s", getattr(bundle.asr, "name", "?"))
