from speech.asr.evidence import StabilityVerdict
from speech.audio.noise_tracker import NoiseEvidence
from speech.turn.validator import TurnValidator, ValidationDecision


def _evidence(snr_db: float) -> NoiseEvidence:
    return NoiseEvidence(rms=100.0, noise_floor=50.0, snr_db=snr_db)


def test_oscillating_stability_always_drops():
    validator = TurnValidator()
    decision = validator.evaluate(
        "đây", noise_evidence=_evidence(20.0), stability=StabilityVerdict.OSCILLATING
    )
    assert decision == ValidationDecision.DROP


def test_low_snr_short_text_drops():
    validator = TurnValidator(min_snr_db=6.0)
    decision = validator.evaluate(
        "tại", noise_evidence=_evidence(1.0), stability=StabilityVerdict.UNKNOWN
    )
    assert decision == ValidationDecision.DROP


def test_low_snr_long_text_does_not_drop_from_snr_alone():
    """SNR thấp không tự động DROP nếu text đủ dài — chỉ text NGẮN mới đáng ngờ (khớp
    mẫu quan sát thực tế: hallucination trên noise luôn ra 1 từ ngắn)."""
    validator = TurnValidator(min_snr_db=6.0)
    decision = validator.evaluate(
        "tôi muốn đổi lịch khám",
        noise_evidence=_evidence(1.0),
        stability=StabilityVerdict.UNKNOWN,
    )
    assert decision != ValidationDecision.DROP


def test_converging_stability_accepts():
    validator = TurnValidator()
    decision = validator.evaluate(
        "tôi muốn đổi lịch",
        noise_evidence=_evidence(20.0),
        stability=StabilityVerdict.CONVERGING,
    )
    assert decision == ValidationDecision.ACCEPT


def test_unknown_stability_without_evidence_waits():
    validator = TurnValidator()
    decision = validator.evaluate("có", noise_evidence=None, stability=StabilityVerdict.UNKNOWN)
    assert decision == ValidationDecision.WAIT


def test_no_noise_evidence_skips_snr_check():
    validator = TurnValidator()
    decision = validator.evaluate("tại", noise_evidence=None, stability=StabilityVerdict.UNKNOWN)
    assert decision == ValidationDecision.WAIT


def test_extra_kwargs_for_future_state_are_accepted_but_unused():
    """state/expected_input chưa có logic thật (ngoài phạm vi đợt này) nhưng interface
    phải chấp nhận được — không raise TypeError khi caller truyền vào."""
    validator = TurnValidator()
    decision = validator.evaluate(
        "có",
        noise_evidence=_evidence(20.0),
        stability=StabilityVerdict.CONVERGING,
        state="AWAITING_CONFIRMATION",
        expected_input="CONFIRMATION",
    )
    assert decision == ValidationDecision.ACCEPT


def test_low_confidence_single_word_noise_is_dropped_but_short_answers_are_kept() -> None:
    """Đập bàn -> "ÔNG" 0,28; nhiễu -> "ĐÂY" 0,31. Câu trả lời thật kém chắc vẫn giữ."""
    validator = TurnValidator()
    assert validator.evaluate("ÔNG", confidence=0.28) == ValidationDecision.DROP
    assert validator.evaluate("ĐÂY", confidence=0.31) == ValidationDecision.DROP
    for answer in ("KHÔNG", "VÂNG", "Ừ", "ĐÚNG RỒI", "CÓ Ạ", "Ô KÊ", "KHÔNG ĐƯỢC"):
        assert validator.evaluate(answer, confidence=0.3) != ValidationDecision.DROP, answer
    # Đủ chắc chắn hoặc câu dài: luật này không áp dụng.
    assert validator.evaluate("ÔNG", confidence=0.8) != ValidationDecision.DROP
    assert validator.evaluate("TÔI MUỐN ĐỔI LỊCH", confidence=0.3) != ValidationDecision.DROP
