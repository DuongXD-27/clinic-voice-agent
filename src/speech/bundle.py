"""Bundle speech (ASR/TTS/audio storage) cho đường HTTP `mode="audio"` (§4.1.2).

Sống ngoài `callbot/`: callbot chỉ lo text và nghiệp vụ, không biết khái niệm audio.
Tầng transport của callbot chỉ nối bundle này vào request.
"""

import logging
from dataclasses import dataclass
from typing import Callable

from inference.asr import create_asr_gateway
from inference.tts import create_tts_gateway
from speech.asr.recognizer import Recognizer, SpeechRecognizer
from speech.audio.loader import load_from_url
from speech.settings import SpeechSettings
from speech.tts.storage import AudioArtifactStore
from speech.tts.synthesizer import SpeechSynthesizer, Synthesizer
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
