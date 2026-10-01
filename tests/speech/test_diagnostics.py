"""Chẩn đoán lượt nói (speech/diagnostics.py): mỗi đoạn giọng đúng một kết cục, đúng cổng.

Chỉ quan sát — các test này kiểm tra lý do được ghi; hành vi của TurnController không đổi đã
được khoá bởi test_controller.py và đối chiếu noise-bench (0 trial khác)."""

import asyncio

import numpy as np

from speech import diagnostics as diag
from speech.asr.vad.base import VadEvent
from speech.audio.ingress import IngressMonitor
from speech.audio.noise_tracker import NoiseEvidence
from speech.turn.controller import TurnController
from speech.turn.interruption import InterruptionController
from speech.turn.validator import TurnValidator
from speech.types import TranscriptEvent


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _controller(clock: _Clock, **kwargs) -> tuple[TurnController, diag.SpeechDiagnostics]:
    diagnostics = diag.SpeechDiagnostics(clock=clock)
    kwargs.setdefault("min_speech_ms", 0)
    controller = TurnController(clock=clock, diagnostics=diagnostics, **kwargs)
    return controller, diagnostics


def _reasons(diagnostics: diag.SpeechDiagnostics) -> list[tuple[str, str]]:
    return [(r.decision, r.reason) for r in diagnostics.utterances]


async def test_emitted_turn_records_one_outcome_with_id_on_the_turn() -> None:
    clock = _Clock()
    controller, diagnostics = _controller(clock)
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="tôi muốn đổi lịch", is_final=True))

    turn = await asyncio.wait_for(controller.get_turn(), 1)

    assert _reasons(diagnostics) == [(diag.EMITTED, diag.REASON_EMITTED)]
    assert turn.utterance_id == diagnostics.utterances[0].utterance_id
    assert diagnostics.utterances[0].words == 4


async def test_filler_is_recorded_as_not_meaningful() -> None:
    clock = _Clock()
    controller, diagnostics = _controller(clock)
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="ừ", is_final=True))

    assert _reasons(diagnostics) == [(diag.DROPPED, diag.REASON_NOT_MEANINGFUL)]


async def test_validator_drop_records_its_reason() -> None:
    clock = _Clock()
    controller, diagnostics = _controller(clock, validator=TurnValidator(min_snr_db=3.0))
    await controller.on_vad_event(VadEvent("speech_start"))
    controller.on_evidence_updated(noise_evidence=NoiseEvidence(rms=1, noise_floor=1, snr_db=0.5))
    await controller.on_transcript_event(TranscriptEvent(text="có", is_final=True))

    assert _reasons(diagnostics) == [(diag.DROPPED, "low_snr_short")]
    assert diagnostics.utterances[0].snr_db == 0.5


async def test_short_speech_and_guard_are_told_apart() -> None:
    clock = _Clock()
    controller, diagnostics = _controller(
        clock, min_speech_ms=250, post_bot_guard_ms=500, max_wait_after_vad_end_ms=0
    )

    # Ngắn hơn min_speech_ms: lỗi do độ dài.
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="có", is_final=False))
    clock.now += 0.1
    await controller.on_vad_event(VadEvent("speech_end"))
    await asyncio.sleep(0.01)

    # Đủ 250 ms nhưng bắt đầu ngay sau câu bot: chính guard chặn.
    controller.on_bot_speaking_changed(True)
    controller.on_bot_speaking_changed(False)
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_transcript_event(TranscriptEvent(text="có", is_final=False))
    clock.now += 0.3
    await controller.on_vad_event(VadEvent("speech_end"))
    await asyncio.sleep(0.01)

    assert _reasons(diagnostics) == [
        (diag.DROPPED, diag.REASON_MIN_SPEECH),
        (diag.DROPPED, diag.REASON_POST_BOT_GUARD),
    ]
    assert diagnostics.utterances[1].guard_extra_ms == 500.0


async def test_candidate_during_bot_speech_is_recorded_when_discarded() -> None:
    clock = _Clock()
    controller, diagnostics = _controller(clock)
    controller.on_bot_speaking_changed(True)
    await controller.on_vad_event(VadEvent("speech_start"))
    controller.on_bot_speaking_changed(False)

    assert _reasons(diagnostics) == [(diag.DROPPED, diag.REASON_DURING_BOT_SPEECH)]
    assert diagnostics.utterances[0].during_bot_speech is True


async def test_asr_skip_turns_empty_candidate_into_min_decode() -> None:
    clock = _Clock()
    controller, diagnostics = _controller(clock, max_wait_after_vad_end_ms=0)
    await controller.on_vad_event(VadEvent("speech_start"))
    diagnostics.on_asr_event(diag.ASR_SKIP_MIN_DECODE)
    await controller.on_vad_event(VadEvent("speech_end"))
    await asyncio.sleep(0.01)

    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_vad_event(VadEvent("speech_end"))
    await asyncio.sleep(0.01)

    assert _reasons(diagnostics) == [
        (diag.DROPPED, diag.REASON_MIN_DECODE),
        (diag.DROPPED, diag.REASON_NO_TEXT),
    ]


async def test_new_speech_start_supersedes_open_candidate_once() -> None:
    clock = _Clock()
    controller, diagnostics = _controller(clock)
    await controller.on_vad_event(VadEvent("speech_start"))
    await controller.on_vad_event(VadEvent("speech_start"))
    diagnostics.close()

    assert _reasons(diagnostics) == [
        (diag.DROPPED, diag.REASON_SUPERSEDED),
        (diag.DROPPED, diag.REASON_CALL_ENDED),
    ]


def test_finished_twice_keeps_first_outcome() -> None:
    diagnostics = diag.SpeechDiagnostics(clock=_Clock())
    utterance = diagnostics.utterance_started()
    diagnostics.utterance_finished(
        utterance, decision=diag.EMITTED, stage=diag.STAGE_TURN, reason=diag.REASON_EMITTED
    )
    again = diagnostics.utterance_finished(
        utterance, decision=diag.DROPPED, stage=diag.STAGE_TURN, reason=diag.REASON_SUPERSEDED
    )

    assert again is None
    assert _reasons(diagnostics) == [(diag.EMITTED, diag.REASON_EMITTED)]


def test_frames_feed_speech_time_probability_and_endpoint() -> None:
    clock = _Clock()

    class _Probe:
        def probability(self, frame: bytes) -> float:
            return 0.8

    diagnostics = diag.SpeechDiagnostics(clock=clock, probe=_Probe())
    diagnostics.observe_frame(b"\x00\x00", is_speech=False, frame_ms=30)
    utterance = diagnostics.utterance_started()
    for _ in range(3):
        clock.now += 0.03
        diagnostics.observe_frame(b"\x00\x00", is_speech=True, frame_ms=30)
    clock.now += 0.6
    record = diagnostics.utterance_finished(
        utterance, decision=diag.EMITTED, stage=diag.STAGE_TURN, reason=diag.REASON_EMITTED
    )

    assert record.speech_ms == 90.0
    assert record.vad_prob_mean == 0.8
    assert round(record.endpoint_ms) == 600


def test_voice_endpoint_includes_detector_hangover_and_ignores_next_onset() -> None:
    """Detector còn báo "đang nói" thêm một lúc sau khi hết giọng (hangover); probe thì không.
    Frame có tiếng sau speech_end là đầu đoạn kế tiếp, không được tính cho đoạn này."""
    clock = _Clock()
    voice, quiet = b"\x01\x00", b"\x00\x00"

    class _Probe:
        def probability(self, frame: bytes) -> float:
            return 0.9 if frame == voice else 0.1

    diagnostics = diag.SpeechDiagnostics(clock=clock, probe=_Probe())
    utterance = diagnostics.utterance_started()
    for frame in (voice, voice, voice, quiet, quiet):  # 3 frame giọng + 2 frame hangover
        clock.now += 0.03
        diagnostics.observe_frame(frame, is_speech=True, frame_ms=30)
    clock.now += 0.6
    diagnostics.utterance_vad_ended(utterance)
    clock.now += 0.03
    diagnostics.observe_frame(voice, is_speech=True, frame_ms=30)  # đoạn sau bắt đầu
    record = diagnostics.utterance_finished(
        utterance, decision=diag.DROPPED, stage=diag.STAGE_TURN, reason=diag.REASON_SUPERSEDED
    )

    assert (record.speech_ms, record.voice_ms) == (150.0, 90.0)
    assert record.vad_prob_mean == 0.58
    assert round(record.endpoint_ms) == 630
    assert round(record.voice_endpoint_ms) == 690


def test_broken_probe_is_disabled_without_breaking_observation() -> None:
    class _Broken:
        def probability(self, frame: bytes) -> float:
            raise RuntimeError("onnx")

    diagnostics = diag.SpeechDiagnostics(clock=_Clock(), probe=_Broken())
    diagnostics.utterance_started()
    diagnostics.observe_frame(b"\x00\x00", is_speech=True, frame_ms=30)
    diagnostics.observe_frame(b"\x00\x00", is_speech=True, frame_ms=30)
    diagnostics.close()

    assert diagnostics.utterances[0].speech_ms == 60.0
    assert diagnostics.utterances[0].vad_prob_mean is None


async def test_barge_in_outcomes_and_latency() -> None:
    clock = _Clock()
    diagnostics = diag.SpeechDiagnostics(clock=clock)

    class _TTS:
        async def cancel(self) -> None:
            pass

    interruption = InterruptionController(
        _TTS(), min_speech_ms=0, clock=clock, diagnostics=diagnostics
    )
    interruption.on_bot_started_speaking("xin chào")
    await interruption.on_speech_started(VadEvent("speech_start"))
    clock.now += 0.4
    await interruption.on_partial_transcript(TranscriptEvent(text="khoan đã", is_final=False))
    interruption.on_bot_stopped_speaking()

    interruption.on_bot_started_speaking("câu sau")
    await interruption.on_speech_started(VadEvent("speech_start"))
    await interruption.on_speech_ended_without_confirmation()

    assert [b.outcome for b in diagnostics.barge_ins] == ["CONFIRMED", "REVERTED"]
    assert round(diagnostics.barge_ins[0].latency_ms) == 400


async def test_asr_event_reaches_only_the_call_that_owns_the_task() -> None:
    first = diag.SpeechDiagnostics(clock=_Clock())
    second = diag.SpeechDiagnostics(clock=_Clock())
    first.utterance_started()
    second.utterance_started()

    async def skip() -> None:
        diag.report_asr_event(diag.ASR_SKIP_MIN_DECODE)

    loop = asyncio.get_running_loop()
    await loop.create_task(skip(), context=diag.context_with(first))
    diag.report_asr_event(diag.ASR_SKIP_MIN_DECODE)  # ngoài task: không ai nhận

    assert first._open.asr_skips == 1
    assert second._open.asr_skips == 0


def test_ingress_detects_narrowband_and_missing_audio() -> None:
    clock = _Clock()
    monitor = IngressMonitor(clock=clock)
    t = np.arange(480) / 16_000
    narrow = (6000 * np.sin(2 * np.pi * 700 * t)).astype(np.int16).tobytes()
    for i in range(110):
        clock.now = i * 0.03
        monitor.observe(narrow, 16_000, queue_depth=3)
    clock.now += 1.0  # một giây không có frame nào tới (bị rơi)
    monitor.observe(narrow, 16_000)

    summary = monitor.summary()
    assert summary["bandwidth"] == "narrowband"
    assert 950 <= summary["missing_ms"] <= 1050
    assert summary["max_queue_depth"] == 3


def test_ingress_detects_wideband() -> None:
    monitor = IngressMonitor(clock=_Clock())
    rng = np.random.default_rng(0)
    for _ in range(110):
        monitor.observe(rng.normal(0, 3000, 480).astype(np.int16).tobytes(), 16_000)

    assert monitor.bandwidth == "wideband"


def test_ingress_does_not_guess_bandwidth_from_a_click() -> None:
    monitor = IngressMonitor(clock=_Clock())
    t = np.arange(480) / 16_000
    click = (8000 * np.sin(2 * np.pi * 700 * t)).astype(np.int16).tobytes()
    for _ in range(3):  # 90 ms có tiếng
        monitor.observe(click, 16_000)

    assert monitor.bandwidth == "unknown"


def test_lookback_reported_before_the_turn_opens_goes_to_the_next_utterance() -> None:
    """ASR và VAD đọc hai hàng đợi riêng: ASR có thể vào đoạn mới trước TurnController."""
    diagnostics = diag.SpeechDiagnostics(clock=_Clock())
    diagnostics.on_asr_event(diag.ASR_VOICE_LOOKBACK, 270.0)
    diagnostics.utterance_started()
    diagnostics.close()

    assert diagnostics.utterances[0].asr_lookback_ms == 270.0
