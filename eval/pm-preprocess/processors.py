"""Bộ xử lý đã thử trên bộ eval PM nhưng KHÔNG đưa vào /v1/stt/turn (số đo:
docs/evidence/pm-preprocess-2026-10-02.md). Giữ ở đây để `run.py` tái tạo được kết quả.

`prepare_experiment` đi đúng thứ tự `_prepare` của speech/asr/offline.py rồi chèn thêm các bước
này; `run.py --self-check` xác nhận khi không bật bước nào thì audio ra giống hệt API.

Bộ khử nhiễu chạy trước resample (`enhancer=`, suite `neural`/`opt` của run.py):
    gtcrn_simple.onnx, dpdfnet_{baseline,2,4,8}.onnx: github.com/k2-fsa/sherpa-onnx/releases
        (tag speech-enhancement-models), chạy bằng sherpa_onnx.OfflineSpeechDenoiser, tải vào MODEL_DIR
    dpdfnet{2,8}_8khz.onnx: huggingface.co/Ceva-IP/DPDFNet (onnx/, Apache-2.0), cùng định dạng
    DeepFilterNet3 (pip deepfilternet) và RNNoise (pip pyrnnoise): chạy ở 48 kHz
    WebRTC NS: livekit.rtc.AudioProcessingModule (có sẵn trong SDK LiveKit), frame 10 ms
    SpeexDSP denoise: libspeexdsp.so.1 của hệ thống qua ctypes, frame 20 ms, cấu hình mặc định
"""

from __future__ import annotations

import ctypes
import functools
import sys
import types
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from speech.asr.vad.base import FrameClassifier
from speech.audio.codec import read_wav, to_sample_rate
from speech.audio.preprocess import (
    LevelStats,
    detect_speech_frames,
    measure_level,
    normalize_gain,
    remove_dc,
    speech_regions,
)
from speech.types import AudioSegment

_FRAME_MS = 30


def is_silent_turn(flags: list[bool], level: LevelStats) -> bool:
    """Experimental gate: little detected speech and room tone below -55 dBFS."""
    quiet = level.speech_rms_dbfs is None or level.speech_rms_dbfs < -55.0
    return quiet and sum(flags) * _FRAME_MS < 200


MODEL_DIR = Path(__file__).resolve().parents[2] / "temp" / "models" / "speech-enhancement"
# tên -> (loại, file model)
ENHANCERS: dict[str, tuple[str, Optional[str]]] = {
    "gtcrn": ("sherpa-gtcrn", "gtcrn_simple.onnx"),
    "dpdfnet_baseline": ("sherpa-dpdfnet", "dpdfnet_baseline.onnx"),
    "dpdfnet2": ("sherpa-dpdfnet", "dpdfnet2.onnx"),
    "dpdfnet4": ("sherpa-dpdfnet", "dpdfnet4.onnx"),
    "dpdfnet8": ("sherpa-dpdfnet", "dpdfnet8.onnx"),
    "dpdfnet2_8khz": ("sherpa-dpdfnet", "dpdfnet2_8khz.onnx"),
    "dpdfnet8_8khz": ("sherpa-dpdfnet", "dpdfnet8_8khz.onnx"),
    "deepfilternet3": ("deepfilternet", None),
    "rnnoise": ("rnnoise", None),
    "webrtc_ns": ("webrtc-ns", None),
    "speex_ns": ("speex-ns", None),
}
# speex_preprocess_ctl (speex/speex_preprocess.h)
_SPEEX_SET_DENOISE = 0
_SPEEX_SET_AGC = 2


def _samples(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float64)


def _to_pcm(samples: np.ndarray) -> bytes:
    return np.clip(np.round(samples), -32768, 32767).astype(np.int16).tobytes()


def _outside_regions(n_frames: int, regions: list[tuple[int, int]], frame_ms: int) -> np.ndarray:
    outside = np.ones(n_frames, dtype=bool)
    for begin, end in regions:
        outside[begin // frame_ms : -(-end // frame_ms)] = False
    return outside


def trim_to_regions(pcm: bytes, sample_rate: int, regions: list[tuple[int, int]]) -> bytes:
    """Giữ từ đầu đoạn có giọng đầu tiên tới cuối đoạn cuối cùng (đoạn đã có đệm)."""
    if not regions:
        return pcm
    begin = regions[0][0] * sample_rate // 1000 * 2
    end = regions[-1][1] * sample_rate // 1000 * 2
    return pcm[begin:end]


def highpass(pcm: bytes, sample_rate: int, *, cutoff_hz: float = 100.0, order: int = 4) -> bytes:
    """Lọc thông cao Butterworth, lọc hai chiều (không lệch pha). Giọng nói gần như không có năng
    lượng dưới 100 Hz; tiếng xe, gió, rung bàn thì có."""
    from scipy.signal import butter, sosfiltfilt

    samples = _samples(pcm)
    if samples.size < 64:
        return pcm
    sos = butter(order, cutoff_hz, btype="highpass", fs=sample_rate, output="sos")
    return _to_pcm(sosfiltfilt(sos, samples))


def dereverb_wpe(
    pcm: bytes, sample_rate: int, *, taps: int = 10, delay: int = 3, iterations: int = 3
) -> bytes:
    """Khử vang WPE một kênh (`nara_wpe`, STFT 512/128 như ví dụ của thư viện cho 16 kHz)."""
    from nara_wpe.utils import istft, stft
    from nara_wpe.wpe import wpe

    samples = _samples(pcm)
    if samples.size < 2048:
        return pcm
    spectrum = stft(samples[None, :], size=512, shift=128)  # (1, T, F)
    dry = wpe(spectrum.transpose(2, 0, 1), taps=taps, delay=delay, iterations=iterations)
    restored = istft(dry.transpose(1, 2, 0), size=512, shift=128)[0][: samples.size]
    if restored.size < samples.size:
        restored = np.pad(restored, (0, samples.size - restored.size))
    return _to_pcm(restored)


def reduce_noise(
    pcm: bytes,
    sample_rate: int,
    regions: list[tuple[int, int]],
    *,
    prop_decrease: float,
    frame_ms: int = 30,
    min_noise_ms: int = 250,
) -> Optional[bytes]:
    """Khử nhiễu dạng spectral gating (`noisereduce`, chế độ stationary), giảm tối đa
    `prop_decrease` (1 = giảm hết). Hồ sơ nhiễu lấy từ phần NẰM NGOÀI mọi đoạn có giọng đã đệm —
    không lấy frame VAD chưa gắn cờ vì Silero bật cờ trễ ~250 ms (xem `estimate_snr_db`).
    None khi phần ngoài giọng ngắn hơn `min_noise_ms`: tự ước lượng nhiễu từ chính câu nói sẽ
    xoá luôn giọng."""
    import noisereduce

    samples = _samples(pcm)
    frame = sample_rate * frame_ms // 1000
    n_frames = samples.size // frame
    outside = _outside_regions(n_frames, regions, frame_ms)
    if outside.sum() * frame_ms < min_noise_ms:
        return None
    noise = samples[: n_frames * frame].reshape(n_frames, frame)[outside].ravel()
    cleaned = noisereduce.reduce_noise(
        y=samples.astype(np.float32),
        sr=sample_rate,
        y_noise=noise.astype(np.float32),
        stationary=True,
        prop_decrease=prop_decrease,
        n_jobs=1,
    )
    return _to_pcm(cleaned)


# --- bộ khử nhiễu chạy trước resample -------------------------------------------------------------


def _split(name: str) -> tuple[str, float]:
    """ "dpdfnet2@12" -> ("dpdfnet2", 12.0): giới hạn mức nén (dB) của DPDFNet; 0 = không giới hạn."""
    base, _, limit = name.partition("@")
    return base, float(limit or 0)


def enhancer_unavailable(name: str) -> Optional[str]:
    """Lý do không chạy được bộ khử nhiễu `name` trên máy này (None = chạy được)."""
    kind, file = ENHANCERS[_split(name)[0]]
    if file and not (MODEL_DIR / file).exists():
        return f"thiếu {MODEL_DIR / file}"
    try:
        _load(name)
    except Exception as exc:  # thiếu gói (deepfilternet, pyrnnoise, libspeexdsp) hoặc model hỏng
        return f"{type(exc).__name__}: {exc}"
    return None


@functools.cache
def _load(name: str):
    base, limit = _split(name)
    kind, file = ENHANCERS[base]
    if kind.startswith("sherpa"):
        import sherpa_onnx as so

        model = so.OfflineSpeechDenoiserModelConfig(num_threads=1)
        if kind == "sherpa-gtcrn":
            model.gtcrn = so.OfflineSpeechDenoiserGtcrnModelConfig(model=str(MODEL_DIR / file))
        else:
            model.dpdfnet = so.OfflineSpeechDenoiserDpdfNetModelConfig(
                model=str(MODEL_DIR / file), attenuation_limit_db=limit
            )
        return so.OfflineSpeechDenoiser(so.OfflineSpeechDenoiserConfig(model=model))
    if kind == "deepfilternet":
        _stub_torchaudio_io()
        from df.enhance import init_df

        model, state, _ = init_df(log_level="ERROR")
        return model, state
    if kind == "webrtc-ns":
        from livekit import rtc

        return rtc
    if kind == "speex-ns":
        lib = ctypes.CDLL("libspeexdsp.so.1")
        lib.speex_preprocess_state_init.restype = ctypes.c_void_p
        lib.speex_preprocess_state_init.argtypes = [ctypes.c_int, ctypes.c_int]
        lib.speex_preprocess_ctl.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        lib.speex_preprocess_run.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int16)]
        lib.speex_preprocess_state_destroy.argtypes = [ctypes.c_void_p]
        return lib
    from pyrnnoise import rnnoise

    return rnnoise


def _stub_torchaudio_io() -> None:
    """DeepFilterNet 0.5.6 import phần I/O của torchaudio (đã bị bỏ ở bản torchaudio mới) ngay khi
    nạp module, dù `enhance()` không dùng tới. Thiếu torchaudio thì thay bằng module rỗng — đọc
    ghi file và resample ở đây đều tự làm bằng soxr."""
    try:
        import torchaudio  # noqa: F401

        return
    except ImportError:
        pass
    import soxr
    import torch

    for name in (
        "torchaudio",
        "torchaudio.backend",
        "torchaudio.backend.common",
        "torchaudio.functional",
    ):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["torchaudio.backend.common"].AudioMetaData = object
    sys.modules["torchaudio.functional"].resample = lambda wave, a, b, **_: torch.from_numpy(
        soxr.resample(wave.numpy().T, a, b).T.copy()
    )


def enhance(pcm: bytes, sample_rate: int, name: str) -> tuple[bytes, int]:
    """Khử nhiễu bằng `name`; trả (pcm, tần số đầu ra). Model ONNX ra ở tần số của model;
    WebRTC NS và SpeexDSP chạy thẳng ở tần số của file; DeepFilterNet3/RNNoise ở 48 kHz."""
    import soxr

    kind, _ = ENHANCERS[_split(name)[0]]
    if kind == "webrtc-ns":
        return _webrtc_ns(pcm, sample_rate), sample_rate
    if kind == "speex-ns":
        return _speex_ns(pcm, sample_rate), sample_rate
    samples = (_samples(pcm) / 32768.0).astype(np.float32)
    if kind.startswith("sherpa"):
        out = _load(name).run(samples, sample_rate)  # sherpa tự resample về tần số model
        return _to_pcm(np.asarray(out.samples) * 32768.0), out.sample_rate
    wide = soxr.resample(samples, sample_rate, 48_000).astype(np.float32)
    if kind == "deepfilternet":
        import torch
        from df.enhance import enhance

        model, state = _load(name)
        clean = enhance(model, state, torch.from_numpy(wide)[None, :])[0].numpy()
        return _to_pcm(clean * 32768.0), 48_000
    rnnoise = _load(name)
    frame = rnnoise.FRAME_SIZE
    ints = np.clip(np.round(wide * 32768.0), -32768, 32767).astype(np.int16)
    ints = np.pad(ints, (0, -len(ints) % frame))
    state = rnnoise.create()
    try:
        out = [
            rnnoise.process_mono_frame(state, ints[i : i + frame])[0]
            for i in range(0, len(ints), frame)
        ]
    finally:
        rnnoise.destroy(state)
    return np.concatenate(out).astype(np.int16)[: len(wide)].tobytes(), 48_000


def _webrtc_ns(pcm: bytes, sample_rate: int) -> bytes:
    """Chỉ bật khử nhiễu của WebRTC APM (không AGC/AEC/lọc thông cao), một APM mới mỗi clip, frame
    10 ms; phần dư cuối không đủ frame giữ nguyên."""
    rtc = _load("webrtc_ns")
    apm = rtc.AudioProcessingModule(noise_suppression=True)
    frame = sample_rate // 100
    samples = np.frombuffer(pcm, dtype=np.int16).copy()
    for start in range(0, len(samples) - frame + 1, frame):
        audio = rtc.AudioFrame(
            data=samples[start : start + frame].tobytes(),
            sample_rate=sample_rate,
            num_channels=1,
            samples_per_channel=frame,
        )
        apm.process_stream(audio)
        samples[start : start + frame] = np.frombuffer(audio.data, dtype=np.int16)
    return samples.tobytes()


def _speex_ns(pcm: bytes, sample_rate: int) -> bytes:
    """SpeexDSP preprocess chỉ bật denoise (mặc định của thư viện, nén tối đa −15 dB), tắt AGC,
    một state mới mỗi clip, frame 20 ms; phần dư cuối giữ nguyên."""
    lib = _load("speex_ns")
    frame = sample_rate // 50
    state = lib.speex_preprocess_state_init(frame, sample_rate)
    on, off = ctypes.c_int(1), ctypes.c_int(0)
    lib.speex_preprocess_ctl(state, _SPEEX_SET_DENOISE, ctypes.byref(on))
    lib.speex_preprocess_ctl(state, _SPEEX_SET_AGC, ctypes.byref(off))
    samples = np.frombuffer(pcm, dtype=np.int16).copy()
    try:
        for start in range(0, len(samples) - frame + 1, frame):
            buf = (ctypes.c_int16 * frame)(*samples[start : start + frame])
            lib.speex_preprocess_run(state, buf)
            samples[start : start + frame] = np.frombuffer(buf, dtype=np.int16)
    finally:
        lib.speex_preprocess_state_destroy(state)
    return samples.tobytes()


def prepare_experiment(
    data: bytes,
    model_rate: int,
    vad_factory: Callable[[int], FrameClassifier],
    *,
    gate: bool = False,
    highpass_hz: Optional[float] = None,
    dereverb: bool = False,
    denoise: Optional[float] = None,
    trim: bool = False,
    enhancer: Optional[str] = None,
) -> tuple[Optional[bytes], list[str], float]:
    """(audio đưa vào ASR hoặc None nếu cổng chặn, các bước, gain dB). Thứ tự: bỏ DC → resample
    → lọc thông cao → khử vang → VAD → khử nhiễu → cổng im lặng → cắt đầu/đuôi → khuếch đại.

    `enhancer`: lọc thông cao (nếu có) rồi bộ khử nhiễu chạy TRƯỚC khi resample, ở tần số gốc của
    file — model 8 kHz nhận đúng audio 8 kHz; model khác tần số thì sherpa/soxr resample — sau đó
    mới đưa về `model_rate`."""
    original, _ = read_wav(data)
    source = AudioSegment(pcm=remove_dc(original.pcm), sample_rate=original.sample_rate)
    steps = ["DC_REMOVAL"]
    if enhancer:
        if highpass_hz:
            source = AudioSegment(
                pcm=highpass(source.pcm, source.sample_rate, cutoff_hz=highpass_hz),
                sample_rate=source.sample_rate,
            )
            steps.append("HIGHPASS")
            highpass_hz = None
        cleaned, rate = enhance(source.pcm, source.sample_rate, enhancer)
        source = AudioSegment(pcm=cleaned, sample_rate=rate)
        steps.append(f"ENHANCE:{enhancer}")
    pcm = to_sample_rate(source, model_rate).pcm
    if source.sample_rate != model_rate:
        steps.append("RESAMPLE")
    if highpass_hz:
        pcm = highpass(pcm, model_rate, cutoff_hz=highpass_hz)
        steps.append("HIGHPASS")
    if dereverb:
        pcm = dereverb_wpe(pcm, model_rate)
        steps.append("DEREVERB")
    flags: list[bool] = []
    regions: list[tuple[int, int]] = []
    if gate or trim or denoise is not None:
        flags = detect_speech_frames(pcm, model_rate, vad_factory(model_rate), frame_ms=_FRAME_MS)
        regions = speech_regions(flags, len(pcm) * 1000 // (model_rate * 2), frame_ms=_FRAME_MS)
    if denoise is not None and regions:
        cleaned = reduce_noise(pcm, model_rate, regions, prop_decrease=denoise)
        if cleaned is not None:
            pcm = cleaned
            steps.append("DENOISE")
    level = measure_level(pcm, model_rate)
    if gate and is_silent_turn(flags, level):
        return None, [*steps, "VAD_NO_SPEECH"], 0.0
    if trim and regions:
        trimmed = trim_to_regions(pcm, model_rate, regions)
        if len(trimmed) < len(pcm):
            pcm = trimmed
            steps.append("TRIM")
    pcm, gain_db = normalize_gain(pcm, level)
    if gain_db:
        steps.append("GAIN_NORMALIZE")
    return pcm, steps, gain_db
