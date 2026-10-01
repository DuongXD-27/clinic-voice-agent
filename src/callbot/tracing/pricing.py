"""Optional, exact-match approved prices. Missing price or usage means unknown cost."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field

from appconfig import YamlSettings, yaml_config


class PricingSettings(YamlSettings):
    model_config = yaml_config("tracing.yaml", "pricing", populate_by_name=True)

    llm_model: str = Field(default="", validation_alias="TRACE_LLM_PRICE_MODEL")
    llm_input_usd_per_million: float | None = Field(
        default=None, ge=0, validation_alias="TRACE_LLM_INPUT_USD_PER_MILLION"
    )
    llm_output_usd_per_million: float | None = Field(
        default=None, ge=0, validation_alias="TRACE_LLM_OUTPUT_USD_PER_MILLION"
    )
    llm_cached_input_usd_per_million: float | None = Field(
        default=None, ge=0, validation_alias="TRACE_LLM_CACHED_INPUT_USD_PER_MILLION"
    )
    tts_provider: str = Field(default="", validation_alias="TRACE_TTS_PRICE_PROVIDER")
    tts_voice: str = Field(default="", validation_alias="TRACE_TTS_PRICE_VOICE")
    tts_usd_per_character: float | None = Field(
        default=None, ge=0, validation_alias="TRACE_TTS_USD_PER_CHARACTER"
    )
    stt_model: str = Field(default="", validation_alias="TRACE_STT_PRICE_MODEL")
    stt_usd_per_audio_minute: float | None = Field(
        default=None, ge=0, validation_alias="TRACE_STT_USD_PER_AUDIO_MINUTE"
    )


@lru_cache(maxsize=1)
def pricing() -> PricingSettings:
    return PricingSettings()


def llm_cost(
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    cached_tokens: int | None = None,
) -> float | None:
    try:
        cfg = pricing()
        if model != cfg.llm_model or input_tokens is None or output_tokens is None:
            return None
        if cfg.llm_input_usd_per_million is None or cfg.llm_output_usd_per_million is None:
            return None
        cached = cached_tokens or 0
        if cached > input_tokens:
            return None
        if cached and cfg.llm_cached_input_usd_per_million is None:
            return None
        return (
            (input_tokens - cached) * cfg.llm_input_usd_per_million
            + output_tokens * cfg.llm_output_usd_per_million
            + cached * (cfg.llm_cached_input_usd_per_million or 0)
        ) / 1_000_000
    except Exception:
        return None


def tts_cost(provider: str | None, voice: str | None, characters: int) -> float | None:
    try:
        cfg = pricing()
        if (
            provider != cfg.tts_provider
            or voice != cfg.tts_voice
            or cfg.tts_usd_per_character is None
        ):
            return None
        return characters * cfg.tts_usd_per_character
    except Exception:
        return None


def stt_cost(model: str | None, duration_ms: float | None) -> float | None:
    try:
        cfg = pricing()
        if model != cfg.stt_model or duration_ms is None or cfg.stt_usd_per_audio_minute is None:
            return None
        return duration_ms / 60_000 * cfg.stt_usd_per_audio_minute
    except Exception:
        return None
