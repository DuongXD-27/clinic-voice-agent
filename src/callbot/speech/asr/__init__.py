from callbot.speech.asr.base import ASRProvider
from callbot.speech.settings import SpeechSettings


def create_asr(settings: SpeechSettings) -> ASRProvider:
    if settings.asr_provider == "gemini":
        from callbot.speech.asr.gemini import GeminiASR

        return GeminiASR(api_key=settings.gemini_api_key, model=settings.gemini_asr_model)
    if settings.asr_provider == "phowhisper":
        from callbot.speech.asr.phowhisper import PhoWhisperASR

        return PhoWhisperASR(model=settings.phowhisper_model)
    if settings.asr_provider == "zipformer":
        from callbot.speech.asr.zipformer import ZipFormerASR, default_paths

        paths = default_paths()
        return ZipFormerASR(
            encoder_path=settings.zipformer_encoder_path or paths["encoder_path"],
            decoder_path=settings.zipformer_decoder_path or paths["decoder_path"],
            joiner_path=settings.zipformer_joiner_path or paths["joiner_path"],
            tokens_path=settings.zipformer_tokens_path or paths["tokens_path"],
        )
    raise ValueError(f"ASR provider không hỗ trợ: {settings.asr_provider}")


__all__ = ["ASRProvider", "create_asr"]
