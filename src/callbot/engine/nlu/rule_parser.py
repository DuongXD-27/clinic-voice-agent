"""Baseline rule-based NLU — nhanh, rẻ, deterministic; LLM parser bổ sung cho ca khó."""

import re
from typing import Optional

from callbot.engine.nlu.normalizer import normalize_text, parse_dob
from callbot.engine.nlu.schema import Entities, Intent, NLUResult

# Thứ tự quan trọng: nhóm an toàn (clinical, human) được ưu tiên trước nghiệp vụ.
# TODO: mở rộng từ khoá từ trace thật; đo precision/recall trên test set của team.
_INTENT_KEYWORDS: list[tuple[Intent, tuple[str, ...]]] = [
    (Intent.CLINICAL_QUESTION, ("đau", "sốt", "thuốc", "triệu chứng", "khó thở", "chảy máu", "uống")),
    (Intent.REQUEST_HUMAN, ("nhân viên", "gặp người", "chuyển máy", "tổng đài viên")),
    (Intent.ABUSIVE, ("đồ ngu", "im đi", "cút")),
    (Intent.OUT_OF_SCOPE, ("bảo hiểm", "thanh toán", "hóa đơn", "chuyển tuyến", "đơn thuốc")),
    # Phủ định phải đứng trước CANCEL/RESCHEDULE: "không hủy" không phải là hủy (SF-05)
    (Intent.DENY, ("không hủy", "không huỷ", "đừng hủy", "đừng huỷ", "không đổi", "giữ nguyên", "giữ lịch")),
    (Intent.RESCHEDULE, ("đổi lịch", "đổi sang", "dời", "lùi lịch", "đổi giờ", "đổi ngày")),
    (Intent.CANCEL, ("hủy", "huỷ", "không đi được", "không đến được", "không khám nữa")),
    (Intent.BOOK, ("đặt lịch", "đăng ký khám", "muốn khám", "hẹn khám")),
    (Intent.CONFIRM_ATTENDANCE, ("sẽ đến", "sẽ đi", "tôi đến", "có đi", "có đến")),
    (Intent.DENY, ("không", "sai", "chưa", "thôi")),
    (Intent.AFFIRM, ("vâng", "dạ", "được", "đúng", "ừ", "ok", "đồng ý", "có")),
]

_PERIODS = {"sáng": "MORNING", "chiều": "AFTERNOON", "tối": "EVENING"}
_SLOT_INDEX = re.compile(r"(?:khung|giờ|lựa chọn|số)\s*(?:thứ\s*)?(\d)")


def _contains(text: str, keyword: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", text) is not None


class RuleBasedParser:
    def parse(self, text: str) -> NLUResult:
        normalized = normalize_text(text)
        return NLUResult(
            intent=self._detect_intent(normalized),
            entities=self._extract_entities(normalized),
            raw_text=text,
        )

    def _detect_intent(self, text: str) -> Intent:
        for intent, keywords in _INTENT_KEYWORDS:
            if any(_contains(text, k) for k in keywords):
                return intent
        return Intent.UNKNOWN

    def _extract_entities(self, text: str) -> Entities:
        entities = Entities(dob=parse_dob(text))
        entities.preferred_period = next(
            (value for word, value in _PERIODS.items() if _contains(text, word)), None
        )
        entities.slot_choice_index = _parse_slot_index(text)
        # TODO: preferred_date ("thứ hai tuần sau", "ngày 20"), cancel_reason
        return entities


def _parse_slot_index(text: str) -> Optional[int]:
    match = _SLOT_INDEX.search(text)
    return int(match.group(1)) if match else None
