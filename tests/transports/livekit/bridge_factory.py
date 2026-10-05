"""Dựng CallBridge cho test với cấu hình của test (không phải config/livekit.yaml)."""

from tests.transports.livekit_support import require_livekit

require_livekit()

from callbot.transports.livekit.call_bridge import CallBridge  # noqa: E402
from speech.turn.controller import TurnController  # noqa: E402
from speech.types import NARROWBAND_RATE  # noqa: E402

_TEST_CONFIG = {
    "interruption_validator": None,
    "interruption_min_snr_db": None,
    "sample_rate": NARROWBAND_RATE,
    "frame_ms": 30,
    "input_queue_ms": 1_500,
    "output_queue_ms": 200,
    "silence_timeout_ms": 0,
    "krisp_noise_suppression_enabled": False,
}


def make_call_bridge(room, orchestrator, stt_pipeline, tts, **overrides) -> CallBridge:
    # Mỗi bridge một TurnController riêng, như worker (mỗi cuộc gọi một bundle).
    turn_controller = overrides.pop("turn_controller", None) or TurnController()
    return CallBridge(
        room,
        orchestrator,
        stt_pipeline,
        tts,
        turn_controller=turn_controller,
        **{**_TEST_CONFIG, **overrides},
    )
