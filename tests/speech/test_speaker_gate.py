import numpy as np

from speech.audio.speaker_gate import SpeakerGate

RATE = 16_000


CALLER, OTHER = 3000, -3000  # độ lệch DC đánh dấu giọng trong audio giả


def _embed(samples, sample_rate):
    """Embedding giả: giọng đoán theo dấu của trung bình đoạn (người gọi > 0, giọng khác < 0)."""
    vector = np.array([1.0, 0.0] if samples.mean() > 0 else [0.0, 1.0], dtype=np.float32)
    return vector


def _speech(*parts: tuple[int, float]) -> bytes:
    """Ghép các đoạn (giọng, giây): nhiễu + độ lệch DC của giọng đó."""
    rng = np.random.default_rng(0)
    chunks = [rng.normal(offset, 800, int(seconds * RATE)) for offset, seconds in parts]
    return np.concatenate(chunks).astype(np.int16).tobytes()


def _gate(enforce: bool = True) -> SpeakerGate:
    return SpeakerGate(_embed, enforce=enforce, threshold=0.2, min_speech_ms=2000)


def test_single_voice_turn_enrolls_then_other_voice_is_blocked() -> None:
    gate = _gate()

    assert gate.assess(_speech((CALLER, 3.0)), RATE, 3000).decision == "enroll"
    assert gate.assess(_speech((OTHER, 3.0)), RATE, 3000).decision == "block"
    assert gate.assess(_speech((CALLER, 3.0)), RATE, 3000).decision == "pass"


def test_mixed_voices_turn_is_not_used_as_the_caller_voice() -> None:
    """Điện thoại phát tin tức rồi người gọi nói trong cùng lượt: chưa lấy giọng mẫu."""
    gate = _gate()

    assert gate.assess(_speech((OTHER, 3.0), (CALLER, 3.0)), RATE, 6000).decision == "defer"
    assert not gate.enrolled
    assert gate.assess(_speech((CALLER, 3.0)), RATE, 3000).decision == "enroll"


def test_other_voice_before_the_caller_is_trimmed() -> None:
    gate = _gate()
    gate.assess(_speech((CALLER, 3.0)), RATE, 3000)

    verdict = gate.assess(_speech((OTHER, 3.0), (CALLER, 3.0)), RATE, 6000)

    assert verdict.decision == "trim"
    start, end = verdict.keep
    assert start >= 3 * RATE - RATE // 2 and end == 6 * RATE


def test_short_turns_are_never_judged() -> None:
    """Embedding của đoạn ngắn không tin cậy: "ừ", "có" luôn qua và không làm giọng mẫu."""
    gate = _gate()

    assert gate.assess(_speech((OTHER, 0.5)), RATE, 600).decision == "skip"
    assert gate.assess(_speech((OTHER, 3.0)), RATE, None).decision == "skip"
    assert not gate.enrolled


def test_log_mode_never_blocks() -> None:
    gate = _gate(enforce=False)
    gate.assess(_speech((CALLER, 3.0)), RATE, 3000)

    assert gate.allows(_speech((OTHER, 3.0)), RATE, 3000) is True


def test_missing_model_runs_without_gate(tmp_path, caplog) -> None:
    """Image Docker không có model speaker: worker vẫn dựng được pipeline, chỉ cảnh báo."""
    from speech.bundle import _build_speaker_gate
    from speech.settings import SpeechSettings

    settings = SpeechSettings(
        speaker_gate_mode="enforce",
        speaker_gate_model_path=str(tmp_path / "missing.onnx"),
        _env_file=None,
    )

    assert _build_speaker_gate(settings) is None
    assert "missing.onnx" in caplog.text


def test_short_other_voice_turn_is_blocked_once_the_caller_voice_is_known() -> None:
    """ "BẰNG QUY NHÁ" 1,6 s từ điện thoại cạnh mic: sau khi có giọng mẫu, lượt ngắn cũng được chấm."""
    gate = _gate()

    assert gate.assess(_speech((OTHER, 1.6)), RATE, 1600).decision == "skip"  # chưa có giọng mẫu
    gate.assess(_speech((CALLER, 3.0)), RATE, 3000)

    assert gate.assess(_speech((OTHER, 1.6)), RATE, 1600).decision == "block"
    assert gate.assess(_speech((CALLER, 1.6)), RATE, 1600).decision == "pass"
    assert gate.assess(_speech((CALLER, 0.6)), RATE, 600).decision == "skip"
