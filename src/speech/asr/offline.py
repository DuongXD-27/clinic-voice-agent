"""STT offline trên file WAV — phục vụ PM kiểm tra chất lượng model (stt_eval.py). Hai chế độ:

- `transcribe_turn`: file là MỘT lượt nói (như mỗi audio_url của /v1/calls/{id}/turn). Decode
  nguyên clip một lần sau tiền xử lý nhẹ; `compare` chạy thêm đúng đường production của
  /v1/calls turn (giữ tần số gốc, không tiền xử lý) để PM thấy bot đang nghe ra gì.
- `transcribe_offline`: file dài nhiều câu. VAD tìm các đoạn có giọng, mỗi đoạn decode một lần,
  text ghép theo thời gian; `compare` decode nguyên file không tiền xử lý.

Không mô phỏng streaming. Mọi lần decode dài tối đa `MAX_SEGMENT_MS`: bộ nhớ ZipFormer offline
tăng theo bình phương độ dài audio, file 3 phút decode một lần cần ~12 GB và làm OOM cả server.
Lý do từng bước: docs/reference/stt-eval-api.md.
"""

import logging
import struct
from dataclasses import dataclass
from time import perf_counter_ns
from typing import Callable, Optional

from speech.asr.recognizer import Recognizer
from speech.asr.vad.base import FrameClassifier
from speech.audio.codec import read_wav, to_sample_rate
from speech.audio.preprocess import (
    LevelStats,
    detect_speech_frames,
    estimate_snr_db,
    measure_level,
    normalize_gain,
    remove_dc,
    speech_regions,
    split_long_regions,
)
from speech.types import NARROWBAND_RATE, SAMPLE_WIDTH_BYTES, AudioSegment

logger = logging.getLogger(__name__)

MAX_DURATION_MS = 300_000
MAX_SEGMENT_MS = 30_000
MAX_TURN_MS = MAX_SEGMENT_MS
_FRAME_MS = 30
_CLIPPING_WARN_RATIO = 0.001
_LOW_LEVEL_DBFS = -35.0
_LOW_SNR_DB = 10.0
# Cổng im lặng của /v1/stt/turn: lượt im lặng khi Silero gắn cờ giọng ít hơn chừng này ms VÀ
# mức âm thấp hơn _SILENT_BELOW_DBFS (docs/evidence/pm-preprocess-2026-10-02.md). Chỉ dựa vào Silero thì sai: tiếng đường phố SNR 6 dB làm xác suất giọng
# của Silero không quá 0,31 (8 kHz) nên câu thật bị bỏ (bộ PM 02/10: 17/19 file ồn mạnh). Giọng
# nhỏ nhất của bộ PM (nói xa) ở −48,8 dBFS; tiếng phòng B-SIL-01 ở −66,8 dBFS.
_MIN_TURN_SPEECH_MS = 200
_SILENT_BELOW_DBFS = -55.0

VadFactory = Callable[[int], FrameClassifier]


class InvalidAudio(ValueError):
    pass


class AudioTooLong(ValueError):
    def __init__(self, duration_ms: int, limit_ms: int) -> None:
        super().__init__(f"{duration_ms} ms > {limit_ms} ms")
        self.limit_ms = limit_ms


@dataclass(frozen=True)
class SegmentResult:
    start_ms: int
    end_ms: int
    text: str
    confidence: Optional[float]


@dataclass(frozen=True)
class ComparisonResult:
    text: str
    confidence: Optional[float]
    asr_ms: float


@dataclass(frozen=True)
class SourceReport:
    format: str
    sample_rate: int
    channels: int
    duration_ms: int
    peak_dbfs: Optional[float]
    speech_rms_dbfs: Optional[float]
    clipping_ratio: float


@dataclass(frozen=True)
class Timings:
    decode_ms: float
    preprocess_ms: float
    vad_ms: float
    asr_ms: float
    total_ms: float


@dataclass(frozen=True)
class TurnTimings:
    decode_ms: float
    preprocess_ms: float
    asr_ms: float
    total_ms: float


@dataclass(frozen=True)
class OfflineTranscription:
    text: str
    confidence: Optional[float]
    segments: list[SegmentResult]
    raw: Optional[ComparisonResult]
    audio: SourceReport
    snr_db: Optional[float]
    speech_ms: int
    steps: list[str]
    gain_db: float
    telephone_band: bool
    timings: Timings
    real_time_factor: Optional[float]
    warnings: list[str]


@dataclass(frozen=True)
class TurnTranscription:
    text: str
    confidence: Optional[float]
    production: Optional[ComparisonResult]
    audio: SourceReport
    # Đúng audio đã đưa vào ASR (None khi cổng VAD chặn) — cho bộ đo nghe lại, không trả qua API
    model_audio: Optional[AudioSegment]
    steps: list[str]
    gain_db: float
    telephone_band: bool
    timings: TurnTimings
    real_time_factor: Optional[float]
    warnings: list[str]


@dataclass(frozen=True)
class _Prepared:
    original: AudioSegment
    source: SourceReport
    # Sau bước giả lập điện thoại (nếu có), chưa tiền xử lý — nguồn cho bản `raw`
    base: AudioSegment
    # Đã bỏ DC, ở tần số model, đã khuếch đại nếu cần
    pcm: bytes
    model_rate: int
    # Cổng im lặng chặn: không gọi ASR
    no_speech: bool
    steps: list[str]
    gain_db: float
    warnings: list[str]
    decode_ms: float
    preprocess_ms: float


def _ms_since(start_ns: int) -> float:
    return (perf_counter_ns() - start_ns) / 1_000_000


def _prepare(
    data: bytes,
    model_rate: int,
    *,
    telephone_band: bool,
    max_duration_ms: int,
    vad_factory: Optional[VadFactory] = None,
) -> _Prepared:
    started = perf_counter_ns()
    try:
        original, info = read_wav(data)
    except (ValueError, TypeError, EOFError, struct.error) as exc:
        raise InvalidAudio(str(exc)) from exc
    if not original.pcm:
        raise InvalidAudio("wav không có mẫu audio nào")
    if original.duration_ms > max_duration_ms:
        raise AudioTooLong(original.duration_ms, max_duration_ms)
    decode_ms = _ms_since(started)

    step = perf_counter_ns()
    level = measure_level(original.pcm, original.sample_rate)
    steps = ["DOWNMIX_MONO"] if info.channels > 1 else []
    base = original
    if telephone_band and base.sample_rate > NARROWBAND_RATE:
        base = to_sample_rate(base, NARROWBAND_RATE)
        steps.append("TELEPHONE_BAND")
    processed = to_sample_rate(
        AudioSegment(pcm=remove_dc(base.pcm), sample_rate=base.sample_rate), model_rate
    )
    steps.append("DC_REMOVAL")
    if base.sample_rate != model_rate:
        steps.append("RESAMPLE")
    pcm = processed.pcm
    level = measure_level(pcm, model_rate)
    no_speech = vad_factory is not None and is_silent_turn(
        detect_speech_frames(pcm, model_rate, vad_factory(model_rate), frame_ms=_FRAME_MS), level
    )
    gain_db = 0.0
    if no_speech:
        steps.append("VAD_NO_SPEECH")
    else:
        pcm, gain_db = normalize_gain(pcm, level)
    if gain_db:
        steps.append("GAIN_NORMALIZE")

    warnings = []
    if info.sample_rate <= NARROWBAND_RATE:
        warnings.append("NARROWBAND_SOURCE")
    if level.clipping_ratio > _CLIPPING_WARN_RATIO:
        warnings.append("CLIPPING")
    if level.speech_rms_dbfs is None or level.speech_rms_dbfs < _LOW_LEVEL_DBFS:
        warnings.append("LOW_LEVEL")

    return _Prepared(
        original=original,
        source=SourceReport(
            format=info.format,
            sample_rate=info.sample_rate,
            channels=info.channels,
            duration_ms=original.duration_ms,
            peak_dbfs=level.peak_dbfs,
            speech_rms_dbfs=level.speech_rms_dbfs,
            clipping_ratio=level.clipping_ratio,
        ),
        base=base,
        pcm=pcm,
        model_rate=model_rate,
        no_speech=no_speech,
        steps=steps,
        gain_db=gain_db,
        warnings=warnings,
        decode_ms=decode_ms,
        preprocess_ms=_ms_since(step),
    )


def is_silent_turn(flags: list[bool], level: LevelStats) -> bool:
    """Cổng im lặng: Silero gần như không gắn cờ giọng VÀ cả file nhỏ hơn _SILENT_BELOW_DBFS.

    Cần cả hai điều kiện: tiếng phòng (−67 dBFS) thì khuếch đại tĩnh kéo lên +20 dB rồi ASR bịa
    chữ; nhưng chỉ tin Silero thì câu thật trong tiếng đường phố cũng bị bỏ."""
    quiet = level.speech_rms_dbfs is None or level.speech_rms_dbfs < _SILENT_BELOW_DBFS
    return quiet and sum(flags) * _FRAME_MS < _MIN_TURN_SPEECH_MS


def _decode(
    recognizer: Recognizer, pcm: bytes, sample_rate: int, pieces: list[tuple[int, int]]
) -> list[SegmentResult]:
    results = []
    for start_ms, end_ms in pieces:
        begin = start_ms * sample_rate // 1000 * SAMPLE_WIDTH_BYTES
        end = end_ms * sample_rate // 1000 * SAMPLE_WIDTH_BYTES
        transcript = recognizer.transcribe(
            AudioSegment(pcm=pcm[begin:end], sample_rate=sample_rate)
        )
        results.append(SegmentResult(start_ms, end_ms, transcript.text, transcript.confidence))
    return results


def _join(segments: list[SegmentResult]) -> str:
    return " ".join(segment.text for segment in segments if segment.text)


def _weighted_confidence(parts: list[tuple[str, Optional[float]]]) -> Optional[float]:
    """Trung bình confidence theo số từ — đoạn dài đóng góp nhiều hơn đoạn một từ."""
    weighted = [(len(text.split()), conf) for text, conf in parts if text and conf is not None]
    words = sum(count for count, _ in weighted)
    if not words:
        return None
    return sum(count * conf for count, conf in weighted) / words


def _real_time_factor(asr_ms: float, duration_ms: int) -> Optional[float]:
    return asr_ms / duration_ms if duration_ms else None


def transcribe_turn(
    data: bytes,
    *,
    recognizer: Recognizer,
    telephone_band: bool = False,
    compare: bool = False,
    vad_factory: Optional[VadFactory] = None,
) -> TurnTranscription:
    """Một lượt nói: tiền xử lý nhẹ rồi decode nguyên clip một lần, không cắt đoạn.

    `vad_factory`: bật cổng im lặng (`is_silent_turn`) — lượt chỉ có tiếng phòng trả rỗng, không
    gọi ASR. `production` (khi `compare`) dùng đúng chuỗi hàm của /v1/calls turn: `load_from_url`
    giữ tần số gốc (`read_wav`), rồi `SpeechRecognizer.transcribe` resample một lần về tần số model.
    """
    started = perf_counter_ns()
    prepared = _prepare(
        data,
        recognizer.input_sample_rate,
        telephone_band=telephone_band,
        max_duration_ms=MAX_TURN_MS,
        vad_factory=vad_factory,
    )

    step = perf_counter_ns()
    model_audio = None
    text, confidence = "", None
    if not prepared.no_speech:
        model_audio = AudioSegment(pcm=prepared.pcm, sample_rate=prepared.model_rate)
        transcript = recognizer.transcribe(model_audio)
        text, confidence = transcript.text, transcript.confidence
    asr_ms = _ms_since(step)

    production = None
    if compare:
        step = perf_counter_ns()
        heard = recognizer.transcribe(prepared.original)
        production = ComparisonResult(heard.text, heard.confidence, _ms_since(step))

    duration_ms = prepared.source.duration_ms
    total_ms = _ms_since(started)
    logger.info(
        "stt_eval turn duration_ms=%d asr_ms=%.1f total_ms=%.1f", duration_ms, asr_ms, total_ms
    )
    return TurnTranscription(
        text=text,
        confidence=confidence if text else None,
        production=production,
        audio=prepared.source,
        model_audio=model_audio,
        steps=prepared.steps,
        gain_db=prepared.gain_db,
        telephone_band=telephone_band,
        timings=TurnTimings(prepared.decode_ms, prepared.preprocess_ms, asr_ms, total_ms),
        real_time_factor=_real_time_factor(asr_ms, duration_ms),
        warnings=prepared.warnings,
    )


def transcribe_offline(
    data: bytes,
    *,
    recognizer: Recognizer,
    vad_factory: VadFactory,
    telephone_band: bool = False,
    compare: bool = False,
) -> OfflineTranscription:
    started = perf_counter_ns()
    prepared = _prepare(
        data,
        recognizer.input_sample_rate,
        telephone_band=telephone_band,
        max_duration_ms=MAX_DURATION_MS,
    )
    pcm, model_rate = prepared.pcm, prepared.model_rate

    step = perf_counter_ns()
    flags = detect_speech_frames(pcm, model_rate, vad_factory(model_rate), frame_ms=_FRAME_MS)
    duration_ms = len(pcm) // SAMPLE_WIDTH_BYTES * 1000 // model_rate
    regions = speech_regions(flags, duration_ms, frame_ms=_FRAME_MS)
    snr_db = estimate_snr_db(pcm, model_rate, flags, regions, frame_ms=_FRAME_MS)
    regions = split_long_regions(regions, pcm, model_rate, max_ms=MAX_SEGMENT_MS)
    vad_ms = _ms_since(step)

    step = perf_counter_ns()
    segments = _decode(recognizer, pcm, model_rate, regions)
    asr_ms = _ms_since(step)

    raw = None
    if compare:
        step = perf_counter_ns()
        raw_input = to_sample_rate(prepared.base, model_rate)
        pieces = split_long_regions(
            [(0, raw_input.duration_ms)], raw_input.pcm, model_rate, max_ms=MAX_SEGMENT_MS
        )
        decoded = _decode(recognizer, raw_input.pcm, model_rate, pieces)
        raw = ComparisonResult(
            _join(decoded),
            _weighted_confidence([(part.text, part.confidence) for part in decoded]),
            _ms_since(step),
        )

    warnings = list(prepared.warnings)
    if snr_db is not None and snr_db < _LOW_SNR_DB:
        warnings.append("LOW_SNR")
    if not regions:
        warnings.append("NO_SPEECH_DETECTED")

    source_ms = prepared.source.duration_ms
    total_ms = _ms_since(started)
    # Không log transcript (PII) — chỉ số liệu
    logger.info(
        "stt_eval duration_ms=%d segments=%d asr_ms=%.1f total_ms=%.1f",
        source_ms,
        len(segments),
        asr_ms,
        total_ms,
    )
    return OfflineTranscription(
        text=_join(segments),
        confidence=_weighted_confidence([(s.text, s.confidence) for s in segments]),
        segments=segments,
        raw=raw,
        audio=prepared.source,
        snr_db=snr_db,
        speech_ms=sum(flags) * _FRAME_MS,
        steps=[*prepared.steps, "VAD_SEGMENT"],
        gain_db=prepared.gain_db,
        telephone_band=telephone_band,
        timings=Timings(prepared.decode_ms, prepared.preprocess_ms, vad_ms, asr_ms, total_ms),
        real_time_factor=_real_time_factor(asr_ms, source_ms),
        warnings=warnings,
    )
