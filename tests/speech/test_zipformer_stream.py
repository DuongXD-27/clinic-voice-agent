import asyncio
from typing import AsyncIterator, Iterable

import pytest

from inference.asr.config import ZipFormerConfig
from inference.asr.providers.zipformer import ZipFormerASR, _Decoded
from speech.asr.vad.streaming import FRAME_MS
from speech.types import AsrSegmentEnd

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
    """Bọc ZipFormerASR để _decode_scored dùng recognizer giả theo buffer hiện tại."""

    def __init__(self, growing: _GrowingFakeRecognizer) -> None:
        super().__init__(
            ZipFormerConfig(encoder_path="e", decoder_path="d", joiner_path="j", tokens_path="t"),
            recognizer=object(),
        )
        self._growing = growing

    def _decode_scored(self, pcm: bytes) -> _Decoded:  # type: ignore[override]
        text = self._growing._text_for(len(pcm))
        self._growing.decode_calls += 1
        return _Decoded(text)


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

    `_LOUD` là frame 8kHz (30ms) — `_decode_stream_scored` tự resample 8k->16k nội bộ
    trước khi gọi `_decode_scored` (khớp `ZipFormerASR.input_sample_rate=16_000`), nhân đôi
    kích thước byte quan sát được ở đây; công thức ngưỡng dưới đây tính cả hệ số đó,
    không liên quan tới việc buffer THẬT (trước resample) có bị chặn đúng hay không —
    điều đó đã được `test_stream_forces_flush_when_speech_exceeds_max_turn_speech_ms`
    xác nhận qua số lượng final event."""
    growing = _GrowingFakeRecognizer()
    max_pcm_len_seen = 0

    class _BoundedRecordingASR(_RecordingASR):
        def _decode_scored(self, pcm: bytes) -> _Decoded:  # type: ignore[override]
            nonlocal max_pcm_len_seen
            max_pcm_len_seen = max(max_pcm_len_seen, len(pcm))
            return super()._decode_scored(pcm)

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
    # trigger; resample 8k->16k nhân đôi byte quan sát ở _decode_scored (hệ số x2).
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

        def _decode_stream_scored(self, pcm: bytes, source_rate: int) -> _Decoded:
            assert source_rate == 8000
            self.decoded.append(pcm)
            return _Decoded("TÔI CÓ ĐẾN ĐƯỢC")

    asr = _CapturingASR()
    events = [
        event
        async for event in asr.stream(
            _aiter(frames),
            silence_classifier=_ScriptedClassifier(),
            end_silence_ms=60,
            min_emit_interval_ms=10_000,
            min_decode_ms=60,
            pre_speech_ms=300,  # cơ chế, không phụ thuộc giá trị cấu hình
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


_UTTERANCE_A = b"\x01\x10" * (_FRAME_BYTES // 2)
_UTTERANCE_B = b"\x02\x10" * (_FRAME_BYTES // 2)


class _LabellingASR(_RecordingASR):
    """Decode ra nhãn câu có mặt trong buffer ("A", "B", "A B") — thấy được câu cũ có
    còn nằm lại trong buffer khi câu mới tới hay không."""

    def __init__(self) -> None:
        super().__init__(_GrowingFakeRecognizer())

    def _decode_stream_scored(self, pcm: bytes, source_rate: int) -> _Decoded:
        labels: list[str] = []
        for start in range(0, len(pcm), _FRAME_BYTES):
            label = {_UTTERANCE_A[:2]: "A", _UTTERANCE_B[:2]: "B"}.get(pcm[start : start + 2])
            if label and (not labels or labels[-1] != label):
                labels.append(label)
        return _Decoded(" ".join(labels))


async def _finals(asr: ZipFormerASR, frames: list, **options) -> list[str]:
    options = {"end_silence_ms": 600, "min_emit_interval_ms": 10_000, **options}
    return [e.text async for e in asr.stream(_aiter(frames), **options) if e.is_final]


async def test_discard_marker_drops_utterance_without_event() -> None:
    """Bot bắt đầu nói giữa câu: phần dở bị bỏ, không phát final, không ghép vào câu sau
    (bug thật: "ANH SINH ANH SINH NGÀY ...")."""
    frames = [_UTTERANCE_A] * 5 + [AsrSegmentEnd.DISCARD] + [_UTTERANCE_B] * 5

    assert await _finals(_LabellingASR(), frames, min_decode_ms=0) == ["B"]


async def test_transport_preroll_survives_the_smaller_asr_onset_buffer() -> None:
    from speech.asr.stream_context import StreamingFrame

    decoded = []

    class Capture(_RecordingASR):
        def _decode_stream_scored(self, pcm, source_rate):
            decoded.append(pcm)
            return _Decoded("không được")

    class Onset:
        def is_speech(self, pcm):
            return pcm == _LOUD

    prefix = [bytes((marker, 0)) * 240 for marker in range(1, 17)]
    # VAD only notices speech after the bot stops: retain replay plus onset delay.
    items = [StreamingFrame(pcm, 0, 0, is_preroll=True) for pcm in prefix]
    items += [_SILENT] * 8 + [_LOUD] * 14
    events = await _finals(Capture(_GrowingFakeRecognizer()), items, silence_classifier=Onset())

    assert events == ["không được"]
    assert decoded[-1].startswith(b"".join(prefix))


async def test_replayed_noise_cannot_satisfy_minimum_speech_duration() -> None:
    from speech.asr.stream_context import StreamingFrame

    asr = _RecordingASR(_GrowingFakeRecognizer())
    items = [StreamingFrame(_SILENT, 0, 0, is_preroll=True)] * 16 + [_LOUD] * 3

    assert await _finals(asr, items) == []
    assert asr._growing.decode_calls == 0


async def test_replayed_prefix_ages_out_after_long_silence() -> None:
    from speech.asr.stream_context import StreamingFrame

    items = [StreamingFrame(_UTTERANCE_A, 0, 0, is_preroll=True)] * 16

    class OnlyB:
        def is_speech(self, pcm):
            return pcm == _UTTERANCE_B

    items += [_SILENT] * 40 + [_UTTERANCE_B] * 14
    # Im lặng phải dài hơn pre-roll; ghim pre-roll để test không phụ thuộc cấu hình.
    finals = await _finals(_LabellingASR(), items, silence_classifier=OnlyB(), pre_speech_ms=300)
    assert finals == ["B"]


class _ScoredFakeRecognizer:
    """Recognizer giả trả text + ys_log_probs như sherpa-onnx OfflineRecognizer thật."""

    def __init__(self, text: str, log_probs: list[float]) -> None:
        self._result = type("Result", (), {"text": text, "ys_log_probs": log_probs})()

    def create_stream(self):
        stream = _FakeStream("")
        stream.result = self._result
        return stream

    def decode_stream(self, stream) -> None:
        pass


async def test_final_carries_confidence_from_token_log_probs() -> None:
    """Confidence = trung bình nhân xác suất token (exp của trung bình ys_log_probs); chỉ để
    ghi log/đo, core không đọc `asr_confidence`."""
    import math

    asr = ZipFormerASR(
        ZipFormerConfig(encoder_path="e", decoder_path="d", joiner_path="j", tokens_path="t"),
        recognizer=_ScoredFakeRecognizer(" VÂNG", [math.log(0.5), math.log(0.8)]),
    )
    frames = [_LOUD] * 5 + [_SILENT] * 21

    events = [
        e
        async for e in asr.stream(
            _aiter(frames), end_silence_ms=600, min_emit_interval_ms=10_000, min_decode_ms=0
        )
    ]

    assert [e.text for e in events] == ["VÂNG"]
    assert events[0].confidence == pytest.approx(math.sqrt(0.5 * 0.8))


async def test_empty_decode_has_no_confidence() -> None:
    asr = ZipFormerASR(
        ZipFormerConfig(encoder_path="e", decoder_path="d", joiner_path="j", tokens_path="t"),
        recognizer=_ScoredFakeRecognizer("", []),
    )

    assert asr._decode_scored(b"\x00\x10" * 160) == _Decoded("")


async def _count_decodes(partial_interval_ratio: float, speech_frames: int = 200) -> int:
    growing = _GrowingFakeRecognizer()
    asr = _RecordingASR(growing)
    asr._config = ZipFormerConfig(
        encoder_path="e",
        decoder_path="d",
        joiner_path="j",
        tokens_path="t",
        partial_interval_ratio=partial_interval_ratio,
    )
    frames = [_LOUD] * speech_frames + [_SILENT] * 21
    async for _ in asr.stream(
        _aiter(frames), end_silence_ms=600, min_emit_interval_ms=300, min_decode_ms=0
    ):
        pass
    return growing.decode_calls


async def test_partial_interval_ratio_spaces_out_decodes_for_long_utterance() -> None:
    """Mỗi partial decode lại toàn bộ buffer: giãn nhịp theo độ dài buffer thì câu dài tốn ít
    lần decode hơn; 0 giữ nhịp cố định 300 ms như cũ."""
    fixed = await _count_decodes(0.0)  # 6 s nói liên tục
    spaced = await _count_decodes(0.2)

    assert fixed == 20 + 1  # 6 s / 300 ms partial + 1 final
    assert spaced <= fixed * 0.6
    # Câu ngắn (1,2 s: 0,2 x buffer < 300 ms) giữ nguyên nhịp — partial cho barge-in không đổi.
    assert await _count_decodes(0.2, speech_frames=40) == await _count_decodes(0.0, 40)


if __name__ == "__main__":
    pytest.main([__file__])


async def test_stream_pre_speech_override_replaces_config_for_this_stream() -> None:
    """Profile điện thoại đặt pre-roll riêng cho từng cuộc gọi; ASR dùng chung không đổi config."""
    frame_bytes = 8000 * 30 // 1000 * 2
    frames = [bytes((marker, 0)) * (frame_bytes // 2) for marker in range(1, 31)]

    class _ScriptedClassifier:
        index = 0

        def is_speech(self, _frame: bytes) -> bool:
            self.index += 1
            return 20 < self.index <= 24

    class _CapturingASR(_RecordingASR):
        def __init__(self) -> None:
            super().__init__(_GrowingFakeRecognizer())
            self.decoded: list[bytes] = []

        def _decode_stream_scored(self, pcm: bytes, source_rate: int) -> _Decoded:
            self.decoded.append(pcm)
            return _Decoded("CÓ")

    asr = _CapturingASR()
    async for _ in asr.stream(
        _aiter(frames),
        silence_classifier=_ScriptedClassifier(),
        end_silence_ms=60,
        min_emit_interval_ms=10_000,
        min_decode_ms=60,
        pre_speech_ms=450,
    ):
        pass

    # 450 ms pre-roll (15 frame) trước frame nói đầu tiên; chốt sau 60 ms im lặng (2 frame).
    assert asr.decoded == [b"".join(frames[20 - 450 // 30 : 26])]
