from typing import Optional

from callbot.engine.dialogue.llm.base import LLMClient, LLMReply, ToolCall
from callbot.engine.settings import EngineSettings


def create_llm(settings: EngineSettings) -> Optional[LLMClient]:
    if settings.llm_provider == "none":
        return None
    if settings.llm_provider == "gemini":
        from callbot.engine.dialogue.llm.gemini import GeminiLLM

        return GeminiLLM(api_key=settings.gemini_api_key, model=settings.gemini_llm_model)
    raise ValueError(f"LLM provider không hỗ trợ: {settings.llm_provider}")


__all__ = ["LLMClient", "LLMReply", "ToolCall", "create_llm"]
