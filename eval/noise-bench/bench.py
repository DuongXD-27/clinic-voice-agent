"""Đo độ chính xác pipeline streaming LiveKit (VAD -> ASR -> Turn) dưới nhiễu.

Khác `eval/stt-bench` (gọi `transcribe()` batch trên audio sạch): mỗi câu được đặt giữa đoạn
đệm trước/sau, trộn nhiễu ở SNR xác định, rồi đẩy TỪNG FRAME 30 ms qua đúng
`STTPipeline.stream()` mà worker LiveKit dùng (VAD, ZipFormer chunked-offline,
TurnController + Validator). Đo cả text ASR final lẫn turn thực sự gửi lên core.

Bộ dữ liệu (`--dataset`):
- `web` (mặc định): câu thật của người thử nghiệm, 16 kHz đầy đủ dải, cắt từ dump
  `temp/audio/livekit_debug_web-*.wav` của các cuộc gọi yên tĩnh. Không có nhãn — tham chiếu là
  chính model decode đoạn sạch đó.
- `golden`: 40 câu có nhãn của `eval/stt-bench` (8 kHz điện thoại, nâng lên 16 kHz).
- `short`: câu trả lời 1-3 từ ("dạ", "vâng", "có", "đúng rồi", "hủy lịch"...) cắt từ cùng các
  dump yên tĩnh, chỉ giữ đoạn to hơn nền >= 15 dB (giọng người gọi, không phải ảo giác). Đây là
  loại câu dễ bị validator/bộ lọc từ đệm bỏ nhầm nhất.

Cấu hình (`--profile`): `production` = đúng cấu hình deploy (Silero VAD + Validator, như
config/speech.yaml); `target` là tên cũ của cùng cấu hình đó; `webrtc-legacy` = deploy trước
28/09 (WebRTC VAD, không Validator). Profile ghi đè hẳn các khoá này, kết quả không phụ thuộc
.env của máy chạy; `--set` ghi đè tiếp lên profile. Kết quả cũ gắn nhãn `production` trước
28/09 là WebRTC; từ 28/09 tới trước khi bỏ speech_shared_detector thực chất là Silero, không
Validator — để ý khi `--compare` với các lần chạy đó.
Xác định (deterministic): TurnController chạy theo đồng hồ ảo (cả `clock` lẫn `sleep`), và
mỗi frame chỉ được đẩy khi VAD + ASR đã xử lý xong frame trước (ASR coi như tức thời). Chạy
hai lần cùng tham số cho kết quả giống hệt — khác biệt giữa hai cấu hình là do cấu hình.

Nguồn nhiễu:
- `office`: đoạn không có giọng nói (theo Silero) cắt tự động từ các bản dump — nhiễu thật
  qua mic + trình duyệt + LiveKit.
- `babble`: 3 luồng giọng người khác (bộ golden) cộng lại — người nói xung quanh.
- `voice2`: MỘT người khác nói chuyện bình thường, có ngắt nghỉ giữa các câu — người nhà hay
  đồng nghiệp bên cạnh. Giọng lấy từ bộ khác người với bộ đang đo (golden <-> web). Mức trộn
  tính trên đoạn có giọng, không tính khoảng nghỉ.

Kênh (`--channel`): `web` đưa thẳng 16 kHz như LiveKit web. `phone` mô phỏng đường SIP: trộn
nhiễu ở 16 kHz (nhiễu tới mic trước codec) -> hạ 8 kHz -> G.711 μ-law -> nâng lại 16 kHz như
LiveKit đưa vào AudioStream. Tham chiếu `clean_batch` cũng qua cùng kênh, nên `*_drift` chỉ đo
ảnh hưởng của nhiễu; ảnh hưởng của kênh nằm trong `wer_golden`/`wer_turn` (so với nhãn).

Chỉ số chính:
- `wer_turn_drift`/`wer_turn`: WER của turn gửi lên core so với decode sạch / so với nhãn.
- `wer_drift`/`wer_golden`: như trên nhưng ở mức ASR final. `wer_golden` chỉ tính câu không
  có chữ số (nhãn "14" vs model "mười bốn" sai lệch có hệ thống).
- `dropped_turns`: ASR có chữ nhưng không thành turn. `false_turns`: trial chỉ có nhiễu mà
  vẫn thành turn.
- `latency_p50`/`latency_p90`: giây từ lúc hết câu (theo audio) tới lúc turn được chốt.
- `decode_calls`/`decode_s`: số lần và tổng giây CPU gọi model ASR (partial + final).

Chạy (từ gốc repo; dữ liệu và kết quả nằm trong temp/noise-bench/, không commit):
    PYTHONPATH=src .venv/bin/python eval/noise-bench/bench.py --label moi --profile production
    PYTHONPATH=src .venv/bin/python eval/noise-bench/bench.py --label moi --dataset golden
    PYTHONPATH=src .venv/bin/python eval/noise-bench/bench.py --label x --set vad_end_silence_ms=500
    PYTHONPATH=src .venv/bin/python eval/noise-bench/bench.py --compare cu moi
So với code cũ: tạo git worktree của commit cũ rồi chạy với NOISE_BENCH_SRC=<worktree>/src.
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import heapq
import itertools
import json
import os
import re
import sys
import time
import wave
from pathlib import Path
from typing import AsyncIterator, NamedTuple

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[2]
# NOISE_BENCH_SRC: chạy bộ đo trên mã nguồn khác (vd. một git worktree của commit cũ) để so
# sánh A/B trên cùng dữ liệu; dữ liệu/model vẫn đọc từ repo hiện tại.
sys.path.insert(0, os.environ.get("NOISE_BENCH_SRC", str(ROOT / "src")))
sys.path.insert(0, str(ROOT / "eval" / "stt-bench"))

from evaluate import calculate_wer  # noqa: E402

from callbot.transports.livekit.settings import LiveKitSettings  # noqa: E402
from inference.asr import create_asr_gateway  # noqa: E402
from inference.asr.providers.zipformer import ZipFormerASR  # noqa: E402
from speech.asr.recognizer import SpeechRecognizer  # noqa: E402
from speech.audio.codec import resample  # noqa: E402
from speech.audio.g711 import mulaw_to_pcm16  # noqa: E402
from speech.bundle import build_streaming_bundle, turn_controller_options  # noqa: E402
from speech.settings import SpeechSettings  # noqa: E402
from speech.turn.controller import TurnController  # noqa: E402
from speech.turn.interruption import InterruptionController, InterruptionState  # noqa: E402
from speech.types import AudioSegment  # noqa: E402

RATE = 16_000
FRAME = RATE * 30 // 1000
LEAD_S = 1.2
TAIL_S = 2.0
WORK_DIR = ROOT / "temp" / "noise-bench"
GOLDEN = ROOT / "eval" / "stt-bench" / "golden-cases.yaml"
DEFAULT_CONDITIONS = "clean,office@15,office@8,office@3,babble@12,babble@6"
PHONE_RATE = 8_000
CHANNELS = ("web", "phone")
NOISE_ONLY_TRIALS = 12
FRAME_S = FRAME / RATE
# Phải khớp config/speech.yaml: deploy đổi sang Silero + Validator từ 28/09
# (docs/evidence/livekit-audio-plan-execution-2026-09-28.md §5.2).
_PRODUCTION = {
    "vad_provider": "silero",
    "turn_validator_enabled": True,
}
PROFILES: dict[str, dict[str, object]] = {
    "production": _PRODUCTION,
    # Tên cũ của cấu hình Silero + Validator trước khi lên production; giữ cho lệnh trong docs.
    "target": _PRODUCTION,
    # Deploy trước 28/09, để so với số đo cũ.
    "webrtc-legacy": {
        "vad_provider": "webrtc",
        "turn_validator_enabled": False,
    },
}


def _read_wav(path: Path | str) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate()
        pcm = w.readframes(w.getnframes())
        channels = w.getnchannels()
    samples = np.frombuffer(pcm, dtype=np.int16)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1).astype(np.int16)
    return samples, rate


def _write_wav(path: Path, samples: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(samples.astype(np.int16).tobytes())


def _to_16k(samples: np.ndarray, rate: int) -> np.ndarray:
    if rate == RATE:
        return samples.astype(np.float32)
    pcm = resample(samples.astype(np.int16).tobytes(), rate, RATE)
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32)


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if x.size else 0.0


def _active_rms(x: np.ndarray) -> float:
    """RMS chỉ trên các frame có giọng (trong vòng 30 dB so với frame to nhất)."""
    frames = [x[i : i + FRAME] for i in range(0, len(x) - FRAME + 1, FRAME)]
    levels = np.array([_rms(f) for f in frames])
    if not levels.size or levels.max() == 0:
        return 0.0
    active = levels[levels >= levels.max() * 10 ** (-30 / 20)]
    return float(np.sqrt(np.mean(active**2)))


def build_office_noise(model_path: str, max_seconds: float = 180.0) -> np.ndarray:
    """Cắt đoạn không có giọng nói (Silero) >= 1.5 s, bỏ 300 ms mỗi biên để tránh dính đầu/đuôi
    câu, chỉ giữ đoạn có nhiễu nghe được (RMS >= 10, tức >= 20 dB) — đoạn gần như im lặng số
    (trình duyệt đã khử nhiễu) không mang thông tin gì để đo."""
    cache = WORK_DIR / "office_noise.wav"
    if cache.exists():
        samples, _ = _read_wav(cache)
        return samples.astype(np.float32)

    from speech.asr.vad.silero import SileroVadClassifier

    pieces: list[np.ndarray] = []
    total = 0
    paths = sorted(glob.glob(str(ROOT / "temp" / "audio" / "livekit_debug_web-*.wav")))
    for path in paths:
        if os.path.getsize(path) < 200_000:
            continue
        samples, rate = _read_wav(path)
        if rate != RATE:
            continue
        vad = SileroVadClassifier(model_path, sample_rate=RATE)
        flags = [
            vad.is_speech(samples[i : i + FRAME].tobytes())
            for i in range(0, len(samples) - FRAME + 1, FRAME)
        ]
        run_start = None
        per_file = 0
        for idx, is_speech in enumerate([*flags, True]):
            if not is_speech and run_start is None:
                run_start = idx
            elif is_speech and run_start is not None:
                start, end = (run_start + 10) * FRAME, (idx - 10) * FRAME
                run_start = None
                if end - start < int(1.5 * RATE):
                    continue
                segment = samples[start:end].astype(np.float32)
                if _rms(segment) < 10 or per_file > 20 * RATE:
                    continue
                pieces.append(segment)
                per_file += len(segment)
                total += len(segment)
        if total >= max_seconds * RATE:
            break
    if not pieces:
        raise RuntimeError("Không tìm được đoạn nhiễu nào trong temp/audio/livekit_debug_web-*.wav")
    noise = np.concatenate(pieces)
    _write_wav(cache, noise)
    return noise


def build_babble(speech_clips: list[np.ndarray], seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    streams = []
    for _ in range(3):
        order = rng.permutation(len(speech_clips))
        stream = np.concatenate(
            [speech_clips[i] / max(_active_rms(speech_clips[i]), 1.0) for i in order]
        )
        streams.append(stream)
    length = min(len(s) for s in streams)
    babble = sum(s[:length] for s in streams)
    return babble * (1000.0 / _rms(babble))


def build_voice2(speech_clips: list[np.ndarray], seed: int = 11) -> np.ndarray:
    """Một người khác nói chuyện: các câu nối nhau, nghỉ 0,3-1,5 s giữa hai câu."""
    rng = np.random.default_rng(seed)
    parts = []
    for i in rng.permutation(len(speech_clips)):
        parts.append(speech_clips[i] / max(_active_rms(speech_clips[i]), 1.0))
        parts.append(np.zeros(int(rng.uniform(0.3, 1.5) * RATE), dtype=np.float32))
    stream = np.concatenate(parts)
    return stream * (1000.0 / _active_rms(stream))


# Nguồn nhiễu là giọng người có khoảng nghỉ: đo mức trên đoạn có giọng, như với câu người gọi.
_SPEECH_LIKE_NOISE = frozenset({"voice2"})


def _mulaw_encode(samples: np.ndarray) -> bytes:
    """Lượng tử G.711 μ-law về mức gần nhất trong chính bảng giải mã của `speech.audio.g711`."""
    levels = np.frombuffer(mulaw_to_pcm16(bytes(range(256))), dtype=np.int16).astype(np.int32)
    order = np.argsort(levels, kind="stable")
    ordered = levels[order]
    x = samples.astype(np.int32)
    upper = np.clip(np.searchsorted(ordered, x), 1, len(ordered) - 1)
    lower = upper - 1
    nearest = np.where(x - ordered[lower] <= ordered[upper] - x, lower, upper)
    return order[nearest].astype(np.uint8).tobytes()


def phone_channel(samples: np.ndarray) -> np.ndarray:
    """16 kHz -> 8 kHz -> G.711 μ-law -> 16 kHz, giữ nguyên số mẫu."""
    pcm = np.clip(np.round(samples), -32768, 32767).astype(np.int16).tobytes()
    narrow = np.frombuffer(resample(pcm, RATE, PHONE_RATE), dtype=np.int16)
    coded = mulaw_to_pcm16(_mulaw_encode(narrow))
    wide = np.frombuffer(resample(coded, PHONE_RATE, RATE), dtype=np.int16)
    out = np.zeros(len(samples), dtype=np.int16)
    out[: min(len(wide), len(out))] = wide[: len(out)]
    return out


def make_trial(
    speech: np.ndarray | None,
    noise: np.ndarray | None,
    snr_db: float | None,
    rng: np.random.Generator,
    *,
    noise_rms_target: float | None = None,
    speech_like_noise: bool = False,
) -> np.ndarray:
    speech_len = 0 if speech is None else len(speech)
    total = int(LEAD_S * RATE) + speech_len + int(TAIL_S * RATE)
    mix = np.zeros(total, dtype=np.float64)
    if speech is not None:
        lead = int(LEAD_S * RATE)
        mix[lead : lead + speech_len] = speech
    if noise is None:
        mix += rng.normal(0.0, 1.0, total)  # dither nhẹ, tương đương "im lặng" sau khử nhiễu
    else:
        start = int(rng.integers(0, len(noise) - total))
        segment = noise[start : start + total].astype(np.float64)
        level = max((_active_rms if speech_like_noise else _rms)(segment), 1e-6)
        if noise_rms_target is not None:
            gain = noise_rms_target / level
        else:
            gain = _active_rms(speech) / (level * 10 ** (snr_db / 20))
        mix += gain * segment
    return np.clip(np.round(mix), -32768, 32767).astype(np.int16)


class VirtualTime:
    """Đồng hồ + hẹn giờ ảo cho TurnController: thời gian chỉ tiến khi bộ đo đẩy frame."""

    def __init__(self) -> None:
        self._ms = 0
        self._seq = itertools.count()
        self._sleepers: list[tuple[int, int, asyncio.Future]] = []

    def now(self) -> float:
        return self._ms / 1000

    async def sleep(self, delay_s: float) -> None:
        future = asyncio.get_running_loop().create_future()
        deadline = self._ms + max(0, round(delay_s * 1000))
        heapq.heappush(self._sleepers, (deadline, next(self._seq), future))
        await future

    def advance(self, ms: int) -> None:
        self._ms += ms
        while self._sleepers and self._sleepers[0][0] <= self._ms:
            future = heapq.heappop(self._sleepers)[2]
            if not future.done():
                future.set_result(None)


class _CapturingRecognizer:
    """Bọc recognizer thật: ghi mọi final (text, confidence) và cho bộ đo biết ASR đang rảnh
    (chờ frame) hay đang bận (decode trong thread) để đẩy frame kế tiếp đúng lúc."""

    def __init__(self, inner: SpeechRecognizer) -> None:
        self._inner = inner
        self.name = inner.name
        self.input_sample_rate = inner.input_sample_rate
        self.supports_preroll_frames = getattr(inner, "supports_preroll_frames", False)
        self.supports_stream_context = getattr(inner, "supports_stream_context", False)
        self.finals: list[str] = []
        self.final_confidences: list[float | None] = []
        self.waiting = True
        # Decode cả đoạn (lời chen giữ riêng, STTPipeline keep_unconfirmed_barge_in): đang chạy, và
        # thời gian thật từng lần — đồng hồ ảo không tính phần này.
        self.batch_busy = 0
        self.batch_seconds: list[float] = []

    def transcribe(self, segment):
        started = time.perf_counter()
        self.batch_busy += 1
        try:
            return self._inner.transcribe(segment)
        finally:
            self.batch_busy -= 1
            self.batch_seconds.append(time.perf_counter() - started)

    async def stream(self, frames: AsyncIterator[bytes], **kwargs):
        async def pulled():
            iterator = frames.__aiter__()
            while True:
                self.waiting = True
                try:
                    item = await iterator.__anext__()
                except StopAsyncIteration:
                    self.waiting = False
                    return
                self.waiting = False
                yield item

        async for event in self._inner.stream(pulled(), **kwargs):
            if event.is_final:
                self.finals.append(event.text)
                self.final_confidences.append(event.confidence)
            yield event
        self.waiting = True


async def _settle(recognizer: _CapturingRecognizer) -> None:
    """Chờ tới khi VAD/Turn (chạy trên event loop) và ASR (decode trong thread) xử lý xong
    mọi frame đã đẩy: ASR phải ở trạng thái chờ frame qua vài vòng event loop liên tiếp."""
    stable = 0
    while stable < 4:
        await asyncio.sleep(0)
        if recognizer.waiting and not recognizer.batch_busy:
            stable += 1
        else:
            stable = 0
            await asyncio.sleep(0.0002)


class DecodeMeter:
    """Đếm số lần gọi model ASR và tổng thời gian — chi phí thật của chunked-offline."""

    def __init__(self) -> None:
        self.calls = 0
        self.seconds = 0.0
        self.audio_seconds = 0.0
        self._original = ZipFormerASR._decode_scored
        meter = self

        def counted(asr_self, pcm: bytes):
            started = time.perf_counter()
            try:
                return meter._original(asr_self, pcm)
            finally:
                meter.calls += 1
                meter.seconds += time.perf_counter() - started
                meter.audio_seconds += len(pcm) / 2 / ZipFormerASR.input_sample_rate

        ZipFormerASR._decode_scored = counted

    def snapshot(self) -> tuple[int, float, float]:
        return self.calls, self.seconds, self.audio_seconds


def _livekit_queues() -> dict[str, int]:
    """Hàng đợi/pre-roll như worker LiveKit thật (config/livekit.yaml); frame cố định 30 ms
    vì bộ đo cắt audio theo `FRAME`."""
    livekit = LiveKitSettings()
    return {
        "frame_ms": FRAME * 1000 // RATE,
        "input_queue_ms": livekit.input_queue_ms,
        "asr_queue_ms": livekit.asr_queue_ms,
        "barge_in_preroll_ms": livekit.barge_in_preroll_ms,
    }


class BotTurn(NamedTuple):
    """Bot nói câu `text` (audio TTS `audio`) trong [start_s, end_s) (giây trong trial). `echo`:
    tiếng bot vọng về mic người gọi, cùng độ dài trial, chỉ cộng vào khi bot còn đang phát —
    ngắt lời được xác nhận thì echo dừng như CallBridge xoá hàng đợi phát."""

    start_s: float
    end_s: float
    text: str
    echo: np.ndarray
    audio: np.ndarray


async def run_pipeline(
    pcm: np.ndarray,
    settings: SpeechSettings,
    asr: SpeechRecognizer,
    bot: BotTurn | list[BotTurn] | None = None,
) -> dict:
    """Trả ASR finals (+ confidence), turn TurnController chốt gửi lên core, thời điểm (giây
    audio) chốt từng turn. Có `bot`: thêm mốc ứng viên ngắt lời
    (`barge_in_candidates`) và lúc ngắt lời được xác nhận (`barge_in_at`), dùng
    InterruptionController như worker. Nhiều `BotTurn` = các câu bot lần lượt trong cùng cuộc
    gọi (một InterruptionController); mốc ngắt lời là của câu cuối. Xác định: xem docstring module."""
    bots = [bot] if isinstance(bot, BotTurn) else list(bot or [])
    recognizer = _CapturingRecognizer(asr)
    clock = VirtualTime()
    bundle = build_streaming_bundle(
        settings,
        sample_rate=RATE,
        **_livekit_queues(),
        asr=recognizer,
    )
    # Bundle dựng TurnController theo đồng hồ thật; bộ đo đẩy audio nhanh hơn thời gian thực nên
    # dựng lại cùng cấu hình, chạy theo đồng hồ ảo.
    controller = TurnController(
        validator=bundle.validator,
        clock=clock.now,
        sleep=clock.sleep,
        **turn_controller_options(settings),
    )
    frame_ms = FRAME * 1000 // RATE

    interruption = None
    barge_in: dict[str, object] = {"at": None, "candidates": []}
    if bots:

        class _Playout:
            async def cancel(self) -> None:
                barge_in["at"] = clock.now()

        interruption = InterruptionController(
            _Playout(),
            clock=clock.now,
            validator=bundle.validator,
            min_snr_db=settings.interruption_min_snr_db,
            echo_policy=settings.turn_echo_policy,
        )
        on_speech_started = interruption.on_speech_started

        async def recording_speech_started(event) -> None:
            await on_speech_started(event)
            if interruption.state == InterruptionState.INTERRUPTION_CANDIDATE:
                barge_in["candidates"].append(clock.now())

        interruption.on_speech_started = recording_speech_started
    bot_state = {"speaking": False, "index": 0}

    def update_bot(now: float) -> None:
        """Như CallBridge._speak: báo bot bắt đầu nói; dừng khi phát hết hoặc bị ngắt lời."""
        if bot_state["index"] >= len(bots):
            return
        bot = bots[bot_state["index"]]
        if not bot_state["speaking"] and now >= bot.start_s:
            bot_state["speaking"] = True
            controller.on_bot_speaking_changed(True)
            interruption.on_bot_started_speaking(bot.text)
            pcm = np.clip(np.round(bot.audio), -32768, 32767).astype(np.int16).tobytes()
            interruption.on_bot_audio(pcm, RATE, complete=True)
        elif bot_state["speaking"] and (barge_in["at"] is not None or now >= bot.end_s):
            bot_state.update(speaking=False, index=bot_state["index"] + 1)
            controller.on_bot_speaking_changed(False, preserve_candidate=barge_in["at"] is not None)
            interruption.on_bot_stopped_speaking()

    frames_ended = asyncio.Event()

    async def frames() -> AsyncIterator[bytes]:
        for i in range(0, len(pcm) - FRAME + 1, FRAME):
            clock.advance(frame_ms)
            await _settle(recognizer)
            update_bot(clock.now())
            frame = pcm[i : i + FRAME]
            if bot_state["speaking"]:
                echo = bots[bot_state["index"]].echo[i : i + FRAME]
                frame = np.clip(frame + echo, -32768, 32767).astype(np.int16)
            yield frame.tobytes()
            await _settle(recognizer)
        # Hết audio: cho các hẹn giờ còn chờ (timeout sau speech_end) kịp chạy.
        for _ in range(2000 // frame_ms):
            clock.advance(frame_ms)
            await _settle(recognizer)
        frames_ended.set()

    async def drain_clock() -> None:
        # ASR có thể trả final hoặc khôi phục lời chen sau EOF. Lúc đó TurnController mới
        # đặt hẹn giờ gộp lượt; tiếp tục đồng hồ đến khi pipeline đóng hết lượt.
        await frames_ended.wait()
        while True:
            await _settle(recognizer)
            clock.advance(frame_ms)

    turns: list[str] = []
    turn_times: list[float] = []
    drain_task = asyncio.create_task(drain_clock())
    try:
        async for turn in bundle.stt_pipeline.stream(
            frames(), turn_controller=controller, interruption=interruption
        ):
            turns.append(turn.text)
            turn_times.append(clock.now())
    finally:
        drain_task.cancel()
        await asyncio.gather(drain_task, return_exceptions=True)
    return {
        "finals": recognizer.finals,
        "final_confidences": recognizer.final_confidences,
        "turns": turns,
        "turn_times": turn_times,
        "barge_in_candidates": barge_in["candidates"],
        "barge_in_at": barge_in["at"],
        "batch_decode_s": recognizer.batch_seconds,
    }


def _has_digit(text: str) -> bool:
    return bool(re.search(r"\d", text))


def _wer(reference: str, prediction: str) -> tuple[int, int]:
    metrics = calculate_wer(reference, prediction)
    errors = metrics.substitutions + metrics.deletions + metrics.insertions
    return errors, metrics.reference_word_count


# Câu theo kịch bản thử nghiệm (tên, ngày sinh, xác nhận) — phân biệt với tiếng người khác
# hoặc câu nói ngoài lề cũng lọt vào mic trong cùng cuộc gọi.
_SCRIPT_RE = re.compile(
    r"^(TÔI (LÀ|TÊN|SINH|KHÔNG ĐẾN|ĐỒNG Ý)|(SINH )?NGÀY|MƯỜI BỐN|NGUYỄN VĂN A$|A LÔ|ĐÚNG|CÓ TÔI|KHÔNG ĐƯỢC$)"
)


def build_web_set(asr: SpeechRecognizer, model_path: str) -> list[dict]:
    """Câu thật của người thử nghiệm, đầy đủ dải 16 kHz, cắt từ dump LiveKit của các cuộc gọi
    yên tĩnh (nhiễu nền < 10 dB). Tham chiếu = chính model decode đoạn sạch đó."""
    cache = WORK_DIR / "web_set.json"
    if not cache.exists():
        from speech.asr.vad.silero import SileroVadClassifier

        found = []
        for path in sorted(glob.glob(str(ROOT / "temp" / "audio" / "livekit_debug_web-*.wav"))):
            if os.path.getsize(path) < 200_000:
                continue
            samples, rate = _read_wav(path)
            if rate != RATE:
                continue
            vad = SileroVadClassifier(model_path, sample_rate=RATE)
            flags = [
                vad.is_speech(samples[i : i + FRAME].tobytes())
                for i in range(0, len(samples) - FRAME + 1, FRAME)
            ]
            quiet = [
                _rms(samples[i * FRAME : (i + 1) * FRAME]) for i, f in enumerate(flags) if not f
            ]
            if not quiet or 20 * np.log10(np.median(quiet) + 1e-6) > 10:
                continue
            i = 0
            while i < len(flags):
                if not flags[i]:
                    i += 1
                    continue
                j = i
                while j < len(flags) and flags[j]:
                    j += 1
                # lùi 450 ms: Silero nhận speech trễ, không cắt mất âm đầu
                start, end = max(0, (i - 15) * FRAME), min(len(samples), (j + 5) * FRAME)
                if 0.8 <= (end - start) / RATE <= 8:
                    pcm = samples[start:end].astype(np.int16).tobytes()
                    text = asr.transcribe(AudioSegment(pcm=pcm, sample_rate=RATE)).text
                    if _SCRIPT_RE.match(text):
                        found.append({"file": os.path.basename(path), "start": start, "end": end})
                i = j
        cache.write_text(json.dumps(found, indent=1), encoding="utf-8")
    cases = []
    loaded: dict[str, np.ndarray] = {}
    for idx, item in enumerate(json.loads(cache.read_text(encoding="utf-8"))):
        if item["file"] not in loaded:
            loaded[item["file"]] = _read_wav(ROOT / "temp" / "audio" / item["file"])[0]
        speech = loaded[item["file"]][item["start"] : item["end"]].astype(np.float32)
        cases.append({"id": f"WEB_{idx:02d}", "reference": None, "speech": speech})
    return cases


# Câu trả lời ngắn theo kịch bản (xác nhận, chọn, huỷ) — model trả chữ in hoa.
SHORT_ANSWERS = frozenset(
    {
        "DẠ", "VÂNG", "CÓ", "KHÔNG", "ĐÚNG", "ĐÚNG RỒI", "CHƯA ĐÚNG", "KHÔNG ĐÚNG", "OK",
        "Ừ", "ỪM", "ĐƯỢC", "KHÔNG ĐƯỢC", "ĐỒNG Ý", "HỦY LỊCH", "HUỶ LỊCH", "ĐỔI LỊCH",
        "GIỮ LỊCH", "A LÔ", "ALÔ", "DẠ VÂNG", "VÂNG Ạ", "DẠ CÓ", "CÓ Ạ", "DẠ ĐÚNG RỒI",
        "ĐÚNG RỒI Ạ", "DẠ KHÔNG", "KHÔNG Ạ", "CÓ TÔI", "TÔI ĐỒNG Ý",
    }
)  # fmt: skip


def build_short_set(asr: SpeechRecognizer, model_path: str) -> list[dict]:
    """Câu trả lời 1-3 từ thật của người thử nghiệm, cùng nguồn và cách cắt với bộ web.

    Nền các cuộc gọi yên tĩnh gần như im lặng số (trình duyệt đã khử nhiễu) nên so với nền thì
    tiếng gõ phím cũng "to"; lọc theo mức tuyệt đối: RMS giọng >= 300 và >= 150 ms frame to hơn
    300 (bộ web: p10 = 2346). Chưa có nhãn tay — các đoạn "Ừ" cần người nghe lại xác nhận."""
    cache = WORK_DIR / "short_set.json"
    if not cache.exists():
        from speech.asr.vad.silero import SileroVadClassifier

        found = []
        for path in sorted(glob.glob(str(ROOT / "temp" / "audio" / "livekit_debug_web-*.wav"))):
            if os.path.getsize(path) < 200_000:
                continue
            samples, rate = _read_wav(path)
            if rate != RATE:
                continue
            vad = SileroVadClassifier(model_path, sample_rate=RATE)
            flags = [
                vad.is_speech(samples[i : i + FRAME].tobytes())
                for i in range(0, len(samples) - FRAME + 1, FRAME)
            ]
            quiet = [
                _rms(samples[i * FRAME : (i + 1) * FRAME]) for i, f in enumerate(flags) if not f
            ]
            if not quiet:
                continue
            floor = float(np.median(quiet))
            if 20 * np.log10(floor + 1e-6) > 10:
                continue
            i = 0
            while i < len(flags):
                if not flags[i]:
                    i += 1
                    continue
                j = i
                while j < len(flags) and flags[j]:
                    j += 1
                start, end = max(0, (i - 15) * FRAME), min(len(samples), (j + 5) * FRAME)
                if 0.5 <= (end - start) / RATE <= 3.0:
                    region = samples[start:end].astype(np.float32)
                    level = _active_rms(region)
                    loud_ms = 30 * sum(
                        _rms(region[k : k + FRAME]) > 300
                        for k in range(0, len(region) - FRAME + 1, FRAME)
                    )
                    snr_db = 20 * np.log10(level / max(floor, 1.0))
                    pcm = region.astype(np.int16).tobytes()
                    text = asr.transcribe(AudioSegment(pcm=pcm, sample_rate=RATE)).text
                    if level >= 300 and loud_ms >= 150 and text in SHORT_ANSWERS:
                        found.append(
                            {
                                "file": os.path.basename(path),
                                "start": start,
                                "end": end,
                                "text": text,
                                "snr_db": round(float(snr_db), 1),
                            }
                        )
                i = j
        cache.write_text(json.dumps(found, ensure_ascii=False, indent=1), encoding="utf-8")
    cases = []
    loaded: dict[str, np.ndarray] = {}
    for idx, item in enumerate(json.loads(cache.read_text(encoding="utf-8"))):
        if item["file"] not in loaded:
            loaded[item["file"]] = _read_wav(ROOT / "temp" / "audio" / item["file"])[0]
        speech = loaded[item["file"]][item["start"] : item["end"]].astype(np.float32)
        cases.append({"id": f"SHORT_{idx:02d}", "reference": None, "speech": speech})
    return cases


def load_golden() -> list[dict]:
    golden = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))
    cases = []
    for case in golden["cases"]:
        if not case.get("should_produce_text", True):
            continue
        samples, rate = _read_wav(GOLDEN.parent / case["audio"])
        cases.append(
            {"id": case["id"], "reference": case["reference"], "speech": _to_16k(samples, rate)}
        )
    return cases


def _latency(turn_times: list[float], speech_end_s: float) -> float | None:
    """Lượt ĐẦU TIÊN chốt sau khi hết câu — lượt cuối có thể là lượt giả do nhiễu phía sau."""
    after = [t for t in turn_times if t >= speech_end_s]
    return round(after[0] - speech_end_s, 3) if after else None


def _percentile(values: list[float], q: float) -> float | None:
    return round(float(np.percentile(values, q)), 3) if values else None


def run(
    label: str,
    dataset: str,
    conditions: list[str],
    repeats: int,
    profile: str,
    overrides: dict,
    channel: str = "web",
) -> dict:
    overrides = {**PROFILES[profile], **overrides}
    settings = SpeechSettings(**overrides)
    asr = SpeechRecognizer(create_asr_gateway(settings.asr_provider))
    meter = DecodeMeter()

    golden_cases = load_golden()
    web_cases = build_web_set(asr, settings.silero_vad_model_path)
    if dataset == "golden":
        cases = golden_cases
    elif dataset == "short":
        cases = build_short_set(asr, settings.silero_vad_model_path)
    else:
        cases = web_cases
    to_channel = phone_channel if channel == "phone" else (lambda x: x)
    clean_ref: dict[str, str] = {}
    for case in cases:
        clean = to_channel(case["speech"]).astype(np.int16).tobytes()
        clean_ref[case["id"]] = asr.transcribe(AudioSegment(pcm=clean, sample_rate=RATE)).text

    # Giọng người khác lấy từ bộ khác người với bộ đang đo: golden (nhiều người gọi điện thoại)
    # cho bộ web/short (người thử nghiệm), và ngược lại.
    others = web_cases if dataset == "golden" else golden_cases
    noises = {
        "office": build_office_noise(settings.silero_vad_model_path),
        "babble": build_babble([c["speech"] for c in golden_cases]),
        "voice2": build_voice2([c["speech"] for c in others]),
    }
    median_speech_rms = float(np.median([_active_rms(c["speech"]) for c in cases]))

    results: dict = {
        "label": label,
        "dataset": dataset,
        "profile": profile,
        "channel": channel,
        "repeats": repeats,
        "settings": {k: getattr(settings, k) for k in sorted(overrides)},
        "conditions": {},
    }
    for condition in conditions:
        noise_name, _, snr = condition.partition("@")
        noise = None if noise_name == "clean" else noises[noise_name]
        speech_like = noise_name in _SPEECH_LIKE_NOISE
        snr_db = float(snr) if snr else None
        rng = np.random.default_rng(1234)
        started = time.monotonic()
        calls_before, decode_s_before, _ = meter.snapshot()
        rows = []
        for repeat in range(repeats if noise is not None else 1):
            for case in cases:
                pcm = to_channel(
                    make_trial(case["speech"], noise, snr_db, rng, speech_like_noise=speech_like)
                )
                out = asyncio.run(run_pipeline(pcm, settings, asr))
                finals, turns = out["finals"], out["turns"]
                prediction = " ".join(finals)
                drift_err, drift_n = _wer(clean_ref[case["id"]], prediction)
                turn_drift_err, _ = _wer(clean_ref[case["id"]], " ".join(turns))
                row = {
                    "id": case["id"],
                    "repeat": repeat,
                    "reference": case["reference"],
                    "clean_batch": clean_ref[case["id"]],
                    "finals": finals,
                    "final_confidences": out["final_confidences"],
                    "turns": turns,
                    "turn_times": out["turn_times"],
                    "latency_s": _latency(out["turn_times"], LEAD_S + len(case["speech"]) / RATE),
                    "drift_errors": drift_err,
                    "turn_drift_errors": turn_drift_err,
                    "drift_words": drift_n,
                }
                if case["reference"] and not _has_digit(case["reference"]):
                    gold_err, gold_n = _wer(case["reference"], prediction)
                    turn_err, _ = _wer(case["reference"], " ".join(turns))
                    row.update(golden_errors=gold_err, golden_words=gold_n, turn_errors=turn_err)
                rows.append(row)

        false_finals = false_turns = 0
        noise_only_rows = []
        if noise is not None:
            noise_rms = median_speech_rms / 10 ** (snr_db / 20)
            for _ in range(NOISE_ONLY_TRIALS):
                pcm = to_channel(
                    make_trial(
                        None,
                        noise,
                        None,
                        rng,
                        noise_rms_target=noise_rms,
                        speech_like_noise=speech_like,
                    )
                )
                out = asyncio.run(run_pipeline(pcm, settings, asr))
                noise_only_rows.append(
                    {
                        "finals": out["finals"],
                        "final_confidences": out["final_confidences"],
                        "turns": out["turns"],
                    }
                )
                false_finals += bool(out["finals"])
                false_turns += bool(out["turns"])

        calls_after, decode_s_after, _ = meter.snapshot()
        latencies = [r["latency_s"] for r in rows if r["latency_s"] is not None]
        gold_n = sum(r.get("golden_words", 0) for r in rows)
        drift_n = sum(r["drift_words"] for r in rows)
        summary = {
            "wer_golden": sum(r.get("golden_errors", 0) for r in rows) / gold_n if gold_n else None,
            "wer_turn": sum(r.get("turn_errors", 0) for r in rows) / gold_n if gold_n else None,
            "wer_drift": sum(r["drift_errors"] for r in rows) / drift_n if drift_n else None,
            "wer_turn_drift": sum(r["turn_drift_errors"] for r in rows) / drift_n
            if drift_n
            else None,
            "trials": len(rows),
            "empty_output": sum(1 for r in rows if not r["finals"]),
            "dropped_turns": sum(1 for r in rows if r["finals"] and not r["turns"]),
            "no_turn": sum(1 for r in rows if not r["turns"]),
            "split_turns": sum(1 for r in rows if len(r["turns"]) > 1),
            "false_finals": false_finals if noise is not None else None,
            "false_turns": false_turns if noise is not None else None,
            "noise_only_trials": len(noise_only_rows),
            "latency_p50": _percentile(latencies, 50),
            "latency_p90": _percentile(latencies, 90),
            "decode_calls": calls_after - calls_before,
            "decode_s": round(decode_s_after - decode_s_before, 2),
            "seconds": round(time.monotonic() - started, 1),
        }
        results["conditions"][condition] = {
            "summary": summary,
            "cases": rows,
            "noise_only": noise_only_rows,
        }
        shown = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in summary.items()}
        print(f"[{label}] {condition:11} {shown}", flush=True)

    out_path = WORK_DIR / "results" / f"{label}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"-> {out_path.relative_to(ROOT)}")
    return results


_METRICS = (
    ("wer_golden", "WER ASR so với nhãn (câu không chữ số)"),
    ("wer_turn", "WER của turn gửi lên core, so với nhãn"),
    ("wer_drift", "WER ASR lệch so với decode audio sạch"),
    ("wer_turn_drift", "WER của turn gửi lên core, so với decode audio sạch"),
    ("dropped_turns", "câu ASR có chữ nhưng không thành turn"),
    ("no_turn", "câu thật không thành turn nào"),
    ("split_turns", "câu thật bị tách thành nhiều turn"),
    ("false_finals", "trial chỉ có nhiễu mà ASR vẫn ra chữ"),
    ("false_turns", "trial chỉ có nhiễu mà vẫn thành turn"),
    ("latency_p50", "giây từ hết câu tới lúc chốt turn, trung vị"),
    ("latency_p90", "giây từ hết câu tới lúc chốt turn, p90"),
    ("decode_s", "tổng giây CPU decode ASR"),
)


def compare(labels: list[str]) -> None:
    loaded = [json.loads((WORK_DIR / "results" / f"{label}.json").read_text()) for label in labels]
    conditions = list(loaded[0]["conditions"])
    for key, title in _METRICS:
        print(f"\n## {title} ({key})")
        print(f"{'điều kiện':11} " + " ".join(f"{label[:18]:>18}" for label in labels))
        for condition in conditions:
            cells = []
            for result in loaded:
                s = result["conditions"].get(condition, {}).get("summary") or {}
                value = s.get(key)
                if value is None:
                    cells.append(f"{'-':>18}")
                elif isinstance(value, float):
                    cells.append(f"{value:18.3f}")
                else:
                    cells.append(f"{value:>18}")
            print(f"{condition:11} " + " ".join(cells))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label")
    parser.add_argument("--dataset", choices=("web", "golden", "short"), default="web")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="production")
    parser.add_argument("--channel", choices=CHANNELS, default="web")
    parser.add_argument("--conditions", default=DEFAULT_CONDITIONS)
    parser.add_argument(
        "--repeats", type=int, default=2, help="số đoạn nhiễu khác nhau cho mỗi câu"
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KHOÁ=GIÁ_TRỊ",
        help="ghi đè SpeechSettings, vd. --set speech_foreground_gate_enabled=true",
    )
    parser.add_argument("--compare", nargs="+")
    args = parser.parse_args()
    if args.compare:
        compare(args.compare)
        return
    if not args.label:
        parser.error("--label hoặc --compare là bắt buộc")
    overrides = dict(item.split("=", 1) for item in args.set)
    run(
        args.label,
        args.dataset,
        args.conditions.split(","),
        args.repeats,
        args.profile,
        overrides,
        args.channel,
    )


if __name__ == "__main__":
    main()
