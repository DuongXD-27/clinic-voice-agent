import math

import numpy as np
import pytest

from speech.asr.vad import EnergyFrameClassifier
from speech.audio.preprocess import (
    detect_speech_frames,
    estimate_snr_db,
    measure_level,
    normalize_gain,
    remove_dc,
    speech_regions,
    split_long_regions,
)

RATE = 16_000


def _sine(amplitude: float, seconds: float = 1.0, offset: float = 0.0) -> np.ndarray:
    t = np.arange(int(RATE * seconds)) / RATE
    return offset + amplitude * np.sin(2 * math.pi * 440 * t)


def _pcm(samples: np.ndarray) -> bytes:
    return np.clip(np.round(samples), -32768, 32767).astype(np.int16).tobytes()


def _values(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float64)


def test_remove_dc_centers_signal() -> None:
    centered = _values(remove_dc(_pcm(_sine(3000, offset=1500))))
    assert abs(centered.mean()) < 1


def test_measure_level_of_silence_is_undefined() -> None:
    stats = measure_level(b"\x00\x00" * RATE, RATE)
    assert (stats.peak_dbfs, stats.speech_rms_dbfs, stats.clipping_ratio) == (None, None, 0.0)


def test_measure_level_reports_clipping() -> None:
    stats = measure_level(_pcm(_sine(60_000)), RATE)
    assert stats.peak_dbfs == pytest.approx(0, abs=0.01)
    assert stats.clipping_ratio > 0.3


def test_quiet_file_is_boosted_towards_target() -> None:
    pcm = _pcm(_sine(300))  # RMS ~ -43.8 dBFS
    boosted, gain_db = normalize_gain(pcm, measure_level(pcm, RATE))

    assert gain_db == pytest.approx(17.8, abs=0.2)
    assert measure_level(boosted, RATE).speech_rms_dbfs == pytest.approx(-26, abs=0.3)


def test_gain_is_capped_at_20_db() -> None:
    pcm = _pcm(_sine(30))
    _, gain_db = normalize_gain(pcm, measure_level(pcm, RATE))
    assert gain_db == pytest.approx(20.0)


def test_normal_level_file_is_untouched() -> None:
    pcm = _pcm(_sine(3000))  # ~ -20.8 dBFS: đủ lớn
    assert normalize_gain(pcm, measure_level(pcm, RATE)) == (pcm, 0.0)


def test_gain_never_creates_clipping() -> None:
    samples = _sine(300)
    samples[100] = 30_000  # một xung gần kịch trần
    pcm = _pcm(samples)
    boosted, gain_db = normalize_gain(pcm, measure_level(pcm, RATE))
    assert (boosted, gain_db) == (pcm, 0.0)


def test_detect_speech_frames_follows_energy() -> None:
    pcm = _pcm(np.concatenate([np.zeros(RATE), _sine(8000), np.zeros(RATE)]))
    flags = detect_speech_frames(pcm, RATE, EnergyFrameClassifier(500))

    assert len(flags) == 100
    assert sum(flags) in (33, 34)


def test_speech_regions_merge_close_speech_and_pad() -> None:
    flags = [False] * 200
    for start, end in ((50, 60), (70, 80), (150, 160)):
        flags[start:end] = [True] * (end - start)

    # 1500-1800 và 2100-2400 cách 300 ms -> một câu; 4500-4800 tách riêng
    assert speech_regions(flags, 6000) == [(500, 2700), (3500, 5100)]


def test_speech_regions_merge_when_padding_overlaps() -> None:
    flags = [False] * 100
    flags[10:20] = [True] * 10  # 300-600 ms
    flags[45:50] = [True] * 5  # 1350-1500 ms: cách 750 ms nhưng phần đệm chồng lên

    assert speech_regions(flags, 3000) == [(0, 1800)]


def test_long_region_is_split_at_quietest_frame() -> None:
    rng = np.random.default_rng(0)
    samples = rng.normal(0, 3000, RATE * 70)
    for dip_ms in (22_020, 45_000):  # frame 734 và frame 1500 im hẳn
        samples[dip_ms * 16 : (dip_ms + 30) * 16] = 0

    pieces = split_long_regions([(0, 70_000)], _pcm(samples), RATE, max_ms=30_000)

    assert pieces == [(0, 22_020), (22_020, 45_000), (45_000, 70_000)]


def test_split_never_exceeds_max_length() -> None:
    pcm = _pcm(np.random.default_rng(1).normal(0, 3000, RATE * 100))
    pieces = split_long_regions([(500, 99_500)], pcm, RATE, max_ms=30_000)

    assert pieces[0][0] == 500 and pieces[-1][1] == 99_500
    assert all(end - start <= 30_000 for start, end in pieces)
    assert all(a[1] == b[0] for a, b in zip(pieces, pieces[1:], strict=False))


def test_snr_uses_frames_outside_regions_as_noise() -> None:
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 100, RATE * 3)
    speech = noise.copy()
    speech[RATE : 2 * RATE] += _sine(3000)
    flags = [False] * 100
    flags[34:66] = [True] * 32

    snr = estimate_snr_db(_pcm(speech), RATE, flags, [(1000, 2000)])

    expected = 20 * math.log10(math.sqrt(3000**2 / 2 + 100**2) / 100)
    assert snr == pytest.approx(expected, abs=1.0)


def test_snr_is_undefined_on_digital_silence_background() -> None:
    pcm = _pcm(np.concatenate([np.zeros(RATE), _sine(3000), np.zeros(RATE)]))
    flags = [False] * 33 + [True] * 34 + [False] * 33
    assert estimate_snr_db(pcm, RATE, flags, [(1000, 2000)]) is None
