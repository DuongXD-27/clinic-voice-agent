"""Tăng âm giọng người gọi quá nhỏ (LiveKit): giọng đủ to giữ nguyên, giọng nhỏ được tăng, nền nhiễu
không bị kéo lên quá ngưỡng Silero bắt đầu báo nhầm, hệ số chỉ đổi khi đã im lặng đủ lâu."""

import numpy as np
import pytest

from speech.audio.quiet_gain import QuietSpeechGain, frame_dbfs

_RATE = 16_000
_FRAME = 480  # 30 ms


def _frame(dbfs: float, seed: int = 0) -> bytes:
    """Frame nhiễu trắng có RMS đúng `dbfs`."""
    rng = np.random.default_rng(seed)
    samples = rng.normal(0.0, 1.0, _FRAME)
    samples *= 32768 * 10 ** (dbfs / 20) / np.sqrt(np.mean(samples**2))
    return np.clip(np.round(samples), -32768, 32767).astype(np.int16).tobytes()


def _feed(gain: QuietSpeechGain, dbfs: float, frames: int, *, speech: bool, bot: bool = False):
    out = b""
    for i in range(frames):
        out = gain.apply(_frame(dbfs, seed=i))
        gain.observe(speech, bot_speaking=bot)
    return out


def _call(speech_dbfs: float, floor_dbfs: float, seconds: float = 8.0) -> QuietSpeechGain:
    """Người gọi nói 1,2 s rồi nghỉ 1,5 s, lặp lại; nền nhiễu ở `floor_dbfs`."""
    gain = QuietSpeechGain(frame_ms=30)
    for _ in range(round(seconds / 2.7)):
        _feed(gain, speech_dbfs, 40, speech=True)
        _feed(gain, floor_dbfs, 50, speech=False)
    return gain


def test_normal_level_speech_is_passed_through_byte_for_byte() -> None:
    """Đa số cuộc gọi web đã qua AGC trình duyệt: thêm AGC server ở mức thường làm WER tệ đi."""
    gain = _call(speech_dbfs=-22.0, floor_dbfs=-70.0)
    frame = _frame(-22.0, seed=99)

    assert gain.gain_db == 0.0
    assert gain.apply(frame) is frame


def test_quiet_speech_in_a_quiet_room_is_raised_towards_the_target() -> None:
    gain = _call(speech_dbfs=-45.0, floor_dbfs=-75.0)

    assert gain.gain_db == pytest.approx(19.0, abs=0.5)  # -45 -> -26 dBFS
    assert frame_dbfs(gain.apply(_frame(-45.0, seed=5))) == pytest.approx(-26.0, abs=0.6)


def test_gain_never_lifts_the_noise_floor_above_where_silero_starts_misfiring() -> None:
    """Nền -58 dBFS: tăng tối đa 8 dB để nền <= -50 dBFS, dù giọng -45 dBFS muốn +19 dB."""
    gain = _call(speech_dbfs=-45.0, floor_dbfs=-58.0)

    assert gain.gain_db == pytest.approx(8.0, abs=0.5)


def test_bursty_noise_limits_the_gain_by_its_bursts_not_its_median() -> None:
    """Nhiễu văn phòng đến từng cụm: trung vị thấp nhưng đỉnh cụm làm Silero báo nhầm (11/10: giới hạn
    theo trung vị để lọt lượt giả "ĐÂY"). Nền -75 dBFS, cụm -60 dBFS chiếm 20% lúc im lặng: chỉ tăng
    10 dB để cụm <= -50 dBFS, không phải +19 dB theo trung vị."""
    gain = QuietSpeechGain(frame_ms=30)
    for _ in range(4):
        _feed(gain, -45.0, 40, speech=True)
        _feed(gain, -75.0, 40, speech=False)
        _feed(gain, -60.0, 10, speech=False)

    assert gain.gain_db == pytest.approx(10.0, abs=0.5)


def test_a_single_knock_between_utterances_does_not_drop_the_gain() -> None:
    """Tiếng gõ / va chạm máy ngắn Silero không gắn cờ: hệ số tụt thì câu sau nhỏ đi đúng chừng đó và
    Silero ("nhớ" mức âm) bỏ sót đầu câu."""
    gain = _call(speech_dbfs=-45.0, floor_dbfs=-75.0, seconds=30.0)
    boosted = gain.gain_db
    assert boosted > 15.0

    _feed(gain, -15.0, 3, speech=False)
    _feed(gain, -75.0, 50, speech=False)

    assert gain.gain_db >= boosted


def test_noisy_room_gets_no_gain_at_all() -> None:
    gain = _call(speech_dbfs=-40.0, floor_dbfs=-48.0)

    assert gain.gain_db == 0.0


def test_quieter_voices_after_the_caller_spoke_normally_get_no_gain() -> None:
    """Người gọi nói bình thường rồi im; TV / người khác nói nhỏ phía sau suốt 30 s (log 09/10:
    "THANH THỦY ĐÂY LÀ SÓNG TRUYỀN HÌNH TRỰC TIẾP…"). Tăng âm lúc này chỉ kéo TV thành lượt giả."""
    gain = QuietSpeechGain(frame_ms=30)
    for _ in range(3):
        _feed(gain, -22.0, 40, speech=True)
        _feed(gain, -75.0, 50, speech=False)
    for _ in range(11):
        _feed(gain, -45.0, 40, speech=True)
        _feed(gain, -75.0, 50, speech=False)

    assert gain.gain_db == 0.0


def test_a_short_click_is_not_taken_as_the_callers_voice_level() -> None:
    gain = QuietSpeechGain(frame_ms=30)
    _feed(gain, -75.0, 40, speech=False)
    _feed(gain, -20.0, 5, speech=True)  # 150 ms: tiếng gõ Silero gắn cờ
    _feed(gain, -75.0, 20, speech=False)

    assert gain.speech_dbfs() is None


def test_gain_changes_only_after_a_second_of_silence() -> None:
    """Silero "nhớ" mức âm: hệ số đổi qua một khoảng nghỉ ngắn giữa hai cụm từ làm nó bỏ sót cụm sau."""
    gain = QuietSpeechGain(frame_ms=30)
    _feed(gain, -75.0, 40, speech=False)
    _feed(gain, -45.0, 40, speech=True)
    _feed(gain, -75.0, 20, speech=False)  # nghỉ 0,6 s
    assert gain.gain_db == 0.0

    _feed(gain, -75.0, 20, speech=False)  # đã im 1,2 s
    assert gain.gain_db == pytest.approx(19.0, abs=0.5)


def test_gain_is_held_through_an_utterance_and_not_dropped_for_a_louder_one() -> None:
    """Silero "nhớ" mức âm: hệ số rơi giữa câu, hay câu sau nhỏ hơn câu trước ~10 dB, làm nó bỏ sót
    câu kế tiếp (11/10: rơi 14 dB -> câu sau mất 1,9 s đầu). Người gọi nói to hơn thì giữ hệ số, chỉ
    hạ vừa đủ để giọng sau khi tăng không quá -12 dBFS."""
    gain = _call(speech_dbfs=-45.0, floor_dbfs=-75.0)
    boosted = gain.gain_db
    assert boosted > 15.0

    _feed(gain, -30.0, 60, speech=True)  # người gọi nói to hơn (vẫn nhỏ)
    assert gain.gain_db == boosted  # giữ nguyên trong câu
    _feed(gain, -75.0, 40, speech=False)
    assert gain.gain_db == pytest.approx(18.0, abs=0.5)  # -30 dBFS -> -12 dBFS, không về 0

    _feed(gain, -18.0, 60, speech=True)
    _feed(gain, -75.0, 40, speech=False)
    assert gain.gain_db == pytest.approx(6.0, abs=0.5)  # -18 dBFS -> -12 dBFS


def test_frames_heard_while_the_bot_speaks_do_not_raise_the_gain() -> None:
    """Tiếng bot vọng lại (AEC còn sót) bị Silero gắn cờ không được coi là giọng người gọi nhỏ."""
    gain = QuietSpeechGain(frame_ms=30)
    _feed(gain, -75.0, 40, speech=False)
    _feed(gain, -48.0, 200, speech=True, bot=True)

    assert gain.speech_dbfs() is None
    assert gain.gain_db == 0.0


def test_echo_tail_right_after_the_bot_stops_is_not_the_callers_voice() -> None:
    """Tiếng bot vọng lại / dư âm phòng còn kéo dài sau lúc bot dứt lời (dump web thật: đoạn -51 dBFS
    lúc bot chào làm câu đầu của người gọi bị tăng 15-20 dB)."""
    gain = QuietSpeechGain(frame_ms=30)
    _feed(gain, -75.0, 40, speech=False)
    _feed(gain, -48.0, 100, speech=True, bot=True)
    _feed(gain, -48.0, 15, speech=True)  # 0,45 s sau khi bot dứt lời
    _feed(gain, -75.0, 40, speech=False)

    assert gain.speech_dbfs() is None
    assert gain.gain_db == 0.0


def test_gain_falls_when_the_room_gets_noisy_even_without_speech() -> None:
    """TV bật / tiếng vọng làm nền lên: hệ số phải giảm ngay, không chờ người gọi nói."""
    gain = _call(speech_dbfs=-45.0, floor_dbfs=-75.0)
    assert gain.gain_db > 15.0

    _feed(gain, -52.0, 333, speech=False)

    assert gain.gain_db < 2.5


def test_gain_starts_gently_just_below_the_threshold() -> None:
    """Không nhảy 0 -> +9 dB khi mức giọng vừa chạm -35 dBFS."""
    gain = _call(speech_dbfs=-36.0, floor_dbfs=-75.0)

    assert 0.0 < gain.gain_db < 3.0


def test_boosted_frame_never_clips() -> None:
    gain = _call(speech_dbfs=-45.0, floor_dbfs=-75.0)
    loud = np.zeros(_FRAME, dtype=np.int16)
    loud[100] = 20_000  # tiếng gõ to giữa giọng nhỏ

    boosted = np.frombuffer(gain.apply(loud.tobytes()), dtype=np.int16)

    assert int(np.abs(boosted).max()) <= 32768 * 10 ** (-1 / 20) + 1  # đỉnh <= -1 dBFS


async def test_pipeline_feeds_vad_and_asr_the_boosted_frames() -> None:
    """Mọi bước sau (bộ phân loại, VAD, ASR) thấy cùng frame đã tăng — cùng đối tượng frame, nên kết
    quả phân loại dùng chung vẫn tra được."""
    import asyncio

    from tests.speech.pipeline_factory import make_stt_pipeline

    from speech.asr.vad.async_stream import AsyncStreamingVAD
    from speech.asr.vad.energy import EnergyFrameClassifier
    from speech.asr.vad.shared import SharedSpeechDetector
    from speech.turn.controller import TurnController

    class _RecordingASR:
        name = "fake"
        input_sample_rate = 8000

        def __init__(self) -> None:
            self.levels: list[float] = []

        def transcribe(self, segment):
            raise NotImplementedError

        async def stream(self, frames, **_kwargs):
            async for item in frames:
                if isinstance(item, bytes):
                    self.levels.append(frame_dbfs(item))
            return
            yield  # async generator không phát event nào

    detector = SharedSpeechDetector(EnergyFrameClassifier(50.0), capacity=2000)
    asr = _RecordingASR()
    pipeline = make_stt_pipeline(
        asr=asr,
        vad=AsyncStreamingVAD(detector.view(), end_silence_ms=600, frame_ms=30),
        detector=detector,
        quiet_gain=QuietSpeechGain(frame_ms=30),
    )

    async def frames():
        for second in range(6):
            for i in range(40):  # nói 1,2 s ở -45 dBFS
                yield _frame(-45.0, seed=second * 100 + i)[: 240 * 2]
            for i in range(50):  # nghỉ 1,5 s gần như im lặng
                yield _frame(-80.0, seed=second * 100 + 50 + i)[: 240 * 2]
            await asyncio.sleep(0)

    async for _turn in pipeline.stream(frames(), turn_controller=TurnController()):
        pass

    early, late = asr.levels[:40], asr.levels[-90:-50]  # câu đầu, câu cuối
    assert max(early) < -40.0  # câu đầu: chưa biết mức giọng, giữ nguyên
    assert min(late) > -31.0  # các câu sau: đã tăng về gần -26 dBFS


async def test_snr_evidence_does_not_jump_when_the_gain_changes() -> None:
    """Review PR #110: nền nhiễu của bằng chứng SNR là trung vị ~3 s frame im lặng. Đo trên frame
    đã tăng thì hệ số nhảy +19 dB làm câu sau "rõ hơn nền" thêm ~18 dB (cùng một câu: 24 -> 42 dB,
    đo 12/10) — nhiễu/TV vượt các ngưỡng SNR của Validator và của ngắt lời."""
    import asyncio

    from tests.speech.pipeline_factory import make_stt_pipeline

    from speech.asr.vad.async_stream import AsyncStreamingVAD
    from speech.asr.vad.energy import EnergyFrameClassifier
    from speech.asr.vad.shared import SharedSpeechDetector
    from speech.turn.controller import TurnController
    from speech.turn.evidence import TurnEvidence

    class _SilentASR:
        name = "fake"
        input_sample_rate = 8000

        def transcribe(self, segment):
            raise NotImplementedError

        async def stream(self, frames, **_kwargs):
            async for _item in frames:
                pass
            return
            yield

    class _Recorded(TurnEvidence):
        snrs: list[float] = []

        def observe_frame(self, frame: bytes, **kwargs) -> None:
            super().observe_frame(frame, **kwargs)
            assert self.utterance_noise is not None
            self.snrs.append(self.utterance_noise.snr_db)

    detector = SharedSpeechDetector(EnergyFrameClassifier(50.0), capacity=2000)
    evidence = _Recorded(detector.view(), frame_ms=30)
    _Recorded.snrs = []
    pipeline = make_stt_pipeline(
        asr=_SilentASR(),
        vad=AsyncStreamingVAD(detector.view(), end_silence_ms=600, frame_ms=30),
        detector=detector,
        evidence=evidence,
        quiet_gain=QuietSpeechGain(frame_ms=30),
    )
    plan = [(-70.0, 70), (-45.0, 40), (-70.0, 50), (-45.0, 40)]  # nền, câu 1, nghỉ, câu 2 y hệt

    async def frames():
        seed = 0
        for dbfs, count in plan:
            for _ in range(count):
                seed += 1
                yield _frame(dbfs, seed)[: 240 * 2]
            await asyncio.sleep(0)

    async for _turn in pipeline.stream(frames(), turn_controller=TurnController()):
        pass

    first, second = _Recorded.snrs[70 + 40 - 1], _Recorded.snrs[-1]
    assert pipeline.quiet_gain is not None and pipeline.quiet_gain.gain_db > 15.0
    assert abs(second - first) < 2.0


def test_a_long_silence_does_not_creep_the_gain_up_for_a_normal_voice() -> None:
    """Review PR #110: mức giọng giữ lại giảm theo thời gian kể cả lúc im lặng; sau ~5 phút người
    gọi im (nghe bot, chờ máy) mức tụt dưới -35 dBFS, hệ số tăng lên trong lúc im, và giọng -20 dBFS
    khi người gọi nói lại bị cộng thêm vài dB — trái cam kết "giọng đủ to giữ nguyên từng byte"."""
    gain = QuietSpeechGain(frame_ms=30)
    _feed(gain, -75.0, 40, speech=False)
    _feed(gain, -20.0, 40, speech=True)
    _feed(gain, -75.0, round(6 * 60 / 0.03), speech=False)  # 6 phút im lặng

    frame = _frame(-20.0, seed=7)
    assert gain.gain_db == 0.0
    assert gain.apply(frame) is frame
