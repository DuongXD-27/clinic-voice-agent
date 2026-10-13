"""SileroOnnxClassifier: cùng model v4 thì trùng SileroVadClassifier (sherpa-onnx, production) từng
frame; máy trạng thái bắt đầu / giữ / nhả như sherpa; `silero_vad_version` chọn đúng bộ phân loại."""

from pathlib import Path

import numpy as np
import pytest

from speech.asr.vad.silero_onnx import SileroOnnxClassifier

_V4 = Path("src/speech/asr/vad/assets/silero_vad.onnx")
_V6 = Path("src/speech/asr/vad/assets/silero_vad_v6.onnx")
# Câu TTS thật 8 kHz có trong repo (cache TTS tĩnh đang phát trên production).
_TTS = Path(
    "assets/tts/static/2026-10-08-v1/001_ASK_CHANGE_OR_CANCEL_anh-chi-muon-doi-lich-hay-huy-lich.wav"
)
_FRAME = 480  # 30 ms ở 16 kHz


def _speechlike(seconds: float, seed: int) -> np.ndarray:
    """Tín hiệu có hài + biên độ dao động như âm tiết (Silero gắn cờ được), xen khoảng lặng."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * 16000)) / 16000
    f0 = 140 + 30 * np.sin(2 * np.pi * 0.7 * t)
    voiced = sum(np.sin(2 * np.pi * k * np.cumsum(f0) / 16000) / k for k in range(1, 12))
    syllables = (np.sin(2 * np.pi * 4.0 * t) > -0.2).astype(float)
    pauses = ((t % 3.0) < 1.8).astype(float)
    x = 6000 * voiced * syllables * pauses + rng.normal(0, 30, t.size)
    return np.clip(x, -32768, 32767).astype(np.int16)


def _flags(classifier, pcm: np.ndarray) -> list[bool]:
    return [
        classifier.is_speech(pcm[i : i + _FRAME].tobytes())
        for i in range(0, len(pcm) - _FRAME + 1, _FRAME)
    ]


@pytest.mark.skipif(not _V4.is_file(), reason="chưa tải silero_vad.onnx (config/speech.yaml)")
def test_same_v4_model_gives_the_same_frames_as_the_sherpa_classifier() -> None:
    pytest.importorskip("onnxruntime")
    pytest.importorskip("sherpa_onnx")
    from speech.asr.vad.silero import SileroVadClassifier

    pcm = _speechlike(12.0, seed=1)
    sherpa = _flags(SileroVadClassifier(str(_V4), sample_rate=16000), pcm)
    onnx = _flags(SileroOnnxClassifier(str(_V4), sample_rate=16000), pcm)

    assert any(sherpa)  # tín hiệu thử có được nhận là tiếng nói
    assert onnx == sherpa


class _Scripted(SileroOnnxClassifier):
    """Bỏ model: xác suất theo kịch bản, mỗi cửa sổ 512 mẫu (32 ms) một giá trị."""

    def __init__(self, probs: list[float], **kwargs) -> None:  # noqa: D107
        self._probs = iter(probs)
        self._threshold = kwargs.get("threshold", 0.5)
        self._min_speech = kwargs.get("min_speech_ms", 250) / 1000
        self._min_silence = kwargs.get("min_silence_ms", 500) / 1000
        self._resampler = None
        self._pending = np.empty(0, dtype=np.float32)
        self._now = 0.0
        self._triggered = False
        self._temp_start = None
        self._temp_end = None

    def _prob(self, window: np.ndarray) -> float:
        return next(self._probs)


def _run(probs: list[float]) -> list[bool]:
    vad = _Scripted(probs)
    window = np.zeros(512, dtype=np.int16).tobytes()
    return [vad.is_speech(window) for _ in probs]


def test_speech_starts_only_after_250_ms_above_threshold() -> None:
    flags = _run([0.9] * 12)
    # cửa sổ 32 ms: cần (n − 1) · 32 ms ≥ 250 ms -> cửa sổ thứ 9 (index 8)
    assert flags.index(True) == 8


def test_holds_above_lower_threshold_and_releases_after_500_ms_below() -> None:
    probs = [0.9] * 10 + [0.4] * 5 + [0.1] * 20
    flags = _run(probs)
    assert all(flags[8:15])  # 0,4 > 0,5 − 0,15: vẫn đang nói
    released = flags.index(False, 15)
    assert 15 + 15 <= released <= 15 + 17  # ~500 ms dưới ngưỡng thấp rồi mới nhả


def test_a_short_rise_between_thresholds_does_not_reset_the_silence_timer() -> None:
    """Như sherpa: mốc bắt đầu im chỉ xoá khi > ngưỡng; 0,4 chen giữa không kéo dài thêm 500 ms."""
    probs = [0.9] * 10 + [0.1] * 8 + [0.4] * 3 + [0.1] * 20
    flags = _run(probs)
    assert flags.index(False, 10) <= 10 + 17


@pytest.mark.skipif(not _V6.is_file(), reason="chưa tải silero_vad_v6.onnx (config/speech.yaml)")
def test_v6_flags_real_speech_and_releases_after_it() -> None:
    soundfile = pytest.importorskip("soundfile")
    pytest.importorskip("soxr")
    speech, rate = soundfile.read(_TTS, dtype="int16")
    pad = np.random.default_rng(0).normal(0, 3, rate).astype(np.int16)  # 1 s nền rất nhỏ
    pcm = np.concatenate([pad, speech, pad, pad])
    frame = int(0.03 * rate)
    vad = SileroOnnxClassifier(str(_V6), sample_rate=rate)
    flags = np.array(
        [vad.is_speech(pcm[i : i + frame].tobytes()) for i in range(0, len(pcm) - frame + 1, frame)]
    )
    times = np.arange(len(flags)) * 0.03
    end = 1.0 + len(speech) / rate

    assert not flags[times < 1.0].any()
    assert flags[(times > 1.0) & (times < end)].mean() > 0.5
    assert not flags[times > end + 0.5 + 0.1].any()  # nhả sau min_silence 500 ms


def _settings(**overrides):
    from speech.settings import SpeechSettings

    return SpeechSettings(**overrides, _env_file=None)


@pytest.mark.skipif(not _V4.is_file(), reason="chưa tải silero_vad.onnx (config/speech.yaml)")
def test_version_setting_picks_the_classifier() -> None:
    pytest.importorskip("onnxruntime")
    pytest.importorskip("sherpa_onnx")
    from speech.asr.vad.silero import SileroVadClassifier
    from speech.bundle import build_silero_classifier

    # File v4 đứng thay cho v6: chỉ kiểm việc chọn đường chạy, không cần tải model v6.
    v6 = build_silero_classifier(
        _settings(silero_vad_version="v6", silero_vad_v6_model_path=str(_V4)), 16000
    )
    v4 = build_silero_classifier(_settings(silero_vad_version="v4"), 16000)

    assert isinstance(v6, SileroOnnxClassifier)
    assert isinstance(v4, SileroVadClassifier)


@pytest.mark.skipif(not _V4.is_file(), reason="chưa tải silero_vad.onnx (config/speech.yaml)")
def test_v6_without_its_model_file_falls_back_to_v4(tmp_path, caplog) -> None:
    """Image chưa có file v6: cuộc gọi vẫn có VAD (v4), chỉ cảnh báo."""
    pytest.importorskip("sherpa_onnx")
    from speech.asr.vad.silero import SileroVadClassifier
    from speech.bundle import build_silero_classifier

    missing = tmp_path / "missing.onnx"
    vad = build_silero_classifier(
        _settings(silero_vad_version="v6", silero_vad_v6_model_path=str(missing)), 16000
    )

    assert isinstance(vad, SileroVadClassifier)
    assert "missing.onnx" in caplog.text


@pytest.mark.skipif(not _V4.is_file(), reason="chưa tải silero_vad.onnx (config/speech.yaml)")
def test_instances_share_one_session_per_model_file() -> None:
    """Tạo session ~0,1 s: một lần mỗi process (prewarm), không phải mỗi cuộc gọi."""
    pytest.importorskip("onnxruntime")
    first = SileroOnnxClassifier(str(_V4))
    second = SileroOnnxClassifier(str(_V4))

    assert first._session is second._session


def test_warm_up_vad_preloads_v6_only_when_a_channel_uses_it(tmp_path, monkeypatch) -> None:
    from speech import bundle
    from speech.asr.vad import silero_onnx

    loaded: list[str] = []
    monkeypatch.setattr(silero_onnx, "preload", loaded.append)
    model = tmp_path / "v6.onnx"
    model.write_bytes(b"")

    bundle.warm_up_vad(_settings(silero_vad_version="v4", silero_vad_v6_model_path=str(model)))
    bundle.warm_up_vad(
        _settings(
            silero_vad_version="v4",
            silero_vad_v6_model_path=str(model),
            phone_overrides={"silero_vad_version": "v6"},
        )
    )
    bundle.warm_up_vad(
        _settings(silero_vad_version="v6", silero_vad_v6_model_path=str(tmp_path / "missing"))
    )

    assert loaded == [str(model)]  # chỉ ca SIP dùng v6 và có file


def test_phone_overrides_accept_the_version_key() -> None:
    """Bật riêng cho SIP: khoá hợp lệ trong phone_overrides (khoá lạ bị từ chối)."""
    settings = _settings(phone_overrides={"silero_vad_version": "v6"})

    assert settings.phone_overrides["silero_vad_version"] == "v6"
