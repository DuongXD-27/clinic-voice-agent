"""ZipFormer 68M self-host qua sherpa-onnx.

Model `csukuangfj/sherpa-onnx-zipformer-vi-int8-2025-04-20` đã kiểm chứng (xem
temp/plan_mvp_zipformer.md, docs/reference/phone-leg-architecture.md §3.1) là bản
EXPORT OFFLINE (batch) — thiếu metadata streaming (`encoder_dims`) nên chỉ nạp được
qua `OfflineRecognizer`, không phải `OnlineRecognizer`. Đã tra lại model zoo chính
thức của sherpa-onnx (2026-09): cả 3 model Zipformer tiếng Việt hiện có (kể cả bản
mới nhất `sherpa-onnx-zipformer-vi-30M-int8-2026-02-09`) đều là offline/batch —
không tồn tại checkpoint online/streaming thật cho tiếng Việt. Vì vậy `transcribe()`
nhận nguyên một đoạn audio đã cắt sẵn (bởi VAD), không có partial transcript tăng dần.

`stream()` giả lập streaming bằng chiến lược "chunked-offline": tích luỹ PCM vào
buffer, decode lại toàn bộ buffer bằng `OfflineRecognizer` sau mỗi chunk mới để emit
partial, và emit final khi phát hiện khoảng lặng đủ dài (giống endpoint) trong buffer.
Tốn compute hơn incremental decode thật, nhưng RTF ~0.03 của model này
(docs/reference/phone-leg-architecture.md §3.1) khiến decode lại liên tục vẫn rẻ hơn
nhiều lần thời gian thực.

`decode_stream()` của sherpa-onnx là lời gọi CPU-bound đồng bộ (blocking) — trong
`stream()` PHẢI chạy qua `asyncio.to_thread()`, không gọi trực tiếp trên event loop.
Từng có bug thật: gọi trực tiếp làm chặn event loop LiveKit worker ~1.2s mỗi lần decode
(quan sát qua log "event loop blocked"), trễ toàn bộ audio publish/subscribe của MỌI
call đang chạy chung worker process, không chỉ call đang decode.

`stream()` KHÔNG được gọi decode trên buffer quá ngắn (< `config.min_decode_ms`, mặc
định 400ms). Bug thật đã gặp: audio rất ngắn (tiếng "à", "ờm", hắng giọng — VAD đúng
khi coi đó là speech, không phải noise) khiến ZipFormer HALLUCINATE — tự sinh ra cả
cụm từ không tồn tại ("KHÔNG ĐƯỢC CÁC BẠN") thay vì trả rỗng, vì greedy_search
transducer "đói" tín hiệu khi audio quá ngắn để cung cấp đủ context. Đây khác với việc
VAD nhận nhầm noise thành speech (đã xử lý ở TurnController.min_speech_ms) — ở đây VAD
ĐÚNG, nhưng bản thân ASR không tin cậy trên input siêu ngắn.

`stream()` (và `transcribe()`) gắn confidence = trung bình nhân xác suất các token của lần decode
(exp của trung bình `ys_log_probs`, model offline có sẵn, không tốn thêm compute). Đo 28/09:
"hủy lịch" nghe thành "THÙY LINH" vẫn có xác suất token 0,79/0,98/0,57 — confidence KHÔNG bắt
được nghe nhầm; chỉ có thể giúp nhận ra ảo giác sinh từ nhiễu (xem eval/noise-bench). Hiện chỉ
ghi log/đo, không có nhánh nào của pipeline đọc trường này.

`stream()` nằm ngoài Protocol `ASRProvider` (chỉ ZipFormer hỗ trợ, không phải
gemini/phowhisper) — gọi qua `ASRGateway.provider` (escape hatch), không qua
`ASRGateway.transcribe()`. `frames` nhận PCM 8 kHz (phone) hoặc 16 kHz (web) cùng
`audio_sample_rate` tường minh — khác `transcribe()` vốn luôn nhận PCM đã ở sample
rate của model. Web 16 kHz được decode thẳng; phone 8 kHz được resample một lần tại
boundary của provider.
"""

import asyncio
import logging
import math
from collections import deque
from typing import Any, AsyncIterator, Callable, NamedTuple, Optional

from inference.asr.base import ASRResult
from inference.asr.config import ZipFormerConfig
from speech.asr.vad.base import FrameClassifier
from speech.asr.vad.silero_probe import VOICE_PROBABILITY
from speech.audio.codec import resample
from speech.diagnostics import (
    ASR_EMPTY_DECODE,
    ASR_SKIP_MIN_DECODE,
    ASR_VOICE_LOOKBACK,
    report_asr_event,
)
from speech.types import NARROWBAND_RATE, AsrSegmentEnd, TranscriptEvent

_PRE_SPEECH_PREROLL_MS = 300
# Lùi theo giọng (`voice_lookback_ms`): chỗ xác suất tụt ngắn hơn chừng này vẫn coi là liền câu
# (giữa hai âm tiết); thêm chừng này audio trước frame có giọng đầu tiên cho phụ âm đầu.
_VOICE_GAP_MS = 60
_VOICE_MARGIN_MS = 90

logger = logging.getLogger(__name__)


class _Decoded(NamedTuple):
    text: str
    # exp(trung bình log-prob token) và xác suất token thấp nhất; None khi không có chữ.
    confidence: Optional[float] = None
    min_token_prob: Optional[float] = None


class _PreSpeech:
    """Audio ngay trước khi bộ phân loại báo có giọng — đưa vào đầu buffer decode.

    Mặc định giữ đúng `_PRE_SPEECH_PREROLL_MS` cuối. Với `lookback_ms` > 0 và xác suất Silero
    thô từng frame: nếu giọng liền mạch đã bắt đầu sớm hơn cửa sổ đó thì lùi thêm qua các frame
    có giọng, tối đa `lookback_ms`, cộng `_VOICE_MARGIN_MS` cho phụ âm đầu. sherpa-onnx cần
    250 ms giọng liên tục mới báo speech và một chỗ tụt 30 ms làm nó đếm lại: cuộc gọi 01/10 báo
    trễ 0,6 s, chữ "được" của câu "được em nhé" không tới ASR. Không lùi qua im lặng hay tiếng
    động: lấy cố định 600 ms từng làm model bịa chữ từ chính phần đó.
    """

    def __init__(
        self,
        sample_rate: int,
        lookback_ms: int,
        voice_probability: Optional[Callable[[bytes], Optional[float]]],
    ) -> None:
        self._bytes_per_ms = sample_rate * 2 / 1000
        self._base_bytes = sample_rate * _PRE_SPEECH_PREROLL_MS // 1000 * 2
        self._voice_probability = voice_probability if lookback_ms > 0 else None
        self._max_bytes = self._base_bytes + (
            sample_rate * lookback_ms // 1000 * 2 if self._voice_probability else 0
        )
        self._frames: deque[tuple[bytes, Optional[float]]] = deque()
        self._size = 0

    def add(self, frame: bytes) -> None:
        probability = self._voice_probability(frame) if self._voice_probability else None
        self._frames.append((frame, probability))
        self._size += len(frame)
        while self._frames and self._size - len(self._frames[0][0]) >= self._max_bytes:
            self._size -= len(self._frames.popleft()[0])

    def take(self) -> tuple[bytes, float]:
        """Audio đưa vào ASR và số ms lùi thêm ngoài cửa sổ mặc định; xoá bộ đệm."""
        frames = list(self._frames)
        self.clear()
        start = self._voiced_start(frames) if self._voice_probability else None
        if start is None:
            return b"".join(frame for frame, _ in frames)[-self._base_bytes :], 0.0
        audio = b"".join(frame for frame, _ in frames[start:])
        return audio, max(0, len(audio) - self._base_bytes) / self._bytes_per_ms

    def clear(self) -> None:
        self._frames.clear()
        self._size = 0

    def _voiced_start(self, frames: list[tuple[bytes, Optional[float]]]) -> Optional[int]:
        """Frame đầu tiên cần lấy nếu giọng liền mạch vượt ra trước cửa sổ mặc định, ngược lại
        None (giữ đúng hành vi mặc định)."""
        window_start, covered = len(frames), 0
        while window_start > 0 and covered < self._base_bytes:
            window_start -= 1
            covered += len(frames[window_start][0])
        start: Optional[int] = None
        gap_ms = 0.0
        for index in range(len(frames) - 1, -1, -1):
            frame, probability = frames[index]
            if probability is not None and probability >= VOICE_PROBABILITY:
                start, gap_ms = index, 0.0
            else:
                gap_ms += len(frame) / self._bytes_per_ms
                if gap_ms > _VOICE_GAP_MS:
                    break
        if start is None or start >= window_start:
            return None
        margin_ms = 0.0
        while start > 0 and margin_ms < _VOICE_MARGIN_MS:
            start -= 1
            margin_ms += len(frames[start][0]) / self._bytes_per_ms
        return start


class ZipFormerASR:
    input_sample_rate = 16_000

    def __init__(self, config: ZipFormerConfig, *, recognizer: Any = None) -> None:
        self._config = config
        self._recognizer = recognizer

    @property
    def model(self) -> str:
        return self._config.model

    def _get_recognizer(self):
        if self._recognizer is None:
            import sherpa_onnx  # pip install -e ".[speech-zipformer]"

            self._recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
                tokens=self._config.tokens_path,
                encoder=self._config.encoder_path,
                decoder=self._config.decoder_path,
                joiner=self._config.joiner_path,
                num_threads=self._config.num_threads,
                sample_rate=self.input_sample_rate,
                feature_dim=80,
                decoding_method="greedy_search",
                provider="cpu",
            )
        return self._recognizer

    def transcribe(self, pcm: bytes) -> ASRResult:
        decoded = self._decode_scored(pcm)
        return ASRResult(text=decoded.text, confidence=decoded.confidence)

    async def stream(
        self,
        frames: AsyncIterator[bytes | AsrSegmentEnd],
        *,
        audio_sample_rate: int = NARROWBAND_RATE,
        silence_classifier: FrameClassifier | None = None,
        end_silence_ms: int = 600,
        min_emit_interval_ms: int = 300,
        min_decode_ms: int | None = None,
        max_turn_speech_ms: int | None = None,
        voice_probability: Callable[[bytes], Optional[float]] | None = None,
        voice_lookback_ms: int = 0,
    ) -> AsyncIterator[TranscriptEvent]:
        """Giả lập streaming bằng chunked-offline decode (xem docstring module).

        `frames` là PCM ở `audio_sample_rate` liên tục suốt cuộc gọi — không phải
        một lượt đơn lẻ; ranh giới utterance (final) do chính hàm này tự phát hiện
        qua khoảng lặng, giống StreamingVAD, để không phụ thuộc caller gửi tín hiệu
        "hết câu" riêng. Dùng `silence_classifier` riêng (mặc định năng lượng RMS
        nhẹ) thay vì tái dùng VAD của pipeline — ASR tự chủ việc endpoint hoá của nó,
        VAD ở tầng trên (Turn Controller) là tín hiệu độc lập, không phải gatekeeper
        duy nhất.

        `min_decode_ms`: buffer ngắn hơn ngưỡng này KHÔNG được đưa vào decode — chống
        hallucination trên audio siêu ngắn (xem docstring module). Buffer vẫn tích luỹ
        bình thường, chỉ hoãn gọi model tới khi đủ dài hoặc hết speech (final luôn được
        thử decode dù ngắn hơn ngưỡng, để không mất hẳn câu trả lời 1 âm tiết hợp lệ như
        "có"/"không" — nhưng kết quả rỗng từ audio quá ngắn vẫn bị lọc như bình thường).
        `None` (mặc định) dùng `config.min_decode_ms`.

        `max_turn_speech_ms`: buộc flush buffer (giống speech_end xảy ra) khi `speech_ms`
        vượt ngưỡng này, dù chưa đủ `end_silence_ms` — chống memory leak khi audio speech
        liên tục không bao giờ có khoảng lặng đủ dài (docs/reference/
        livekit-architecture.md §5.5). `None` (mặc định) dùng `config.max_turn_speech_ms`.

        `voice_probability` + `voice_lookback_ms` (> 0): pre-speech lùi theo giọng (xem
        `_PreSpeech`). `voice_probability(frame)` trả xác suất Silero thô đã tính cho frame đó.
        Thiếu một trong hai thì giữ cửa sổ cố định `_PRE_SPEECH_PREROLL_MS`.

        `AsrSegmentEnd` trong `frames`: pipeline ngừng đưa audio (xem docstring enum).
        FINALIZE chốt buffer như khi đủ `end_silence_ms`; DISCARD bỏ buffer không phát
        event. Cả hai xoá luôn pre-speech — audio trước và sau chỗ ngắt không liền nhau.
        """
        if min_decode_ms is None:
            min_decode_ms = self._config.min_decode_ms
        if max_turn_speech_ms is None:
            max_turn_speech_ms = self._config.max_turn_speech_ms
        if silence_classifier is None:
            from speech.asr.vad.energy import EnergyFrameClassifier

            silence_classifier = EnergyFrameClassifier()

        if audio_sample_rate not in (8_000, 16_000):
            raise ValueError(f"ZipFormer stream không hỗ trợ sample rate {audio_sample_rate}")

        buffer = bytearray()
        pre_speech = _PreSpeech(audio_sample_rate, voice_lookback_ms, voice_probability)
        in_speech = False
        last_emitted_text = ""
        silent_ms = 0.0
        speech_ms = 0.0  # chỉ đếm frame is_speech — KHÔNG tính đuôi silence chờ
        # đóng turn, nếu không min_decode_ms bị "lách" bởi silent_frames tích luỹ đủ dài
        # trong buffer dù phần speech thật rất ngắn (bug đã gặp: audio ngắn "à"/"ờm" vẫn
        # decode được vì buffer đã có sẵn 600ms đuôi silence).
        audio_ms_since_emit = 0.0

        async for frame in frames:
            if isinstance(frame, AsrSegmentEnd):
                if frame is AsrSegmentEnd.FINALIZE and buffer and speech_ms >= min_decode_ms:
                    decoded = await asyncio.to_thread(
                        self._decode_stream_scored, bytes(buffer), audio_sample_rate
                    )
                    if decoded.text:
                        yield _final_event(decoded)
                    else:
                        report_asr_event(ASR_EMPTY_DECODE)
                elif frame is AsrSegmentEnd.FINALIZE and buffer:
                    report_asr_event(ASR_SKIP_MIN_DECODE)
                buffer.clear()
                pre_speech.clear()
                in_speech = False
                last_emitted_text = ""
                silent_ms = 0.0
                audio_ms_since_emit = 0.0
                speech_ms = 0.0
                continue
            frame_ms = len(frame) / 2 / audio_sample_rate * 1000
            if frame_ms <= 0:
                continue
            is_speech = silence_classifier.is_speech(frame)
            if not in_speech and not is_speech:
                # VAD nội bộ có thể nhận ra giọng nói muộn hơn âm tiết đầu. Giữ audio trước
                # speech_start (_PreSpeech) để không vô hiệu hóa pre-roll của pipeline.
                # Chỉ đưa vào buffer decode khi VAD xác nhận speech; silence/noise đơn lẻ
                # vẫn không thể tạo transcript hoặc vượt ngưỡng min_decode_ms.
                pre_speech.add(frame)
                continue

            if not in_speech:
                onset, lookback_ms = pre_speech.take()
                buffer.extend(onset)
                if lookback_ms:
                    report_asr_event(ASR_VOICE_LOOKBACK, lookback_ms)
            in_speech = True
            buffer.extend(frame)
            audio_ms_since_emit += frame_ms
            if is_speech:
                speech_ms += frame_ms
                silent_ms = 0.0
            else:
                silent_ms += frame_ms
            has_min_speech = speech_ms >= min_decode_ms
            # Mỗi partial decode lại TOÀN BỘ buffer: câu càng dài càng tốn; giãn nhịp theo độ
            # dài buffer nếu cấu hình (partial_interval_ratio), câu ngắn không đổi.
            buffer_ms = len(buffer) / 2 / audio_sample_rate * 1000
            emit_interval_ms = max(
                min_emit_interval_ms, self._config.partial_interval_ratio * buffer_ms
            )

            if is_speech and audio_ms_since_emit >= emit_interval_ms and has_min_speech:
                decoded = await asyncio.to_thread(
                    self._decode_stream_scored, bytes(buffer), audio_sample_rate
                )
                audio_ms_since_emit = 0.0
                if decoded.text and decoded.text != last_emitted_text:
                    last_emitted_text = decoded.text
                    yield TranscriptEvent(
                        text=decoded.text, is_final=False, confidence=decoded.confidence
                    )

            forced_flush = speech_ms >= max_turn_speech_ms
            if silent_ms >= end_silence_ms or forced_flush:
                if has_min_speech:
                    decoded = await asyncio.to_thread(
                        self._decode_stream_scored, bytes(buffer), audio_sample_rate
                    )
                    if decoded.text:
                        yield _final_event(decoded)
                    else:
                        report_asr_event(ASR_EMPTY_DECODE)
                else:
                    report_asr_event(ASR_SKIP_MIN_DECODE)
                # speech thật ngắn hơn min_decode_ms: coi là backchannel/tiếng động, bỏ
                # qua hoàn toàn — không decode, không emit gì (kể cả rỗng). forced_flush
                # (audio nói liên tục quá lâu) luôn có has_min_speech=True nên nhánh này
                # không áp dụng cho nó.
                buffer.clear()
                in_speech = forced_flush  # forced_flush: vẫn đang nói, giữ in_speech=True
                # để vòng lặp tiếp tục tích luỹ buffer mới ngay, không chờ frame is_speech
                # kế tiếp mới bật lại in_speech (silent_ms/speech_ms đã reset dưới đây).
                last_emitted_text = ""
                silent_ms = 0.0
                audio_ms_since_emit = 0.0
                speech_ms = 0.0

        if in_speech and buffer and speech_ms >= min_decode_ms:
            decoded = await asyncio.to_thread(
                self._decode_stream_scored, bytes(buffer), audio_sample_rate
            )
            if decoded.text:
                yield _final_event(decoded)

    def _decode_stream_scored(self, pcm: bytes, source_rate: int) -> _Decoded:
        """Decode PCM streaming ở 8/16 kHz; chỉ resample khi nguồn khác rate model."""
        if source_rate != self.input_sample_rate:
            pcm = resample(pcm, source_rate, self.input_sample_rate)
        return self._decode_scored(pcm)

    def _decode_stream_pcm(self, pcm: bytes, source_rate: int) -> str:
        return self._decode_stream_scored(pcm, source_rate).text

    def _decode_pcm_8k(self, pcm: bytes) -> str:
        """Compatibility helper cho test/caller cũ."""
        return self._decode_stream_pcm(pcm, NARROWBAND_RATE)

    def _decode_scored(self, pcm: bytes) -> _Decoded:
        """`pcm` đã ở `self.input_sample_rate` — decode thẳng, không resample lại."""
        import numpy as np

        if not pcm:
            return _Decoded("")
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        recognizer = self._get_recognizer()
        stream = recognizer.create_stream()
        stream.accept_waveform(self.input_sample_rate, samples)
        recognizer.decode_stream(stream)
        result = stream.result
        text = result.text.strip()
        log_probs = list(getattr(result, "ys_log_probs", None) or [])
        if not text or not log_probs:
            return _Decoded(text)
        return _Decoded(
            text,
            confidence=math.exp(sum(log_probs) / len(log_probs)),
            min_token_prob=math.exp(min(log_probs)),
        )


def _final_event(decoded: _Decoded) -> TranscriptEvent:
    if decoded.confidence is not None:
        # Không log text (PII); chỉ số để đối chiếu với turn qua thời điểm log.
        logger.debug(
            "zipformer final confidence=%.3f min_token_prob=%.3f",
            decoded.confidence,
            decoded.min_token_prob,
        )
    return TranscriptEvent(text=decoded.text, is_final=True, confidence=decoded.confidence)
