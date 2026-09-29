import numpy as np
import pytest

from speech.audio.noise_tracker import NoiseEvidence, NoiseTracker, UtteranceEvidenceTracker


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


def _evidence(rms: float, floor: float = 10.0) -> NoiseEvidence:
    return NoiseEvidence(rms=rms, noise_floor=floor, snr_db=20 * np.log10(max(rms, 1e-6) / floor))


def test_utterance_evidence_keeps_speech_snr_through_trailing_silence():
    """Final ASR tới sau ~1 s im lặng: SNR phải là của câu vừa nói, không phải im lặng."""
    tracker = UtteranceEvidenceTracker(frame_ms=30, gap_ms=600, hold_ms=3000)
    for _ in range(10):
        tracker.observe(_evidence(1000.0), is_speech=True)
    for _ in range(40):  # 1,2 s im lặng
        result = tracker.observe(_evidence(1.0), is_speech=False)

    assert result.rms == pytest.approx(1000.0)
    assert result.snr_db == pytest.approx(60.0)  # nền = trung vị im lặng (rms 1)


def test_utterance_evidence_expires_after_hold():
    tracker = UtteranceEvidenceTracker(frame_ms=30, gap_ms=90, hold_ms=300)
    for _ in range(10):
        tracker.observe(_evidence(1000.0), is_speech=True)
    for _ in range(11):
        result = tracker.observe(_evidence(1.0), is_speech=False)

    assert result.snr_db == pytest.approx(-20.0)


def test_utterance_evidence_starts_new_segment_after_gap():
    """Câu nhỏ sau câu to không được thừa hưởng SNR của câu trước."""
    tracker = UtteranceEvidenceTracker(frame_ms=30, gap_ms=90, hold_ms=3000, onset_ms=0)
    for _ in range(10):
        tracker.observe(_evidence(1000.0), is_speech=True)
    for _ in range(3):
        tracker.observe(_evidence(1.0), is_speech=False)
    result = tracker.observe(_evidence(20.0), is_speech=True)

    assert result.rms == pytest.approx(20.0)


def test_utterance_evidence_passes_frame_evidence_before_any_speech():
    tracker = UtteranceEvidenceTracker()
    frame = _evidence(5.0)
    assert tracker.observe(frame, is_speech=False) is frame


def _run(tracker: UtteranceEvidenceTracker, noise: NoiseTracker, frames: list[tuple[float, bool]]):
    """Như pipeline: NoiseTracker đo từng frame rồi UtteranceEvidenceTracker tổng hợp."""
    result = None
    for amplitude, is_speech in frames:
        result = tracker.observe(noise.observe(_frame(amplitude), is_speech), is_speech)
    return result


def test_loud_onset_reported_late_by_vad_counts_as_speech_not_noise():
    """Hồi quy (cuộc gọi 2026-09-26, "hủy lịch"): Silero báo speech trễ ~270 ms đúng lúc phần
    to nhất của câu; phần đó từng bị tính vào nền (floor 145 -> 1337), SNR -3,2 dB, DROP."""
    frames = (
        [(150.0, False)] * 40  # nền
        + [(3500.0, False)] * 8  # đầu câu, Silero chưa báo speech
        + [(400.0, True)] * 20  # phần Silero gọi là speech
        + [(150.0, False)] * 20  # im lặng tới lúc ASR final
    )

    result = _run(UtteranceEvidenceTracker(), NoiseTracker(), frames)

    assert result.noise_floor == pytest.approx(150.0)
    assert result.snr_db > 15.0


def test_event_at_background_level_stays_low_snr():
    """Luật chống ảo giác vẫn giữ: âm thanh chỉ to ngang nền dao động (vd. giọng nền) phải
    ra SNR thấp — nền là trung vị, không phải chỗ lặng nhất."""
    background = [(100.0, False), (300.0, False)] * 50
    frames = background + [(220.0, True)] * 10 + [(200.0, False)] * 20

    result = _run(UtteranceEvidenceTracker(), NoiseTracker(), frames)

    assert result.snr_db < 3.0


def test_background_floor_follows_rising_noise():
    """Nhiễu môi trường tăng thật thì nền phải tăng theo, không kẹt ở mức cũ."""
    frames = [(50.0, False)] * 100 + [(400.0, False)] * 120 + [(800.0, True)] * 10

    result = _run(UtteranceEvidenceTracker(), NoiseTracker(), frames)

    assert result.noise_floor == pytest.approx(400.0)
    assert result.snr_db < 9.0
