import asyncio
from typing import AsyncIterator, Iterable

import pytest

from inference.asr.config import ZipFormerConfig
from inference.asr.providers.zipformer import ZipFormerASR
from speech.asr.vad.streaming import FRAME_MS

_FRAME_BYTES = int(8000 * FRAME_MS / 1000) * 2  # PCM16 mono @ 8kHz, frame chuẩn 30ms
_LOUD = b"\x00\x10" * (_FRAME_BYTES // 2)
_SILENT = b"\x00\x00" * (_FRAME_BYTES // 2)


@pytest.fixture(autouse=True)
def _run_fake_decoder_inline(monkeypatch):
    async def inline(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", inline)


class _FakeStream:
    def __init__(self, text: str) -> None:
        self.result = type("Result", (), {"text": text})()

    def accept_waveform(self, sample_rate: int, samples: object) -> None:
        pass


class _GrowingFakeRecognizer:
    """Trả text dài dần theo số byte đã tích luỹ — giả lập câu hình thành dần."""

    def __init__(self) -> None:
        self.decode_calls = 0

    def create_stream(self) -> _FakeStream:
        return self._pending_stream

    def decode_stream(self, stream: _FakeStream) -> None:
        self.decode_calls += 1

    def _text_for(self, num_bytes: int) -> str:
        words = ["xin", "chào", "bác", "sĩ"]
        count = min(len(words), max(1, num_bytes // _FRAME_BYTES // 2))
        return " ".join(words[:count])


class _RecordingASR(ZipFormerASR):
    """Bọc ZipFormerASR để _decode_pcm dùng recognizer giả theo buffer hiện tại."""

    def __init__(self, growing: _GrowingFakeRecognizer) -> None:
        super().__init__(
            ZipFormerConfig(encoder_path="e", decoder_path="d", joiner_path="j", tokens_path="t"),
            recognizer=object(),
        )
        self._growing = growing

    def _decode_pcm(self, pcm: bytes) -> str:  # type: ignore[override]
        text = self._growing._text_for(len(pcm))
        self._growing.decode_calls += 1
        return text


async def _aiter(frames: Iterable[bytes]) -> AsyncIterator[bytes]:
    for frame in frames:
        yield frame


async def test_stream_emits_partial_then_final_on_silence() -> None:
    growing = _GrowingFakeRecognizer()
    asr = _RecordingASR(growing)
    # 4 frame nói (tăng dần độ dài buffer) rồi im lặng đủ lâu để đóng turn.
    frames = [_LOUD] * 4 + [_SILENT] * 21

    events = [
        event
        async for event in asr.stream(
            frames=_aiter(frames), end_silence_ms=600, min_emit_interval_ms=0, min_decode_ms=0
        )
    ]

    assert events, "phải có ít nhất 1 event"
    assert events[-1].is_final is True
    assert all(not e.is_final for e in events[:-1])
    # Partial phải là chuỗi tăng dần thông tin (không giảm số từ).
    partial_texts = [e.text for e in events if not e.is_final]
    assert partial_texts == sorted(partial_texts, key=len)


async def test_stream_dedups_identical_partial_text() -> None:
    growing = _GrowingFakeRecognizer()
    asr = _RecordingASR(growing)
    # Nhiều frame liên tiếp cho cùng 1 "độ dài nhóm" -> cùng text -> không được emit lặp lại.
    frames = [_LOUD] * 2 + [_SILENT] * 21

    events = [
        event
        async for event in asr.stream(
            frames=_aiter(frames), end_silence_ms=600, min_emit_interval_ms=0
        )
    ]

    partials = [e.text for e in events if not e.is_final]
    assert len(partials) == len(set(partials)), "không được emit partial trùng lặp liên tiếp"


async def test_stream_no_speech_emits_nothing() -> None:
    growing = _GrowingFakeRecognizer()
    asr = _RecordingASR(growing)
    frames = [_SILENT] * 25

    events = [event async for event in asr.stream(frames=_aiter(frames))]

    assert events == []


async def test_stream_final_flushed_at_end_without_trailing_silence() -> None:
    growing = _GrowingFakeRecognizer()
    asr = _RecordingASR(growing)
    frames = [_LOUD] * 4  # stream kết thúc giữa chừng, không có khoảng lặng đóng turn

    events = [
        event
        async for event in asr.stream(
            frames=_aiter(frames), min_emit_interval_ms=0, min_decode_ms=0
        )
    ]

    assert events, "phải flush final khi iterator kết thúc dù chưa có speech_end"
    assert events[-1].is_final is True


async def test_stream_skips_decode_when_buffer_shorter_than_min_decode_ms() -> None:
    """Audio siêu ngắn (tiếng "à", "ờm", hắng giọng — VAD đúng khi coi là speech) không
    được đưa vào decode — chống ZipFormer hallucinate ra cả cụm từ không tồn tại từ
    audio quá ngắn (bug thật: "KHÔNG ĐƯỢC CÁC BẠN" từ 1 tiếng "à" khi test qua LiveKit)."""
    growing = _GrowingFakeRecognizer()
    asr = _RecordingASR(growing)
    # 2 frame nói (~60ms, dưới min_decode_ms mặc định 400ms) rồi im lặng đóng turn.
    frames = [_LOUD] * 2 + [_SILENT] * 21

    events = [
        event
        async for event in asr.stream(
            frames=_aiter(frames), end_silence_ms=600, min_emit_interval_ms=0
        )
    ]

    assert events == [], "buffer ngắn hơn min_decode_ms không được emit turn nào (kể cả final)"


async def test_stream_decodes_when_buffer_reaches_min_decode_ms() -> None:
    growing = _GrowingFakeRecognizer()
    asr = _RecordingASR(growing)
    # min_decode_ms=60 -> 2 frame (60ms) đã đủ, phải decode và emit final khi silence tới.
    frames = [_LOUD] * 2 + [_SILENT] * 21

    events = [
        event
        async for event in asr.stream(
            frames=_aiter(frames), end_silence_ms=600, min_emit_interval_ms=0, min_decode_ms=60
        )
    ]

    assert events, "buffer đủ min_decode_ms phải được decode và emit"
    assert events[-1].is_final is True


async def test_stream_min_emit_interval_throttles_partial_decode_frequency() -> None:
    growing = _GrowingFakeRecognizer()
    asr = _RecordingASR(growing)
    frames = [_LOUD] * 8 + [_SILENT] * 21

    events_throttled = [
        event
        async for event in asr.stream(
            frames=_aiter(frames), end_silence_ms=600, min_emit_interval_ms=300
        )
    ]
    partials_throttled = [e for e in events_throttled if not e.is_final]

    growing2 = _GrowingFakeRecognizer()
    asr2 = _RecordingASR(growing2)
    events_fast = [
        event
        async for event in asr2.stream(
            frames=_aiter(frames), end_silence_ms=600, min_emit_interval_ms=0
        )
    ]
    partials_fast = [e for e in events_fast if not e.is_final]

    assert len(partials_throttled) <= len(partials_fast)


async def test_stream_forces_flush_when_speech_exceeds_max_turn_speech_ms() -> None:
    """Speech liên tục không có silence đủ dài để tự đóng turn -> buffer PHẢI tự flush
    ở max_turn_speech_ms thay vì tích luỹ vô hạn (memory leak đã xác nhận thực nghiệm,
    docs/reference/livekit-architecture.md §5.5: 60s audio giả lập -> 127s xử lý, 1551MB)."""
    growing = _GrowingFakeRecognizer()
    asr = _RecordingASR(growing)
    # 30ms/frame; max_turn_speech_ms=90 -> flush cưỡng bức sau 3 frame liên tục dù
    # KHÔNG có silence nào xen giữa (silent_ms luôn 0).
    frames = [_LOUD] * 10

    events = [
        event
        async for event in asr.stream(
            frames=_aiter(frames),
            end_silence_ms=600,
            min_emit_interval_ms=0,
            min_decode_ms=0,
            max_turn_speech_ms=90,
        )
    ]

    final_events = [e for e in events if e.is_final]
    assert len(final_events) >= 2, (
        "phải có nhiều hơn 1 final event — buffer bị flush cưỡng bức nhiều lần "
        "thay vì chỉ 1 final ở cuối stream"
    )


async def test_stream_buffer_size_bounded_with_continuous_speech() -> None:
    """Xác nhận trực tiếp buffer KHÔNG tăng vô hạn: theo dõi độ dài PCM lớn nhất từng
    được đưa vào decode trong lúc audio nói liên tục dài — phải bị chặn bởi
    max_turn_speech_ms, không tăng tuyến tính theo tổng số frame đã nhận.

    `_LOUD` là frame 8kHz (30ms) — `_decode_stream_pcm` tự resample 8k->16k nội bộ
    trước khi gọi `_decode_pcm` (khớp `ZipFormerASR.input_sample_rate=16_000`), nhân đôi
    kích thước byte quan sát được ở đây; công thức ngưỡng dưới đây tính cả hệ số đó,
    không liên quan tới việc buffer THẬT (trước resample) có bị chặn đúng hay không —
    điều đó đã được `test_stream_forces_flush_when_speech_exceeds_max_turn_speech_ms`
    xác nhận qua số lượng final event."""
    growing = _GrowingFakeRecognizer()
    max_pcm_len_seen = 0

    class _BoundedRecordingASR(_RecordingASR):
        def _decode_pcm(self, pcm: bytes) -> str:  # type: ignore[override]
            nonlocal max_pcm_len_seen
            max_pcm_len_seen = max(max_pcm_len_seen, len(pcm))
            return super()._decode_pcm(pcm)

    asr = _BoundedRecordingASR(growing)
    frames = [_LOUD] * 200  # audio nói liên tục dài, không có silence nào

    async for _ in asr.stream(
        frames=_aiter(frames),
        end_silence_ms=600,
        min_emit_interval_ms=0,
        min_decode_ms=0,
        max_turn_speech_ms=150,
    ):
        pass

    # max_turn_speech_ms=150ms @ frame 30ms -> buffer tối đa 5 frame trước khi forced_flush
    # trigger; resample 8k->16k nhân đôi byte quan sát ở _decode_pcm (hệ số x2).
    max_frames_per_segment = 150 // FRAME_MS
    assert max_pcm_len_seen <= _FRAME_BYTES * max_frames_per_segment * 2


@pytest.mark.parametrize("frame_ms", [10, 30])
async def test_stream_keeps_audio_before_internal_vad_onset(frame_ms: int) -> None:
    """VAD nội bộ nhận speech trễ; không được bỏ âm tiết đầu mà pipeline đã gửi."""
    frame_bytes = 8000 * frame_ms // 1000 * 2
    quiet_count = 600 // frame_ms
    speech_count = 120 // frame_ms
    tail_count = 60 // frame_ms
    frames = [
        bytes((marker, 0)) * (frame_bytes // 2)
        for marker in range(1, quiet_count + speech_count + tail_count + 1)
    ]

    class _ScriptedClassifier:
        index = 0

        def is_speech(self, _frame: bytes) -> bool:
            self.index += 1
            return quiet_count < self.index <= quiet_count + speech_count

    class _CapturingASR(_RecordingASR):
        def __init__(self) -> None:
            super().__init__(_GrowingFakeRecognizer())
            self.decoded: list[bytes] = []

        def _decode_stream_pcm(self, pcm: bytes, source_rate: int) -> str:
            assert source_rate == 8000
            self.decoded.append(pcm)
            return "TÔI CÓ ĐẾN ĐƯỢC"

    asr = _CapturingASR()
    events = [
        event
        async for event in asr.stream(
            _aiter(frames),
            silence_classifier=_ScriptedClassifier(),
            end_silence_ms=60,
            min_emit_interval_ms=10_000,
            min_decode_ms=60,
        )
    ]

    expected_start = quiet_count - 300 // frame_ms
    assert asr.decoded == [b"".join(frames[expected_start:])]
    assert len(events) == 1 and events[0].is_final

    # Pre-roll không được tính thành speech để lách ngưỡng chống hallucination.
    short_asr = _CapturingASR()
    short_events = [
        event
        async for event in short_asr.stream(
            _aiter(frames),
            silence_classifier=_ScriptedClassifier(),
            end_silence_ms=60,
            min_decode_ms=400,
        )
    ]
    assert short_events == []
    assert short_asr.decoded == []


if __name__ == "__main__":
    pytest.main([__file__])
