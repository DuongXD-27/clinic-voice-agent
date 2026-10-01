"""Bundle speech (ASR/TTS/audio storage) cho đường HTTP `mode="audio"` (§4.1.2).

Sống ngoài `callbot/`: callbot chỉ lo text và nghiệp vụ, không biết khái niệm audio.
Tầng transport của callbot chỉ nối bundle này vào request.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import AsyncIterator, Callable, Optional, Protocol

from inference.asr import create_asr_gateway
from inference.tts import TTSGateway, create_tts_gateway
from speech.asr.evidence import TranscriptEvidenceTracker
from speech.asr.pipeline import STTPipeline
from speech.asr.recognizer import Recognizer, SpeechRecognizer
from speech.asr.vad.async_stream import AsyncStreamingVAD
from speech.asr.vad.base import FrameClassifier
from speech.asr.vad.energy import EnergyFrameClassifier
from speech.asr.vad.shared import SharedSpeechDetector
from speech.asr.vad.streaming import StreamingVAD
from speech.audio.loader import load_from_url
from speech.audio.noise_tracker import NoiseTracker
from speech.audio.storage import AudioArtifactStore
from speech.diagnostics import ProbabilityProbe
from speech.settings import SpeechSettings
from speech.turn.validator import TurnValidator
from speech.types import AudioSegment

logger = logging.getLogger(__name__)


class Synthesizer(Protocol):
    name: str

    def synthesize(self, text: str) -> Optional[AudioSegment]: ...


class SpeechSynthesizer:
    """Bọc TTS gateway (PCM của provider) thành `AudioSegment` của miền speech."""

    def __init__(self, gateway: TTSGateway) -> None:
        self._gateway = gateway
        self._last_stream_result = None

    @property
    def last_stream_result(self):
        return self._last_stream_result

    @property
    def name(self) -> str:
        return self._gateway.provider_name

    @property
    def model(self) -> str:
        return self._gateway.model

    @property
    def stream_sample_rate(self) -> int:
        return getattr(self._gateway.provider, "stream_sample_rate", 24_000)

    def synthesize(self, text: str) -> Optional[AudioSegment]:
        result = self._gateway.synthesize(text)
        if result is None:
            return None
        return AudioSegment(
            pcm=result.pcm,
            sample_rate=result.sample_rate,
            provider_actual=result.provider_actual,
            voice=result.voice,
            ttfa_ms=result.ttfa_ms,
            fallback_used=result.fallback_used,
        )

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """Stream when supported; use the gateway's fallback for sync-only providers."""
        self._last_stream_result = None
        provider = self._gateway.provider
        stream = getattr(provider, "synthesize_stream", None)
        if stream is not None:
            async for chunk in stream(text):
                yield chunk
            return

        result = await asyncio.to_thread(self._gateway.synthesize, text)
        self._last_stream_result = result
        if result is None:
            return
        pcm = result.pcm
        if result.sample_rate != self.stream_sample_rate:
            from speech.audio.codec import resample

            pcm = resample(pcm, result.sample_rate, self.stream_sample_rate)
        yield pcm

    async def cancel(self) -> None:
        cancel = getattr(self._gateway.provider, "cancel", None)
        if cancel is not None:
            await cancel()


@dataclass
class SpeechBundle:
    asr: Recognizer
    tts: Synthesizer
    audio_store: AudioArtifactStore
    # Seam cho test — mặc định tải thật qua HTTP như harness gửi.
    audio_loader: Callable[[str], AudioSegment] = load_from_url


def build_speech_bundle(settings: SpeechSettings) -> SpeechBundle:
    asr = SpeechRecognizer(create_asr_gateway(settings.asr_provider))
    tts_gateway = create_tts_gateway(settings.tts_provider, fallback=settings.tts_fallback_provider)
    tts = SpeechSynthesizer(tts_gateway)
    backup = tts_gateway.fallback
    logger.info(
        "ASR %s (%s), TTS %s (%s), TTS fallback %s",
        asr.name,
        asr.model,
        tts.name,
        tts.model,
        f"{backup.provider_name} ({backup.model})" if backup else "none",
    )
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
        # VAD, ASR endpoint, Validator) cần instance độc lập (xem docstring
        # speech/asr/vad/silero.py).
        return _build_noise_classifier(settings)
    return EnergyFrameClassifier(settings.vad_rms_threshold)


def _build_noise_classifier(settings: SpeechSettings) -> FrameClassifier:
    """Dùng cho NoiseTracker (evidence của TurnValidator) — LUÔN Silero VAD, không
    đọc `vad_provider` trực tiếp (bug thật đã gặp khi `vad_provider=webrtc`: WebRTC báo
    speech=True gần như liên tục trên noise phòng thuần, khiến noise_floor không cập
    nhật đúng và SNR dao động hỗn loạn, xem docstring `SpeechSettings.silero_vad_model_path`).
    Khi `vad_provider=silero`, `_build_vad_classifier()` cũng gọi hàm này (instance riêng
    mỗi lần, xem đó) — NoiseTracker vẫn luôn dùng Silero dù main VAD là gì."""
    from speech.asr.vad.silero import SileroVadClassifier

    return SileroVadClassifier(
        settings.silero_vad_model_path,
        sample_rate=settings.sample_rate,
        min_silence_ms=settings.silero_min_silence_ms,
    )


def _build_detector_probe(settings: SpeechSettings) -> Optional[ProbabilityProbe]:
    """Silero thô chạy trong bộ phân loại dùng chung, mỗi frame một lần: chẩn đoán và pre-speech
    lùi theo giọng của ASR cùng đọc. Có trạng thái nên mỗi bundle (mỗi cuộc gọi) một bản."""
    if not (settings.speech_diagnostics_probe or settings.asr_voice_lookback_ms):
        return None
    from speech.asr.vad.silero_probe import build_probe

    probe = build_probe(settings.silero_vad_model_path, settings.sample_rate)
    if probe is None and settings.asr_voice_lookback_ms:
        logger.warning("speech_bundle: không có Silero probe, tắt asr_voice_lookback_ms")
    return probe


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
    detector = (
        SharedSpeechDetector(
            _build_noise_classifier(settings), probe=_build_detector_probe(settings)
        )
        if settings.speech_shared_detector
        else None
    )
    async_classifier = detector.view() if detector else _build_vad_classifier(settings)
    # ASR endpointing cần classifier riêng thứ 3: WebRTC/Silero đều có state nội bộ,
    # không được cho hai consumer đồng thời dùng chung một instance (trừ khi dùng chung
    # detector — view() không có state, chỉ đọc kết quả _fanout đã tính).
    asr_endpoint_classifier = detector.view() if detector else _build_vad_classifier(settings)
    vad = StreamingVAD(sync_classifier, end_silence_ms=settings.vad_end_silence_ms)
    async_vad = AsyncStreamingVAD(async_classifier, end_silence_ms=settings.vad_end_silence_ms)
    asr = asr or SpeechRecognizer(create_asr_gateway(settings.asr_provider))
    asr_stream_options: dict[str, object] = {
        "audio_sample_rate": settings.sample_rate,
        "silence_classifier": asr_endpoint_classifier,
        "end_silence_ms": settings.vad_end_silence_ms,
    }
    if settings.asr_voice_lookback_ms and detector is not None and detector.has_probe:
        asr_stream_options["voice_probability"] = detector.probability
        asr_stream_options["voice_lookback_ms"] = settings.asr_voice_lookback_ms
    stt_pipeline = STTPipeline(
        asr,
        vad,
        settings.sample_rate,
        async_vad=async_vad,
        queue_max_frames=queue_max_frames,
        barge_in_preroll_frames=max(1, barge_in_preroll_ms // frame_ms),
        asr_stream_options=asr_stream_options,
        speech_detector=detector,
    )
    tts = SpeechSynthesizer(
        create_tts_gateway(settings.tts_provider, fallback=settings.tts_fallback_provider)
    )

    validator = None
    evidence_tracker = None
    noise_tracker = None
    noise_classifier = None
    if settings.turn_validator_enabled:
        validator = TurnValidator(min_snr_db=settings.turn_validator_min_snr_db)
        evidence_tracker = TranscriptEvidenceTracker()
        noise_tracker = NoiseTracker()
        # Classifier riêng (không dùng chung detector): Silero, không phải
        # _build_vad_classifier/WebRTC — xem _build_noise_classifier.
        noise_classifier = detector.view() if detector else _build_noise_classifier(settings)

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
