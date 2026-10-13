"""Packaged cache through CallBridge PCM frames, tracing and real barge-in cleanup."""

from tests.transports.livekit_support import require_livekit

require_livekit()

from tests.speech.tts.static_support import cached_synthesizer, release_manifest  # noqa: E402
from tests.transports.livekit.test_call_bridge_mapping import (  # noqa: E402
    _RecordingTracer,
    _speaking_bridge,
)


async def test_cache_audio_reaches_livekit_frames_and_traces_zero_cost():
    text = release_manifest()["assets"][0]["utterance"]
    for _ in range(2):
        tts, provider, fallback = cached_synthesizer()
        bridge, source = _speaking_bridge(tts)
        tracer = _RecordingTracer()
        bridge._tracer = tracer
        await bridge._speak(text)
        pcm = b"".join(bytes(frame.data) for frame in source.captured_frames)
        assert pcm == tts._static_cache.lookup(text).pcm
        assert all(
            frame.sample_rate == 8000 and frame.samples_per_channel <= 160
            for frame in source.captured_frames
        )
        assert not provider.calls and not fallback.calls
        (span,) = tracer.spans
        assert span.attributes["cache_hit"] is True
        assert span.attributes["billed_characters"] == 0
        assert span.attributes["cost_usd"] == 0
        assert span.attributes["result"] == "OK"
        assert span.attributes["catalog_version"] == "2026-10-08-v2"


async def test_barge_in_stops_cached_audio_and_next_turn_can_play():
    tts, provider, fallback = cached_synthesizer()
    bridge, source = _speaking_bridge(tts)
    bridge._tracer = tracer = _RecordingTracer()
    text = release_manifest()["assets"][0]["utterance"]
    original_capture = source.capture_frame

    async def interrupt_after_first_frame(frame):
        await original_capture(frame)
        if len(source.captured_frames) == 1:
            await bridge._interruption._confirm()

    source.capture_frame = interrupt_after_first_frame
    await bridge._speak(text)
    assert len(source.captured_frames) == 1 and source.clear_queue_calls >= 1
    assert tracer.spans[0].attributes["result"] == "CANCELLED"
    assert tracer.spans[0].attributes["cost_usd"] == 0
    source.capture_frame = original_capture
    source.captured_frames.clear()
    await bridge._speak(text)
    assert (
        b"".join(bytes(frame.data) for frame in source.captured_frames)
        == tts._static_cache.lookup(text).pcm
    )
    assert not provider.calls and not fallback.calls


async def test_dynamic_livekit_utterance_still_uses_gateway(monkeypatch):
    tts, provider, fallback = cached_synthesizer()
    bridge, _ = _speaking_bridge(tts)
    bridge._tracer = tracer = _RecordingTracer()
    monkeypatch.setattr("callbot.transports.livekit.call_bridge.tts_cost", lambda *args: 0.01)
    text = "Lịch khám của anh là ngày 15 tháng 10, lúc 10 giờ."
    await bridge._speak(text)
    assert provider.calls == [text] and not fallback.calls
    (span,) = tracer.spans
    assert span.attributes["cache_hit"] is False
    assert span.attributes["billed_characters"] is None
    assert span.attributes["cost_usd"] == 0.01
