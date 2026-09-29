import math
from typing import Optional

import numpy as np
import pytest
from tests.transports.http.fakes import FakeASR

from speech.asr.offline import AudioTooLong, InvalidAudio, transcribe_offline, transcribe_turn
from speech.asr.vad import EnergyFrameClassifier
from speech.audio.codec import encode_wav
from speech.types import AudioSegment, Transcript


def _energy_vad(sample_rate: int) -> EnergyFrameClassifier:
    return EnergyFrameClassifier(500)


def _wav(parts: list[tuple[float, float]], rate: int = 16_000) -> bytes:
    """`parts`: (giây, biên độ sine 440 Hz; 0 = lặng)."""
    chunks = []
    for seconds, amplitude in parts:
        t = np.arange(int(rate * seconds)) / rate
        chunks.append(amplitude * np.sin(2 * math.pi * 440 * t))
    pcm = np.concatenate(chunks).astype(np.int16).tobytes()
    return encode_wav(AudioSegment(pcm=pcm, sample_rate=rate))


class _ScriptedASR:
    name = "scripted"
    model = "scripted-v1"
    input_sample_rate = 16_000

    def __init__(self, results: list[tuple[str, Optional[float]]]) -> None:
        self._results = list(results)

    def transcribe(self, segment: AudioSegment) -> Transcript:
        text, confidence = self._results.pop(0)
        return Transcript(text=text, confidence=confidence, is_silence=not text)


def test_speech_is_segmented_and_decoded_at_model_rate() -> None:
    asr = FakeASR("xin chào", confidence=0.9)

    result = transcribe_offline(
        _wav([(1.5, 0), (1, 8000), (1.5, 0)]), recognizer=asr, vad_factory=_energy_vad
    )

    assert result.text == "xin chào"
    assert result.confidence == 0.9
    [segment] = result.segments
    assert (segment.start_ms, segment.end_ms) == (500, 2820)
    assert asr.received[0].sample_rate == 16_000
    assert asr.received[0].duration_ms == 2320
    assert result.steps == ["DC_REMOVAL", "VAD_SEGMENT"]
    assert result.warnings == []
    assert result.raw is None
    assert result.audio.duration_ms == 4000


def test_narrowband_source_is_resampled_and_flagged() -> None:
    asr = FakeASR("có")

    result = transcribe_offline(
        _wav([(1, 0), (1, 8000), (1, 0)], rate=8_000), recognizer=asr, vad_factory=_energy_vad
    )

    assert "RESAMPLE" in result.steps
    assert "NARROWBAND_SOURCE" in result.warnings
    assert {segment.sample_rate for segment in asr.received} == {16_000}


def test_telephone_band_goes_through_8k() -> None:
    result = transcribe_offline(
        _wav([(1, 8000)], rate=44_100),
        recognizer=FakeASR("có"),
        vad_factory=_energy_vad,
        telephone_band=True,
    )
    assert result.steps[:3] == ["TELEPHONE_BAND", "DC_REMOVAL", "RESAMPLE"]
    assert result.telephone_band is True


def test_compare_decodes_whole_file_without_preprocessing() -> None:
    asr = FakeASR("có", confidence=0.7)

    result = transcribe_offline(
        _wav([(1, 0), (1, 8000), (1, 0)]), recognizer=asr, vad_factory=_energy_vad, compare=True
    )

    assert result.raw is not None
    assert (result.raw.text, result.raw.confidence) == ("có", 0.7)
    assert asr.received[-1].duration_ms == 3000


def test_no_decode_is_longer_than_30_seconds() -> None:
    asr = FakeASR("có")

    result = transcribe_offline(
        _wav([(70, 8000)]), recognizer=asr, vad_factory=_energy_vad, compare=True
    )

    assert max(segment.duration_ms for segment in asr.received) <= 30_000
    assert len(result.segments) >= 3
    assert result.segments[0].start_ms == 0 and result.segments[-1].end_ms == 70_000
    assert result.raw is not None and set(result.raw.text.split()) == {"có"}


def test_quiet_file_is_boosted() -> None:
    result = transcribe_offline(
        _wav([(1, 0), (1, 300), (1, 0)]), recognizer=FakeASR("có"), vad_factory=_energy_vad
    )
    assert "GAIN_NORMALIZE" in result.steps
    assert result.gain_db > 10
    assert "LOW_LEVEL" in result.warnings


def test_confidence_is_weighted_by_word_count() -> None:
    asr = _ScriptedASR([("một hai ba", 0.9), ("bốn", 0.5)])

    result = transcribe_offline(
        _wav([(1, 0), (1, 8000), (3, 0), (1, 8000), (1, 0)]),
        recognizer=asr,
        vad_factory=_energy_vad,
    )

    assert result.text == "một hai ba bốn"
    assert result.confidence == pytest.approx(0.8)
    assert len(result.segments) == 2


def test_silence_returns_empty_transcript() -> None:
    asr = FakeASR("không được gọi")

    result = transcribe_offline(_wav([(2, 0)]), recognizer=asr, vad_factory=_energy_vad)

    assert (result.text, result.confidence, result.segments) == ("", None, [])
    assert "NO_SPEECH_DETECTED" in result.warnings
    assert asr.received == []


def test_invalid_and_too_long_audio_are_rejected() -> None:
    with pytest.raises(InvalidAudio):
        transcribe_offline(b"not a wav", recognizer=FakeASR(), vad_factory=_energy_vad)
    with pytest.raises(AudioTooLong):
        transcribe_offline(
            _wav([(301, 0)], rate=8_000), recognizer=FakeASR(), vad_factory=_energy_vad
        )


def test_turn_decodes_whole_clip_once_at_model_rate() -> None:
    asr = FakeASR("xin chào", confidence=0.9)

    result = transcribe_turn(_wav([(1.5, 0), (1, 8000), (1.5, 0)]), recognizer=asr)

    assert (result.text, result.confidence, result.production) == ("xin chào", 0.9, None)
    [segment] = asr.received
    assert (segment.sample_rate, segment.duration_ms) == (16_000, 4000)
    assert result.steps == ["DC_REMOVAL"]
    assert result.warnings == []


def test_turn_production_follows_calls_turn_path_at_source_rate() -> None:
    asr = FakeASR("có", confidence=0.7)

    result = transcribe_turn(_wav([(1, 8000)], rate=44_100), recognizer=asr, compare=True)

    main, production = asr.received
    assert main.sample_rate == 16_000
    # Như /v1/calls turn: clip giữ tần số gốc, SpeechRecognizer thật resample một lần về 16 kHz
    assert production.sample_rate == 44_100
    assert result.production is not None
    assert (result.production.text, result.production.confidence) == ("có", 0.7)
    assert "RESAMPLE" in result.steps


def test_turn_boosts_quiet_clip() -> None:
    result = transcribe_turn(_wav([(1, 300)]), recognizer=FakeASR("có"))

    assert "GAIN_NORMALIZE" in result.steps
    assert "LOW_LEVEL" in result.warnings


def test_turn_empty_transcript_has_no_confidence() -> None:
    result = transcribe_turn(_wav([(1, 0)]), recognizer=FakeASR("", confidence=0.4))
    assert (result.text, result.confidence) == ("", None)


def test_turn_longer_than_30_seconds_is_rejected() -> None:
    with pytest.raises(AudioTooLong) as caught:
        transcribe_turn(_wav([(31, 0)], rate=8_000), recognizer=FakeASR())
    assert caught.value.limit_ms == 30_000
