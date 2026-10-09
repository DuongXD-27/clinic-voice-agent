"""Lắp các thành phần speech cho hai đường:

- HTTP `mode="audio"` (`build_speech_bundle`): mỗi lượt là một clip, ASR decode cả clip.
- LiveKit (`build_streaming_bundle`): audio liên tục, qua STTPipeline (VAD + ASR + chốt lượt).

Sống ngoài `callbot/`: callbot chỉ lo text và nghiệp vụ, không biết khái niệm audio.
"""

import asyncio
import logging
import time
from contextlib import aclosing
from dataclasses import dataclass
from typing import AsyncIterator, Optional, Protocol

from inference.asr import create_asr_gateway
from inference.tts import TTSGateway, create_tts_gateway
from inference.tts.base import StreamHandle, TTSStreamInfo
from speech.asr.pipeline import STTPipeline
from speech.asr.recognizer import Recognizer, SpeechRecognizer
from speech.asr.vad.async_stream import AsyncStreamingVAD
from speech.asr.vad.base import FrameClassifier
from speech.asr.vad.energy import EnergyFrameClassifier
from speech.asr.vad.shared import SharedSpeechDetector
from speech.audio.storage import AudioArtifactStore
from speech.settings import SpeechSettings
from speech.tts.static_cache import StaticAudioCache, create_static_cache
from speech.turn.controller import TurnController
from speech.turn.evidence import TurnEvidence
from speech.turn.validator import TurnValidator
from speech.types import AudioSegment

logger = logging.getLogger(__name__)


class Synthesizer(Protocol):
    name: str

    def synthesize(self, text: str) -> Optional[AudioSegment]: ...


@dataclass
class _SynthesizerStream(StreamHandle):
    cached: bool = False
    info: TTSStreamInfo | None = None


class SpeechSynthesizer:
    """Bọc TTS gateway (PCM của provider) thành `AudioSegment` của miền speech."""

    def __init__(self, gateway: TTSGateway, static_cache: StaticAudioCache | None = None) -> None:
        self._gateway = gateway
        self._static_cache = static_cache
        self._stream: _SynthesizerStream | None = None

    @property
    def static_cache(self) -> StaticAudioCache | None:
        return self._static_cache

    @property
    def last_stream_result(self):
        return self._stream.info if self._stream is not None else None

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
        if self._static_cache is not None:
            cached = self._static_cache.lookup(text)
            if cached is not None:
                return cached
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
        """Phát qua gateway (có dự phòng), ở tần số của track LiveKit (`stream_sample_rate`)."""
        stream = _SynthesizerStream()
        self._stream = stream
        track_rate = self.stream_sample_rate
        started = time.perf_counter()
        cached = self._static_cache.lookup(text) if self._static_cache is not None else None
        if cached is not None and cached.sample_rate == track_rate:
            stream.cached = True
            stream.info = TTSStreamInfo(
                provider_actual=cached.provider_actual,
                voice=cached.voice,
                sample_rate=cached.sample_rate,
                cache_hit=True,
                cache_key=cached.cache_key,
                catalog_version=cached.catalog_version,
                billed_characters=0,
            )
            chunk_bytes = track_rate * 20 // 1000 * 2
            for offset in range(0, len(cached.pcm), chunk_bytes):
                # Give cancellation/new-turn tasks a chance before emitting each PCM frame.
                await asyncio.sleep(0)
                if stream.cancelled:
                    return
                if stream.info.ttfa_ms is None:
                    stream.info.ttfa_ms = (time.perf_counter() - started) * 1000
                yield cached.pcm[offset : offset + chunk_bytes]
            return
        # Chunk luôn là PCM16 (Vbee xin `pcm`, ElevenLabs từ chối mọi format không phải
        # `pcm_*` lúc khởi tạo), nên chỉ còn tần số có thể lệch.
        # Provider thực tế (vd. dự phòng) khác tần số track: gom rồi resample một lần ở cuối.
        # Resample từng chunk rời sẽ có tiếng tách ở chỗ nối. Cấu hình hiện tại Vbee và
        # ElevenLabs cùng 8 kHz nên nhánh này không chạy.
        held = bytearray()
        held_rate = track_rate
        async with aclosing(self._gateway.synthesize_stream(text)) as chunks:
            async for chunk in chunks:
                info = self._gateway.last_stream
                stream.info = info
                if stream.cancelled:
                    return
                if info is not None and info.sample_rate != track_rate:
                    held.extend(chunk)
                    held_rate = info.sample_rate
                    continue
                yield chunk
        if self._stream is stream:
            stream.info = self._gateway.last_stream
        if held and not stream.cancelled:
            from speech.audio.codec import resample

            yield resample(bytes(held), held_rate, track_rate)

    async def cancel(self) -> None:
        stream = self._stream
        if stream is not None:
            stream.cancelled = True
        if stream is None or not stream.cached:
            await self._gateway.cancel()

    def close(self) -> None:
        self._gateway.close()

    async def aclose(self) -> None:
        await self._gateway.aclose()


@dataclass
class SpeechBundle:
    asr: Recognizer
    tts: Synthesizer
    audio_store: AudioArtifactStore


def build_speech_bundle(settings: SpeechSettings) -> SpeechBundle:
    asr = SpeechRecognizer(create_asr_gateway(settings.asr_provider))
    tts_gateway = create_tts_gateway(settings.tts_provider, fallback=settings.tts_fallback_provider)
    tts = SpeechSynthesizer(tts_gateway, create_static_cache(tts_gateway))
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
    """Mọi thành phần speech của MỘT cuộc gọi LiveKit (đều có trạng thái, không dùng chung)."""

    stt_pipeline: STTPipeline
    turn_controller: TurnController
    tts: SpeechSynthesizer
    # None khi turn_validator_enabled=False. CallBridge dùng lại cho InterruptionController.
    validator: Optional[TurnValidator] = None


def build_streaming_bundle(
    settings: SpeechSettings,
    *,
    sample_rate: int,
    frame_ms: int,
    input_queue_ms: int,
    asr_queue_ms: int,
    barge_in_preroll_ms: int,
    asr: Optional[Recognizer] = None,
) -> StreamingSpeechBundle:
    """Đường LiveKit (transports/livekit/worker.py). Đường HTTP dùng `build_speech_bundle`.

    `sample_rate`, `frame_ms`, `*_queue_ms`, `barge_in_preroll_ms`: lấy từ LiveKitSettings
    (config/livekit.yaml), không có mặc định ở đây. Một bộ phân loại theo `vad_provider`, phân
    loại mỗi frame đúng một lần, dùng chung cho VAD chính và bộ chốt câu của ASR.
    """
    queue_max_frames = max(1, input_queue_ms // frame_ms)
    asr_queue_max_frames = max(1, asr_queue_ms // frame_ms)
    preroll_frames = max(1, barge_in_preroll_ms // frame_ms)
    # Frame còn nằm trong hàng đợi VAD/ASR hoặc pre-roll phải còn kết quả khi được đọc lại.
    detector = SharedSpeechDetector(
        _build_classifier(settings, sample_rate),
        capacity=queue_max_frames + asr_queue_max_frames + preroll_frames,
    )
    asr = asr or SpeechRecognizer(create_asr_gateway(settings.asr_provider))
    validator = None
    evidence = None
    if settings.turn_validator_enabled:
        validator = TurnValidator(min_snr_db=settings.turn_validator_min_snr_db)
        # SNR cần Silero (xem speech/turn/evidence.py); dùng lại detector nếu đã là Silero.
        evidence = TurnEvidence(
            detector.view()
            if settings.vad_provider == "silero"
            else _build_silero(settings, sample_rate),
            frame_ms=frame_ms,
        )
    stt_pipeline = STTPipeline(
        asr,
        AsyncStreamingVAD(detector.view(), end_silence_ms=settings.vad_end_silence_ms),
        sample_rate=sample_rate,
        detector=detector,
        evidence=evidence,
        asr_stream_options={
            "audio_sample_rate": sample_rate,
            "silence_classifier": detector.view(),
            "end_silence_ms": settings.vad_end_silence_ms,
        },
        queue_max_frames=queue_max_frames,
        asr_queue_max_frames=asr_queue_max_frames,
        barge_in_preroll_frames=preroll_frames,
    )
    turn_controller = TurnController(
        min_speech_ms=settings.turn_min_speech_ms,
        max_wait_after_vad_end_ms=settings.turn_max_wait_after_vad_end_ms,
        max_wait_for_asr_ms=settings.turn_max_wait_for_asr_ms,
        post_bot_guard_ms=settings.turn_post_bot_guard_ms,
        validator=validator,
    )
    tts_gateway = create_tts_gateway(settings.tts_provider, fallback=settings.tts_fallback_provider)
    tts = SpeechSynthesizer(tts_gateway, create_static_cache(tts_gateway))
    return StreamingSpeechBundle(
        stt_pipeline=stt_pipeline, turn_controller=turn_controller, tts=tts, validator=validator
    )


def _build_classifier(settings: SpeechSettings, sample_rate: int) -> FrameClassifier:
    if settings.vad_provider == "silero":
        return _build_silero(settings, sample_rate)
    if settings.vad_provider == "webrtc":
        from speech.asr.vad.webrtc import WebRtcVadClassifier

        return WebRtcVadClassifier(
            aggressiveness=settings.vad_webrtc_aggressiveness, sample_rate=sample_rate
        )
    return EnergyFrameClassifier(settings.vad_rms_threshold)


def _build_silero(settings: SpeechSettings, sample_rate: int) -> FrameClassifier:
    from speech.asr.vad.silero import SileroVadClassifier

    return SileroVadClassifier(
        settings.silero_vad_model_path,
        sample_rate=sample_rate,
        min_silence_ms=settings.silero_min_silence_ms,
    )


def warm_up(asr: Recognizer) -> None:
    """Buộc ASR load model (vd. ZipFormer ~1.8s lần đầu) trước khi nhận traffic thật.

    Không để lượt đầu tiên của cuộc gọi đầu tiên gánh chi phí này trong ngân sách
    8 giây/lượt (§4.1.2). Provider chỉ có `stream()` (vd. elevenlabs_realtime) raise
    `NotImplementedError` có chủ ý — bỏ qua. Lỗi khác ném ra, nơi gọi tự quyết có chặn
    khởi động hay không.
    """
    try:
        asr.transcribe(AudioSegment(pcm=b"\x00\x00" * 1600, sample_rate=asr.input_sample_rate))
    except NotImplementedError:
        pass
