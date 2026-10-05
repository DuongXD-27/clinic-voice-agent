"""LiveKit Agent Worker — process riêng biệt với FastAPI (transports/http/main.py).

Chạy: python -m callbot.transports.livekit.worker

Nhận job dispatch từ LiveKit Cloud, mỗi job = 1 CallBridge độc lập (mỗi call state
riêng, nhiều job chạy chung 1 worker process không được share state).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from callbot.engine import EngineSettings, create_orchestrator
from callbot.tracing import create_tracer
from callbot.transports.http.clinic_backend import build_clinic
from callbot.transports.http.config import settings as http_settings
from callbot.transports.livekit.call_bridge import CallBridge
from callbot.transports.livekit.settings import LiveKitSettings
from inference.asr import create_asr_gateway
from speech.asr.recognizer import SpeechRecognizer
from speech.bundle import build_streaming_bundle, warm_up
from speech.settings import SpeechSettings

if TYPE_CHECKING:
    from livekit.agents import JobContext, JobProcess

logger = logging.getLogger(__name__)

_PREWARMED_ASR = "zipformer_asr"


def prewarm(proc: "JobProcess") -> None:
    """Load model ASR local (vd. ZipFormer) một lần mỗi LiveKit job process, trước khi
    process đó nhận call."""
    asr = SpeechRecognizer(create_asr_gateway(SpeechSettings().asr_provider))
    warm_up(asr)
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
    speech_settings = SpeechSettings()
    prewarmed_asr: Any = ctx.proc.userdata.get(_PREWARMED_ASR)
    bundle = build_streaming_bundle(
        speech_settings,
        sample_rate=livekit_settings.input_sample_rate,
        asr=prewarmed_asr,
        frame_ms=livekit_settings.frame_ms,
        queue_max_frames=max(1, livekit_settings.input_queue_ms // livekit_settings.frame_ms),
        barge_in_preroll_ms=livekit_settings.barge_in_preroll_ms,
    )
    # Cùng CLINIC_BACKEND với bot HTTP. sim: mỗi job (mỗi cuộc gọi) một clinic mới seed lại, nên
    # lịch mẫu luôn còn chờ xác nhận; không chung dữ liệu với sim trong process bot.
    clinic = build_clinic(http_settings)
    tracer = create_tracer()
    orchestrator = create_orchestrator(clinic, EngineSettings(), tracer=tracer)

    bridge = CallBridge(
        ctx.room,
        orchestrator,
        bundle.stt_pipeline,
        bundle.tts,
        direction=direction,
        caller_number=caller_number,
        appointment_id=appointment_id,
        turn_controller=bundle.turn_controller,
        interruption_validator=bundle.validator,
        interruption_min_snr_db=speech_settings.interruption_min_snr_db,
        sample_rate=livekit_settings.input_sample_rate,
        frame_ms=livekit_settings.frame_ms,
        input_queue_ms=livekit_settings.input_queue_ms,
        output_queue_ms=livekit_settings.output_queue_ms,
        caller_identity=participant.identity,
        silence_timeout_ms=livekit_settings.silence_timeout_ms,
        krisp_noise_suppression_enabled=livekit_settings.krisp_noise_suppression_enabled,
    )
    try:
        await bridge.run()
    finally:
        await asyncio.to_thread(tracer.close, 2.0)
        try:
            # Mỗi cuộc gọi một bundle: đóng kết nối TTS giữ sẵn (cả client stream), không để rò theo job
            await bundle.tts.aclose()
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
            # Rỗng giữ automatic dispatch; có tên thì chỉ nhận job token browser gọi đúng tên.
            agent_name=livekit_settings.agent_name,
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
