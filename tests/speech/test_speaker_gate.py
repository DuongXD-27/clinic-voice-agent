import numpy as np

from speech.audio.speaker_gate import SpeakerGate

RATE = 16_000


def _voice(direction: list[float]):
    vector = np.array(direction, dtype=np.float32)
    return vector / np.linalg.norm(vector)


class _Voices:
    """Embedding giả: mỗi lượt trả về vector cho sẵn theo thứ tự."""

    def __init__(self, *vectors) -> None:
        self._vectors = list(vectors)
        self.calls = 0

    def __call__(self, samples, sample_rate):
        self.calls += 1
        return self._vectors.pop(0)


def _pcm(seconds: float = 2.5) -> bytes:
    rng = np.random.default_rng(0)
    return (rng.normal(0, 3000, int(seconds * RATE))).astype(np.int16).tobytes()


def test_first_long_turn_enrolls_then_other_voice_is_blocked() -> None:
    caller, other = _voice([1, 0]), _voice([0, 1])
    gate = SpeakerGate(_Voices(caller, other), enforce=True, threshold=0.2, min_speech_ms=2000)

    assert gate.allows(_pcm(), RATE, speech_ms=2500) is True  # giọng mẫu
    assert gate.allows(_pcm(), RATE, speech_ms=2500) is False


def test_same_voice_passes() -> None:
    caller = _voice([1, 0])
    gate = SpeakerGate(
        _Voices(caller, _voice([0.9, 0.1])), enforce=True, threshold=0.2, min_speech_ms=2000
    )

    gate.allows(_pcm(), RATE, speech_ms=2500)

    assert gate.allows(_pcm(), RATE, speech_ms=2500) is True


def test_short_turns_are_never_judged() -> None:
    """Embedding của đoạn ngắn không tin cậy: "ừ", "có" luôn qua và không làm giọng mẫu."""
    voices = _Voices()
    gate = SpeakerGate(voices, enforce=True, threshold=0.2, min_speech_ms=2000)

    assert gate.allows(_pcm(0.5), RATE, speech_ms=600) is True
    assert gate.allows(_pcm(0.5), RATE, speech_ms=None) is True
    assert voices.calls == 0


def test_log_mode_never_blocks() -> None:
    gate = SpeakerGate(
        _Voices(_voice([1, 0]), _voice([0, 1])), enforce=False, threshold=0.2, min_speech_ms=2000
    )

    gate.allows(_pcm(), RATE, speech_ms=2500)

    assert gate.allows(_pcm(), RATE, speech_ms=2500) is True
