"""Ranh giới đầu/cuối câu của ZipFormer chunked-offline: không mất âm đầu khi Silero báo trễ,
không mất âm cuối nhỏ, nhưng không decode cả giây im lặng ở đuôi final."""

import numpy as np

from inference.asr.providers.zipformer import _Decoded, _prefer_confident_partial, _Utterance

_RATE = 16_000
_FRAME = 480  # 30 ms
_FRAME_BYTES = _FRAME * 2
_rng = np.random.default_rng(3)


def _frame(level_dbfs: float) -> bytes:
    noise = _rng.normal(0, 1, _FRAME)
    noise *= 32768 * 10 ** (level_dbfs / 20) / np.sqrt(np.mean(noise**2))
    return np.clip(noise, -32768, 32767).astype(np.int16).tobytes()


def _feed(utterance: _Utterance, frames: list[tuple[float, bool]]) -> None:
    for level, is_speech in frames:
        utterance.add(_frame(level), is_speech)


def test_soft_onset_before_late_vad_flag_is_kept() -> None:
    """Âm đầu ("HỌ") đủ to so với câu nhưng Silero chưa gắn cờ 600 ms: giữ cả phần đó."""
    utterance = _Utterance(_RATE, 300, onset_lookback_ms=1000)
    _feed(utterance, [(-70.0, False)] * 40 + [(-24.0, False)] * 20 + [(-15.0, True)])

    lead_frames = len(utterance.pcm) // _FRAME_BYTES - 1
    assert lead_frames == 20 + 3  # phần đầu nhỏ + đệm 90 ms


def test_without_lookback_only_the_fixed_pre_roll_is_kept() -> None:
    utterance = _Utterance(_RATE, 300)
    _feed(utterance, [(-70.0, False)] * 40 + [(-24.0, False)] * 20 + [(-15.0, True)])

    assert len(utterance.pcm) // _FRAME_BYTES - 1 == 10


def test_breath_or_room_noise_before_speech_is_not_pulled_in() -> None:
    utterance = _Utterance(_RATE, 300, onset_lookback_ms=1000)
    _feed(utterance, [(-70.0, False)] * 40 + [(-55.0, False)] * 20 + [(-15.0, True)])

    assert len(utterance.pcm) // _FRAME_BYTES - 1 == 10


def test_final_keeps_a_soft_last_syllable_but_drops_the_silent_tail() -> None:
    """ "ĐÚNG KHÔNG": "KHÔNG" nhỏ, Silero không gắn cờ — vẫn phải nằm trong final."""
    utterance = _Utterance(_RATE, 300, track_voice_end=True)
    _feed(
        utterance,
        [(-70.0, False)] * 40 + [(-15.0, True)] * 15 + [(-32.0, False)] * 8 + [(-70.0, False)] * 30,
    )

    pcm = utterance.final_pcm(150)
    voiced = (10 + 15 + 8) * _FRAME_BYTES  # pre-roll + câu + âm cuối nhỏ
    assert len(pcm) == voiced + 5 * _FRAME_BYTES  # tail 150 ms
    assert len(utterance.final_pcm(None)) == len(utterance.pcm)


def test_low_confidence_short_final_that_flips_the_partial_keeps_the_partial() -> None:
    utterance = _Utterance(_RATE, 300)
    utterance.last_partial, utterance.last_partial_confidence = "BÂY GIỜ", 0.94

    kept = _prefer_confident_partial(_Decoded("ĐƯỢC", 0.28), utterance)

    assert kept.text == "BÂY GIỜ"


def test_final_extending_the_partial_is_kept() -> None:
    utterance = _Utterance(_RATE, 300)
    utterance.last_partial, utterance.last_partial_confidence = "KHÔNG", 0.95

    kept = _prefer_confident_partial(_Decoded("KHÔNG ĐƯỢC", 0.3), utterance)

    assert kept.text == "KHÔNG ĐƯỢC"


def test_confident_final_is_kept_even_when_it_differs() -> None:
    utterance = _Utterance(_RATE, 300)
    utterance.last_partial, utterance.last_partial_confidence = "ĐÂY", 0.9

    kept = _prefer_confident_partial(_Decoded("VÂNG", 0.85), utterance)

    assert kept.text == "VÂNG"
