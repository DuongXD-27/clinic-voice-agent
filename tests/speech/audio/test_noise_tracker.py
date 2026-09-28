import numpy as np
import pytest

from speech.audio.noise_tracker import NoiseTracker


def _frame(amplitude: float, n: int = 240) -> bytes:
    samples = np.full(n, amplitude, dtype=np.int16)
    return samples.tobytes()


def test_snr_high_when_speech_much_louder_than_floor():
    tracker = NoiseTracker(initial_floor=50.0)
    evidence = tracker.observe(_frame(5000), is_speech=True)
    assert evidence.snr_db > 20


def test_snr_low_when_frame_close_to_floor():
    tracker = NoiseTracker(initial_floor=500.0)
    evidence = tracker.observe(_frame(500), is_speech=True)
    assert evidence.snr_db == pytest.approx(0.0, abs=0.5)


def test_noise_floor_only_updates_on_non_speech():
    tracker = NoiseTracker(initial_floor=50.0, floor_alpha=0.5)
    tracker.observe(_frame(5000), is_speech=True)
    assert tracker.observe(_frame(0), is_speech=False).noise_floor < 50.0

    tracker2 = NoiseTracker(initial_floor=50.0, floor_alpha=0.5)
    evidence = tracker2.observe(_frame(5000), is_speech=True)
    assert evidence.noise_floor == 50.0


def test_noise_floor_tracks_rising_noise():
    tracker = NoiseTracker(initial_floor=50.0, floor_alpha=0.5)
    for _ in range(20):
        evidence = tracker.observe(_frame(300), is_speech=False)
    assert evidence.noise_floor == pytest.approx(300.0, rel=0.05)


def test_empty_frame_does_not_crash():
    tracker = NoiseTracker()
    evidence = tracker.observe(b"", is_speech=False)
    assert evidence.rms == 0.0


def test_peek_does_not_update_floor():
    tracker = NoiseTracker(initial_floor=50.0, floor_alpha=0.5)
    evidence = tracker.peek(_frame(0))

    assert evidence.noise_floor == 50.0
    # Gọi lại peek() với cùng input phải ra cùng kết quả — chứng tỏ floor chưa đổi.
    assert tracker.peek(_frame(0)).noise_floor == 50.0


def test_commit_floor_applies_evidence_rms():
    tracker = NoiseTracker(initial_floor=50.0, floor_alpha=0.5)
    evidence = tracker.peek(_frame(0))
    tracker.commit_floor(evidence)

    assert tracker.peek(_frame(0)).noise_floor == pytest.approx(25.0)


def test_peek_then_no_commit_leaves_floor_unchanged_even_for_loud_frame():
    """Mô phỏng đúng bug Speech Admission đã gặp: frame low_snr/too_short (có thể vẫn là
    speech thật) không được phép kéo floor lên nếu caller không tự gọi commit_floor()."""
    tracker = NoiseTracker(initial_floor=50.0, floor_alpha=0.5)
    tracker.peek(_frame(5000))  # "REJECT" giả định — caller CHỦ Ý không commit

    assert tracker.peek(_frame(0)).noise_floor == 50.0
