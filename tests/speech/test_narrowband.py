import math
import struct

import pytest

from callbot.speech import SpeechSettings, STTPipeline
from callbot.speech.audio import alaw_to_pcm16, decode_wav, encode_wav, mulaw_to_pcm16
from callbot.speech.types import NARROWBAND_RATE, AudioSegment, Transcript
from callbot.speech.vad import EnergyFrameClassifier, StreamingVAD


def _wav(format_tag: int, sample_rate: int, bits: int, frames: bytes, channels: int = 1) -> bytes:
    block_align = channels * bits // 8
    fmt = struct.pack("<HHIIHH", format_tag, channels, sample_rate, sample_rate * block_align, block_align, bits)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(frames)) + frames
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _tone(freq_hz: float, rate: int, seconds: float, amplitude: int = 8000) -> bytes:
    count = int(rate * seconds)
    return b"".join(
        struct.pack("<h", int(amplitude * math.sin(2 * math.pi * freq_hz * i / rate))) for i in range(count)
    )


def test_settings_default_to_narrowband() -> None:
    assert SpeechSettings().sample_rate == NARROWBAND_RATE


def test_g711_silence_and_extremes() -> None:
    assert mulaw_to_pcm16(b"\xff") == struct.pack("<h", 0)
    assert struct.unpack("<h", mulaw_to_pcm16(b"\x00"))[0] == -32124
    assert struct.unpack("<h", mulaw_to_pcm16(b"\x80"))[0] == 32124
    assert abs(struct.unpack("<h", alaw_to_pcm16(b"\xd5"))[0]) <= 8
    assert struct.unpack("<h", alaw_to_pcm16(b"\xaa"))[0] == 32256


def test_decode_mulaw_wav_keeps_8k() -> None:
    segment = decode_wav(_wav(7, 8000, 8, b"\xff" * 800))
    assert segment.sample_rate == NARROWBAND_RATE
    assert segment.duration_ms == 100


def test_decode_pcm_8k_wav_roundtrip() -> None:
    pcm = _tone(440, 8000, 0.1)
    segment = decode_wav(encode_wav(AudioSegment(pcm=pcm, sample_rate=8000)))
    assert segment.pcm == pcm


def test_downsample_16k_filters_out_of_band() -> None:
    np = pytest.importorskip("numpy")
    in_band = decode_wav(_wav(1, 16000, 16, _tone(1000, 16000, 0.5)))
    # 6 kHz nằm ngoài băng thoại 8 kHz (Nyquist 4 kHz) — phải bị lọc, không được alias thành 2 kHz
    out_band = decode_wav(_wav(1, 16000, 16, _tone(6000, 16000, 0.5)))
    assert in_band.sample_rate == out_band.sample_rate == NARROWBAND_RATE
    rms = lambda s: float(np.sqrt(np.mean(np.frombuffer(s.pcm, dtype=np.int16).astype(np.float64) ** 2)))
    assert rms(out_band) < 0.1 * rms(in_band)


class _RecordingASR:
    name = "fake"
    input_sample_rate = NARROWBAND_RATE

    def __init__(self) -> None:
        self.received: list[AudioSegment] = []

    def transcribe(self, segment: AudioSegment) -> Transcript:
        self.received.append(segment)
        return Transcript(text="alo")


def test_pipeline_feeds_asr_at_8k() -> None:
    pytest.importorskip("numpy")
    asr = _RecordingASR()
    pipeline = STTPipeline(asr=asr, vad=StreamingVAD(EnergyFrameClassifier()))

    assert pipeline.transcribe_segment(AudioSegment(pcm=b"\x00\x00" * 8000, sample_rate=8000)).is_silence
    assert asr.received == []

    result = pipeline.transcribe_segment(AudioSegment(pcm=_tone(300, 16000, 0.5), sample_rate=16000))
    assert result.text == "alo"
    assert asr.received[0].sample_rate == NARROWBAND_RATE
