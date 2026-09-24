"""LiveKit Agent Worker — process riêng biệt với FastAPI (transports/http/main.py).

Chạy: python -m callbot.transports.livekit.worker

Nhận job dispatch từ LiveKit Cloud, mỗi job = 1 CallBridge độc lập (mỗi call state
riêng, nhiều job chạy chung 1 worker process không được share state).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from callbot.engine import EngineSettings, create_orchestrator
from callbot.engine.tools.clinic_mock_client import ClinicMockClient
from callbot.transports.http.config import settings as http_settings
from callbot.transports.livekit.call_bridge import CallBridge
from callbot.transports.livekit.settings import LiveKitSettings
from inference.asr import create_asr_gateway
from speech.asr.recognizer import SpeechRecognizer
from speech.bundle import build_streaming_bundle
from speech.settings import SpeechSettings
from speech.turn.controller import TurnController
from speech.types import AudioSegment

if TYPE_CHECKING:
    from livekit.agents import JobContext, JobProcess

logger = logging.getLogger(__name__)

_PREWARMED_ASR = "zipformer_asr"


def prewarm(proc: "JobProcess") -> None:
    """Load model ASR local (vd. ZipFormer) một lần mỗi LiveKit job process, trước khi
    process đó nhận call. Provider cloud/streaming-only (vd. elevenlabs_realtime) không có
    model file để nạp trước và `transcribe()` của nó raise `NotImplementedError` có chủ ý
    (chỉ hỗ trợ `stream()`) — bỏ qua warm-up cho các provider này, không coi là lỗi."""
    livekit_settings = LiveKitSettings()
    speech_settings = SpeechSettings(sample_rate=livekit_settings.input_sample_rate)
    asr = SpeechRecognizer(create_asr_gateway(speech_settings.asr_provider))
    try:
        # Một đoạn silence đủ để lazy provider tạo OfflineRecognizer/model trong prewarm.
        asr.transcribe(
            AudioSegment(
                pcm=b"\x00\x00" * asr.input_sample_rate,
                sample_rate=asr.input_sample_rate,
            )
        )
    except NotImplementedError:
        pass
    proc.userdata[_PREWARMED_ASR] = asr


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    # Chờ browser join trước khi đọc direction/caller_number/appointment_id giả lập
    # (gắn qua token attribute, xem transports/http/livekit_token.py) — participant
    # chưa chắc đã có mặt ngay sau connect() vì đây là job của Agent, không phải browser.
    participant = await ctx.wait_for_participant()
    attrs = participant.attributes
    direction = attrs.get("direction") or "inbound"
    caller_number = attrs.get("caller_number") or None
    appointment_id = attrs.get("appointment_id") or None

    livekit_settings = LiveKitSettings()
    speech_settings = SpeechSettings(sample_rate=livekit_settings.input_sample_rate)
    prewarmed_asr: Any = ctx.proc.userdata.get(_PREWARMED_ASR)
    bundle = build_streaming_bundle(
        speech_settings,
        asr=prewarmed_asr,
        frame_ms=livekit_settings.frame_ms,
        queue_max_frames=max(1, livekit_settings.input_queue_ms // livekit_settings.frame_ms),
        barge_in_preroll_ms=livekit_settings.barge_in_preroll_ms,
    )
    clinic = ClinicMockClient(
        http_settings.require_clinic_mock_base_url(), http_settings.clinic_mock_api_key
    )
    orchestrator = create_orchestrator(clinic, EngineSettings())
    turn_controller = TurnController(
        min_speech_ms=speech_settings.turn_min_speech_ms,
        max_wait_after_vad_end_ms=speech_settings.turn_max_wait_after_vad_end_ms,
        post_bot_guard_ms=speech_settings.turn_post_bot_guard_ms,
        validator=bundle.validator,
    )

    bridge = CallBridge(
        ctx.room,
        orchestrator,
        bundle.stt_pipeline,
        bundle.tts,
        direction=direction,
        caller_number=caller_number,
        appointment_id=appointment_id,
        turn_controller=turn_controller,
        evidence_tracker=bundle.evidence_tracker,
        noise_tracker=bundle.noise_tracker,
        noise_classifier=bundle.noise_classifier,
        interruption_validator=bundle.validator,
        interruption_min_snr_db=speech_settings.interruption_min_snr_db,
        sample_rate=livekit_settings.input_sample_rate,
        frame_ms=livekit_settings.frame_ms,
        input_queue_ms=livekit_settings.input_queue_ms,
        output_queue_ms=livekit_settings.output_queue_ms,
    )
    try:
        await bridge.run()
    finally:
        close = getattr(clinic, "close", None)
        if close is not None:
            close()


def main() -> None:
    from livekit.agents import WorkerOptions, cli

    # WorkerOptions không tự đọc .env qua pydantic-settings (khác phần transports/http) —
    # truyền tường minh từ LiveKitSettings, tránh phụ thuộc os.environ đã được nạp sẵn.
    livekit_settings = LiveKitSettings()
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            ws_url=livekit_settings.livekit_url,
            api_key=livekit_settings.livekit_api_key,
            api_secret=livekit_settings.livekit_api_secret,
            num_idle_processes=livekit_settings.worker_num_idle_processes,
        )
    )


if __name__ == "__main__":
    # Bật log turn.text (PII, mặc định ẩn ở mức INFO) để chẩn đoán ASR nghe sai gì — xem
    # call_bridge.py::run(). KHÔNG dùng `logging.basicConfig()`/biến env tuỳ ý ở đây: LiveKit
    # CLI (cli.run_app(), gọi bên trong main()) tự cấu hình lại root logger THEO SAU qua
    # `setup_logging()` (livekit/agents/cli/log.py), ghi đè bất kỳ level nào set trước đó.
    # Cách đúng để bật DEBUG (đã xác nhận qua `--help` của chính CLI này):
    #   LIVEKIT_LOG_LEVEL=debug python -m callbot.transports.livekit.worker start
    #   hoặc: python -m callbot.transports.livekit.worker start --log-level debug
    main()
