import pytest

from speech.asr.admission import PreRollBuffer, SpeechAdmission
from speech.audio.noise_tracker import NoiseEvidence


def _evidence(snr_db: float) -> NoiseEvidence:
    return NoiseEvidence(rms=100.0, noise_floor=50.0, snr_db=snr_db)


def test_rejects_non_speech_frame():
    admission = SpeechAdmission()
    decision = admission.evaluate(
        is_speech=False, evidence=_evidence(20.0), speech_ms_so_far=500, already_admitted=False
    )
    assert decision.admit is False
    assert decision.reason == "no_speech"


def test_rejects_low_snr_new_candidate():
    admission = SpeechAdmission(min_snr_db=6.0)
    decision = admission.evaluate(
        is_speech=True, evidence=_evidence(2.0), speech_ms_so_far=500, already_admitted=False
    )
    assert decision.admit is False
    assert decision.reason == "low_snr"


def test_rejects_too_short_new_candidate():
    admission = SpeechAdmission(min_speech_ms=150)
    decision = admission.evaluate(
        is_speech=True, evidence=_evidence(20.0), speech_ms_so_far=30, already_admitted=False
    )
    assert decision.admit is False
    assert decision.reason == "too_short"


def test_admits_when_snr_and_duration_ok():
    admission = SpeechAdmission(min_snr_db=6.0, min_speech_ms=150)
    decision = admission.evaluate(
        is_speech=True, evidence=_evidence(20.0), speech_ms_so_far=200, already_admitted=False
    )
    assert decision.admit is True
    assert decision.reason == "ok"


def test_already_admitted_frame_keeps_admitting_despite_low_snr():
    admission = SpeechAdmission(min_snr_db=6.0)
    decision = admission.evaluate(
        is_speech=False, evidence=_evidence(-5.0), speech_ms_so_far=500, already_admitted=True
    )
    assert decision.admit is True
    assert decision.reason == "ok"


def test_preroll_buffer_rejects_non_positive_maxlen():
    with pytest.raises(ValueError):
        PreRollBuffer(0)


def test_preroll_buffer_flush_returns_frames_in_order():
    buffer = PreRollBuffer(maxlen_frames=4)
    buffer.push(b"a")
    buffer.push(b"b")
    buffer.push(b"c")

    assert buffer.flush() == [b"a", b"b", b"c"]


def test_preroll_buffer_flush_empties_buffer():
    buffer = PreRollBuffer(maxlen_frames=4)
    buffer.push(b"a")
    buffer.flush()

    assert buffer.flush() == []


def test_preroll_buffer_drops_oldest_frame_beyond_maxlen():
    buffer = PreRollBuffer(maxlen_frames=2)
    buffer.push(b"a")
    buffer.push(b"b")
    buffer.push(b"c")

    assert buffer.flush() == [b"b", b"c"]


def test_preroll_buffer_clear_discards_without_returning():
    buffer = PreRollBuffer(maxlen_frames=4)
    buffer.push(b"a")
    buffer.clear()

    assert buffer.flush() == []
