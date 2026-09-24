import pytest

pytest.importorskip("rapidfuzz", reason="cần extra [speech] cài rapidfuzz")

from speech.asr.evidence import StabilityVerdict, TranscriptEvidenceTracker  # noqa: E402
from speech.types import TranscriptEvent  # noqa: E402


def _event(text: str) -> TranscriptEvent:
    return TranscriptEvent(text=text, is_final=False)


def test_first_event_is_unknown():
    tracker = TranscriptEvidenceTracker()
    assert tracker.observe(_event("t")) == StabilityVerdict.UNKNOWN


def test_converging_sequence_growing_prefix():
    tracker = TranscriptEvidenceTracker()
    tracker.observe(_event("t"))
    tracker.observe(_event("tôi"))
    tracker.observe(_event("tôi muốn"))
    verdict = tracker.observe(_event("tôi muốn đổi lịch"))
    assert verdict == StabilityVerdict.CONVERGING


def test_oscillating_sequence_short_unrelated_words():
    tracker = TranscriptEvidenceTracker(oscillation_repeat_threshold=2)
    tracker.observe(_event("đây"))
    tracker.observe(_event("tại"))
    tracker.observe(_event("có"))
    verdict = tracker.observe(_event("đây"))
    assert verdict == StabilityVerdict.OSCILLATING


def test_stable_repeated_single_word_is_not_oscillating():
    """User thật sự chỉ nói "có" liên tục (ví dụ xác nhận nhiều lần) không phải
    hallucination — chỉ dao động QUA LẠI GIỮA NHIỀU giá trị mới đáng ngờ."""
    tracker = TranscriptEvidenceTracker(oscillation_repeat_threshold=2)
    tracker.observe(_event("có"))
    tracker.observe(_event("có"))
    verdict = tracker.observe(_event("có"))
    assert verdict != StabilityVerdict.OSCILLATING


def test_empty_text_is_unknown():
    tracker = TranscriptEvidenceTracker()
    assert tracker.observe(_event("")) == StabilityVerdict.UNKNOWN


def test_reset_clears_window():
    tracker = TranscriptEvidenceTracker(oscillation_repeat_threshold=2)
    tracker.observe(_event("đây"))
    tracker.observe(_event("tại"))
    tracker.reset()
    assert tracker.observe(_event("đây")) == StabilityVerdict.UNKNOWN


def test_window_limits_history():
    tracker = TranscriptEvidenceTracker(window=2, oscillation_repeat_threshold=2)
    tracker.observe(_event("đây"))
    tracker.observe(_event("tại"))
    # window=2 -> "đây" đã bị đẩy ra khỏi lịch sử, chỉ còn "tại" + "có" -> không đủ lặp lại.
    verdict = tracker.observe(_event("có"))
    assert verdict != StabilityVerdict.OSCILLATING


if __name__ == "__main__":
    pytest.main([__file__])
