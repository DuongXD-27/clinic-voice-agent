"""ZipFormer 68M self-host qua sherpa-onnx.

Model `csukuangfj/sherpa-onnx-zipformer-vi-int8-2025-04-20` đã kiểm chứng (xem
temp/plan_mvp_zipformer.md, docs/reference/phone-leg-architecture.md §3.1) là bản
EXPORT OFFLINE (batch) — thiếu metadata streaming (`encoder_dims`) nên chỉ nạp được
qua `OfflineRecognizer`, không phải `OnlineRecognizer`. Vì vậy `transcribe()` nhận
nguyên một đoạn audio đã cắt sẵn (bởi VAD), không có partial transcript tăng dần.
"""

from pathlib import Path
from typing import Any, AsyncIterator

from callbot.speech.audio.codec import to_sample_rate
from callbot.speech.types import WIDEBAND_RATE, AudioSegment, Transcript, TranscriptEvent

_ASSETS_DIR = Path(__file__).parent / "assets" / "zipformer"


class ZipFormerASR:
    name = "zipformer"
    input_sample_rate = WIDEBAND_RATE

    def __init__(
        self,
        encoder_path: str,
        decoder_path: str,
        joiner_path: str,
        tokens_path: str,
        *,
        num_threads: int = 2,
        recognizer: Any = None,
    ) -> None:
        self._encoder_path = encoder_path
        self._decoder_path = decoder_path
        self._joiner_path = joiner_path
        self._tokens_path = tokens_path
        self._num_threads = num_threads
        self._recognizer = recognizer

    def _get_recognizer(self):
        if self._recognizer is None:
            import sherpa_onnx  # pip install -e ".[speech-zipformer]"

            self._recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
                tokens=self._tokens_path,
                encoder=self._encoder_path,
                decoder=self._decoder_path,
                joiner=self._joiner_path,
                num_threads=self._num_threads,
                sample_rate=self.input_sample_rate,
                feature_dim=80,
                decoding_method="greedy_search",
                provider="cpu",
            )
        return self._recognizer

    def transcribe(self, segment: AudioSegment) -> Transcript:
        import numpy as np

        segment = to_sample_rate(segment, self.input_sample_rate)
        if not segment.pcm:
            return Transcript(is_silence=True)

        samples = np.frombuffer(segment.pcm, dtype=np.int16).astype(np.float32) / 32768.0
        recognizer = self._get_recognizer()
        stream = recognizer.create_stream()
        stream.accept_waveform(self.input_sample_rate, samples)
        recognizer.decode_stream(stream)
        text = stream.result.text.strip()
        return Transcript(text=text, is_silence=not text)

    async def stream(self, frames: AsyncIterator[bytes]) -> AsyncIterator[TranscriptEvent]:
        # Model là batch (xem docstring module) — không có partial tăng dần, cần
        # checkpoint export riêng cho streaming mới cài được đường này.
        raise NotImplementedError
        yield  # pragma: no cover


def default_paths() -> dict[str, str]:
    """Đường dẫn 4 file asset ZipFormer đi kèm repo (assets/zipformer/)."""
    return {
        "encoder_path": str(_ASSETS_DIR / "encoder-epoch-12-avg-8.int8.onnx"),
        "decoder_path": str(_ASSETS_DIR / "decoder-epoch-12-avg-8.onnx"),
        "joiner_path": str(_ASSETS_DIR / "joiner-epoch-12-avg-8.int8.onnx"),
        "tokens_path": str(_ASSETS_DIR / "tokens.txt"),
    }
