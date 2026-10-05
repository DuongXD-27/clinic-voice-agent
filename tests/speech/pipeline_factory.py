"""Dựng STTPipeline cho test với kích thước mặc định của test (không phải của production)."""

from speech.asr.pipeline import STTPipeline
from speech.types import NARROWBAND_RATE

_TEST_SIZES = {
    "sample_rate": NARROWBAND_RATE,
    "queue_max_frames": 50,
    "asr_queue_max_frames": 1000,
    "barge_in_preroll_frames": 17,
}


def make_stt_pipeline(asr, vad, **overrides) -> STTPipeline:
    return STTPipeline(asr=asr, vad=vad, **{**_TEST_SIZES, **overrides})
