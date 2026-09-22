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
