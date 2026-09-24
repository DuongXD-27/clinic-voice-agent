"""Bundle speech (ASR/TTS/audio storage) cho đường HTTP `mode="audio"` (§4.1.2).

Sống ngoài `callbot/`: callbot chỉ lo text và nghiệp vụ, không biết khái niệm audio.
Tầng transport của callbot chỉ nối bundle này vào request.
"""

import logging
from dataclasses import dataclass
from typing import Callable, Optional, Protocol

from inference.asr import create_asr_gateway
from inference.tts import TTSGateway, create_tts_gateway
from speech.asr.recognizer import Recognizer, SpeechRecognizer
from speech.audio.loader import load_from_url
from speech.audio.storage import AudioArtifactStore
from speech.settings import SpeechSettings
from speech.types import AudioSegment

logger = logging.getLogger(__name__)


class Synthesizer(Protocol):
    name: str

    def synthesize(self, text: str) -> Optional[AudioSegment]: ...


class SpeechSynthesizer:
    """Bọc TTS gateway (PCM của provider) thành `AudioSegment` của miền speech."""

    def __init__(self, gateway: TTSGateway) -> None:
        self._gateway = gateway

    @property
    def name(self) -> str:
        return self._gateway.provider_name

    @property
    def model(self) -> str:
        return self._gateway.model

    def synthesize(self, text: str) -> Optional[AudioSegment]:
        result = self._gateway.synthesize(text)
        if result is None:
            return None
        return AudioSegment(pcm=result.pcm, sample_rate=result.sample_rate)


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
