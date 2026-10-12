"""Audio riêng cho bộ phân loại tiếng nói (Silero) của đường LiveKit — ASR vẫn nghe frame gốc.

Khử nhiễu đưa thẳng vào ASR đã thử nhiều lần và luôn làm WER tệ đi: GipFormer nghe audio thô tốt
hơn audio đã khử nhiễu (WebRTC NS, RNNoise, GTCRN, DPDFNet, DeepFilterNet3, Krisp, Quail — docs/
evidence/pm-preprocess-neural-2026-10-02.md, livekit-audio-plan-execution-2026-09-28.md §8). Còn
Silero thì yếu đúng ở chỗ khử nhiễu mạnh: nhiễu phòng / tiếng lạo xạo G.711 làm nó báo nhầm, nhiễu
đường phố làm nó bỏ sót giọng. Mà quyết định của Silero lại quyết định ASR nghe đoạn nào (bắt đầu
/ kết thúc đoạn, đuôi câu), lượt nào được chốt, lượt nào thành ảo giác.

Ở đây khử nhiễu chỉ đi vào bộ phân loại: `STTPipeline._fanout` đưa frame qua `VadFrontend.process`
rồi phân loại bản đã xử lý, kết quả gắn với frame GỐC (`SharedSpeechDetector.classify(frame,
analysis=...)`). ASR, bằng chứng SNR (đo mức), tiếng vọng vẫn nhận frame gốc.

Đầu ra mỗi lần gọi có thể dài/ngắn hơn frame vào (bộ khử nhiễu streaming nhả theo bước hop của
nó); Silero tự gom mẫu thành cửa sổ 512 nên không cần cắt lại cho đúng 30 ms — cắt lại sẽ thêm trễ.
Vì vậy chỉ dùng với `vad_provider=silero` (WebRTC VAD đòi frame đúng 10/20/30 ms).

TẮT mặc định (config/speech.yaml): Silero nghe lại được giọng trong nhiễu nặng (SIP ở chỗ ồn mất
86/89 câu -> 4/89), nhưng cũng nghe được TV / người xung quanh khi người gọi im lặng. Số đo:
docs/evidence/livekit-vad-frontend-2026-10-12.md.
"""

from __future__ import annotations

import logging
from typing import Literal, Optional, Protocol

import numpy as np

logger = logging.getLogger(__name__)

# webrtc_agc: WebRTC NS + AGC (đưa giọng nhỏ về mức Silero nghe tốt), chỉ cho bộ phân loại.
VadFrontendKind = Literal["off", "webrtc", "webrtc_agc", "gtcrn", "dpdfnet"]


class _Denoiser(Protocol):
    def process(self, samples: np.ndarray) -> np.ndarray:
        """PCM16 vào (int16, một kênh), PCM16 ra — độ dài ra có thể khác độ dài vào."""
        ...


class _WebRtcNoiseSuppressor:
    """WebRTC NS của libwebrtc (qua `livekit.rtc.AudioProcessingModule`, cùng bộ khử nhiễu của
    trình duyệt). Xử lý từng khúc 10 ms tại chỗ, không thêm trễ; phần lẻ chờ frame sau."""

    def __init__(self, sample_rate: int, *, auto_gain: bool, high_pass: bool) -> None:
        from livekit import rtc

        self._rtc = rtc
        self._apm = rtc.AudioProcessingModule(
            noise_suppression=True, auto_gain_control=auto_gain, high_pass_filter=high_pass
        )
        self._rate = sample_rate
        self._chunk = sample_rate // 100
        self._pending = np.empty(0, dtype=np.int16)

    def process(self, samples: np.ndarray) -> np.ndarray:
        pending = np.concatenate([self._pending, samples]) if self._pending.size else samples
        usable = len(pending) - len(pending) % self._chunk
        out = np.empty(usable, dtype=np.int16)
        for start in range(0, usable, self._chunk):
            frame = self._rtc.AudioFrame(
                data=pending[start : start + self._chunk].tobytes(),
                sample_rate=self._rate,
                num_channels=1,
                samples_per_channel=self._chunk,
            )
            self._apm.process_stream(frame)
            out[start : start + self._chunk] = np.frombuffer(frame.data, dtype=np.int16)
        self._pending = pending[usable:].copy()
        return out


class _SherpaDenoiser:
    """GTCRN / DPDFNet streaming của sherpa-onnx (`OnlineSpeechDenoiser`). Đo 12/10 trên frame
    30 ms, 1 luồng CPU: GTCRN ~2 ms/frame và không thêm trễ (nhả mẫu ngay trong lần gọi nhận vào);
    DPDFNet baseline ~6,6 ms/frame, trễ 60 ms."""

    def __init__(self, kind: str, model_path: str, sample_rate: int) -> None:
        import sherpa_onnx

        model = sherpa_onnx.OfflineSpeechDenoiserModelConfig(num_threads=1)
        if kind == "gtcrn":
            model.gtcrn.model = model_path
        else:
            model.dpdfnet.model = model_path
        self._denoiser = sherpa_onnx.OnlineSpeechDenoiser(
            sherpa_onnx.OnlineSpeechDenoiserConfig(model=model)
        )
        self._rate = sample_rate
        self._resampler: Optional[object] = None
        if self._denoiser.sample_rate != sample_rate:
            import soxr

            self._resampler = soxr.ResampleStream(
                self._denoiser.sample_rate, sample_rate, 1, dtype="float32", quality="HQ"
            )

    def process(self, samples: np.ndarray) -> np.ndarray:
        result = self._denoiser.run(samples.astype(np.float32) / 32768.0, self._rate)
        out = np.asarray(result.samples, dtype=np.float32)
        if self._resampler is not None:
            out = self._resampler.resample_chunk(out)
        return np.clip(np.round(out * 32768.0), -32768, 32767).astype(np.int16)


class VadFrontend:
    """Một instance cho một cuộc gọi (bộ khử nhiễu có trạng thái). Gọi `process` cho MỌI frame
    theo đúng thứ tự tới, kể cả lúc bot nói — như bộ phân loại dùng chung.

    `gain_db`: tăng âm sau khi khử nhiễu, CHỈ cho bộ phân loại (Silero phụ thuộc mức âm tuyệt
    đối, nền đã được khử nên tăng không kéo nhiễu lên ngang ngưỡng như tăng trên audio thô).
    `floor_dbfs`: nhiễu trắng nền (RMS) cộng vào sau khi khử nhiễu, None = không cộng."""

    def __init__(
        self,
        denoiser: _Denoiser,
        *,
        gain_db: float = 0.0,
        floor_dbfs: Optional[float] = None,
        seed: int = 0,
    ) -> None:
        self._denoiser = denoiser
        self._factor = 10 ** (gain_db / 20) if gain_db else None
        self._floor = 32768 * 10 ** (floor_dbfs / 20) if floor_dbfs is not None else None
        self._rng = np.random.default_rng(seed)

    def process(self, frame: bytes) -> bytes:
        out = self._denoiser.process(np.frombuffer(frame, dtype=np.int16))
        if not out.size or (self._factor is None and self._floor is None):
            return out.tobytes()
        samples = out.astype(np.float64)
        if self._factor is not None:
            samples *= self._factor
        if self._floor is not None:
            samples += self._rng.normal(0.0, self._floor, samples.size)
        return np.clip(np.round(samples), -32768, 32767).astype(np.int16).tobytes()


def build_vad_frontend(
    kind: VadFrontendKind,
    *,
    sample_rate: int,
    model_path: str = "",
    gain_db: float = 0.0,
    floor_dbfs: Optional[float] = None,
    auto_gain: bool = False,
    high_pass: bool = False,
) -> Optional[VadFrontend]:
    """None khi `kind="off"`. Thiếu model / thư viện thì cảnh báo và chạy không có front-end (như
    cổng giọng): VAD trên audio gốc vẫn là cấu hình đã chạy production."""
    if kind == "off":
        return None
    try:
        if kind in ("webrtc", "webrtc_agc"):
            denoiser: _Denoiser = _WebRtcNoiseSuppressor(
                sample_rate, auto_gain=auto_gain or kind == "webrtc_agc", high_pass=high_pass
            )
        else:
            from pathlib import Path

            if not Path(model_path).is_file():
                logger.warning("vad_frontend: không thấy model %s — VAD nghe audio gốc", model_path)
                return None
            denoiser = _SherpaDenoiser(kind, model_path, sample_rate)
    except ImportError as exc:
        logger.warning("vad_frontend: thiếu thư viện cho %s (%s) — VAD nghe audio gốc", kind, exc)
        return None
    return VadFrontend(denoiser, gain_db=gain_db, floor_dbfs=floor_dbfs)
