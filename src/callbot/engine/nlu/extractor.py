"""Information Extraction: trích xuất intent, thực thể; chuẩn hoá & kiểm tra ràng buộc."""

from typing import Optional, Protocol

from callbot.engine.nlu.normalizer import normalize_text
from callbot.engine.nlu.schema import Intent, NLUResult
from callbot.engine.session.context import CallContext


class NLUParser(Protocol):
    def parse(self, text: str) -> NLUResult: ...


_GREETINGS = ("alo", "a lô", "xin chào", "chào", "ai đấy", "ai vậy")
_FILLERS = ("dạ", "vâng", "tên tôi là", "tôi tên là", "tôi là", "em là", "mình là")


class InformationExtractor:
    def __init__(self, parser: NLUParser, fallback: Optional[NLUParser] = None) -> None:
        self._parser = parser
        # TODO: LLM parser cho ca rule-based trả UNKNOWN (router theo độ khó — §6.3)
        self._fallback = fallback

    def extract(self, ctx: CallContext, text: str) -> NLUResult:
        result = self._parser.parse(text)
        if not result.understood and self._fallback is not None:
            result = self._fallback.parse(text)
        return self._apply_slot_context(ctx, result)

    def _apply_slot_context(self, ctx: CallContext, result: NLUResult) -> NLUResult:
        """Diễn giải theo câu bot vừa hỏi: đang hỏi tên thì câu trả lời là tên."""
        if ctx.state == "AWAITING_IDENTITY" and ctx.identity_step == "ASK_NAME":
            name = _extract_name_answer(result.raw_text)
            if name and result.intent in (Intent.UNKNOWN, Intent.AFFIRM):
                result.entities.full_name = name
                result.intent = Intent.UNKNOWN
        return result


def _extract_name_answer(text: str) -> Optional[str]:
    """Heuristic lấy tên từ câu trả lời. TODO: thay bằng NER / LLM structured output."""
    name = normalize_text(text).strip(" .,!?")
    for prefix in _FILLERS:
        if name.startswith(prefix):
            name = name[len(prefix) :].strip(" .,")
    if not name or name in _GREETINGS or any(c.isdigit() for c in name):
        return None
    if len(name.split()) < 2:
        return None
    return name
