import httpx
import pytest

from speech.audio import loader
from speech.audio.codec import encode_wav
from speech.types import AudioSegment

_PCM = b"\x10\x00\xf0\xff" * 4410  # 0,2 s ở 44,1 kHz


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> None:
    wav = encode_wav(AudioSegment(pcm=_PCM, sample_rate=44_100))

    def fake_get(url: str, **_kwargs: object) -> httpx.Response:
        return httpx.Response(200, content=wav, request=httpx.Request("GET", url))

    monkeypatch.setattr(loader.httpx, "get", fake_get)


@pytest.mark.usefixtures("served")
def test_harness_clip_keeps_source_rate() -> None:
    # /v1/calls turn không ép qua 8 kHz: ASR tự resample một lần về tần số model
    segment = loader.load_from_url("https://harness.example/turn.wav")

    assert (segment.sample_rate, segment.pcm) == (44_100, _PCM)


@pytest.mark.usefixtures("served")
def test_target_rate_still_resamples_when_asked() -> None:
    pytest.importorskip("numpy")
    segment = loader.load_from_url("https://harness.example/turn.wav", 8_000)

    assert (segment.sample_rate, segment.duration_ms) == (8_000, 200)
