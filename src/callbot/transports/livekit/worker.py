"""LiveKit Agent Worker — process riêng biệt với FastAPI (transports/http/main.py).

Chạy: python -m callbot.transports.livekit.worker

Nhận job dispatch từ LiveKit Cloud, mỗi job = 1 CallBridge độc lập (mỗi call state
riêng, nhiều job chạy chung 1 worker process không được share state).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Optional

from callbot.engine import EngineSettings, create_orchestrator
from callbot.tracing import create_tracer
from callbot.transports.http.clinic_backend import build_clinic
from callbot.transports.http.config import settings as http_settings
from callbot.transports.livekit.call_bridge import CallBridge
from callbot.transports.livekit.settings import LiveKitSettings
from callbot.transports.livekit.status import report_status
from callbot.transports.livekit.stt_session import SttSession
from inference.asr import create_asr_gateway
from inference.asr.base import AsrAuthError
from speech.asr.recognizer import SpeechRecognizer
from speech.bundle import build_streaming_bundle, turn_controller_options, warm_up, warm_up_vad
from speech.settings import SpeechSettings

if TYPE_CHECKING:
    from livekit.agents import JobContext, JobProcess

logger = logging.getLogger(__name__)

_PREWARMED_ASR = "zipformer_asr"
# ASR người gọi thử chọn trên trang gọi (participant attribute `asr_provider`, gắn lúc xin token).
_SELECTABLE_ASR = ("zipformer", "gemini_live", "elevenlabs_realtime")
# Trang thử STT (`/ui/stt`) gắn `mode=stt`: chỉ chạy STTPipeline và gửi chữ, không có bot.
MODE_ATTRIBUTE = "mode"
# Worker báo lại ASR thực sự dùng cho cuộc gọi (attribute của bot) để trang gọi hiển thị.
ASR_ATTRIBUTE = "asr_provider"


def prewarm(proc: "JobProcess") -> None:
    """Load model ASR local (vd. ZipFormer) và Silero v6 một lần mỗi LiveKit job process, trước
    khi process đó nhận call."""
    provider = LiveKitSettings().asr_provider or SpeechSettings().asr_provider
    asr = SpeechRecognizer(create_asr_gateway(provider))
    try:
        warm_up(asr)
    except NotImplementedError:
        logger.info("ASR %s uses streaming only; skipping batch warm-up", asr.name)
    proc.userdata[_PREWARMED_ASR] = asr
    # Chỉ để cuộc gọi đầu không phải nạp model trên event loop; lỗi thật sẽ lộ khi dựng bundle.
    try:
        warm_up_vad(SpeechSettings())
    except Exception as exc:
        logger.warning("worker: không nạp sẵn được Silero v6: %s", exc)


def speech_settings_for(
    participant_kind: int,
    livekit_settings: LiveKitSettings,
    requested_asr: Optional[str] = None,
) -> SpeechSettings:
    """Cấu hình speech cho một cuộc gọi: ASR riêng của LiveKit, và `phone_overrides` khi người
    gọi vào qua SIP (âm thanh điện thoại 8 kHz G.711). `requested_asr`: ASR chọn trên trang gọi
    thử (thắng cấu hình worker); giá trị lạ bị bỏ qua."""
    from livekit import rtc

    settings = SpeechSettings()
    provider = requested_asr if requested_asr in _SELECTABLE_ASR else livekit_settings.asr_provider
    if provider:
        settings = settings.model_copy(update={"asr_provider": provider})
    if participant_kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
        settings = settings.for_phone()
    return settings


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
    requested_asr = attrs.get(ASR_ATTRIBUTE) or None

    livekit_settings = LiveKitSettings()
    speech_settings = speech_settings_for(participant.kind, livekit_settings, requested_asr)
    prewarmed_asr: Any = ctx.proc.userdata.get(_PREWARMED_ASR)
    asr = await _recognizer_for(speech_settings.asr_provider, prewarmed_asr)
    if asr is None:
        # Chọn ASR nào thì chỉ dùng ASR đó: không tạo được (vd. thiếu GEMINI_API_KEY) thì báo lên
        # trang gọi thử và dừng, không đổi sang ASR nạp sẵn của worker.
        await report_status(
            ctx.room,
            "ASR_UNAVAILABLE",
            f"Worker không tạo được ASR {speech_settings.asr_provider} (thiếu key hoặc model). "
            "Cuộc gọi dừng, không chuyển sang ASR khác.",
        )
        ctx.shutdown(reason="asr unavailable")
        return
    logger.info(
        "worker: participant kind=%s asr_provider=%s (requested=%s) asr_pre_speech_ms=%s",
        participant.kind,
        speech_settings.asr_provider,
        requested_asr,
        speech_settings.asr_pre_speech_ms,
    )
    stt_only = attrs.get(MODE_ATTRIBUTE) == "stt"
    bundle = build_streaming_bundle(
        speech_settings,
        sample_rate=livekit_settings.input_sample_rate,
        frame_ms=livekit_settings.frame_ms,
        input_queue_ms=livekit_settings.input_queue_ms,
        asr_queue_ms=livekit_settings.asr_queue_ms,
        barge_in_preroll_ms=livekit_settings.barge_in_preroll_ms,
        asr=asr,
        with_tts=not stt_only,
    )
    try:
        await ctx.room.local_participant.set_attributes(
            {ASR_ATTRIBUTE: str(speech_settings.asr_provider)}
        )
    except Exception as exc:  # chỉ để hiển thị trên trang gọi thử, không được làm hỏng cuộc gọi
        logger.warning("worker: không gắn được attribute ASR: %s", type(exc).__name__)
    if stt_only:
        await _run_stt_only(ctx, bundle, speech_settings, livekit_settings, participant.identity)
        return
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
        interruption_echo_policy=speech_settings.turn_echo_policy,
        sample_rate=livekit_settings.input_sample_rate,
        frame_ms=livekit_settings.frame_ms,
        input_queue_ms=livekit_settings.input_queue_ms,
        output_queue_ms=livekit_settings.output_queue_ms,
        caller_identity=participant.identity,
        silence_timeout_ms=livekit_settings.silence_timeout_ms,
        krisp_noise_suppression_enabled=livekit_settings.krisp_noise_suppression_enabled,
        demo_debug=livekit_settings.demo_debug,
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


async def _run_stt_only(
    ctx: JobContext,
    bundle: Any,
    speech_settings: SpeechSettings,
    livekit_settings: LiveKitSettings,
    caller_identity: str,
) -> None:
    """Trang thử STT: cùng pipeline (VAD, tăng âm, ASR, chốt lượt) với cuộc gọi, không bot/TTS."""
    session = SttSession(
        ctx.room,
        bundle.stt_pipeline,
        turn_controller_options={
            "validator": bundle.validator,
            **turn_controller_options(speech_settings),
        },
        sample_rate=livekit_settings.input_sample_rate,
        frame_ms=livekit_settings.frame_ms,
        input_queue_ms=livekit_settings.input_queue_ms,
        krisp_enabled=livekit_settings.krisp_noise_suppression_enabled,
        caller_identity=caller_identity,
    )
    try:
        await session.run()
    except Exception as exc:
        # Model hỏng giữa chừng (vd. thiếu thư viện của provider, key bị từ chối, mất kết nối):
        # báo lên trang, không để trang chờ mãi một worker đã rời phòng. Message lỗi lạ có thể
        # chứa dữ liệu cuộc gọi: chỉ gửi tên lỗi, trừ các lỗi tự mô tả ở dưới.
        if isinstance(exc, ModuleNotFoundError):
            detail = f"worker thiếu thư viện {exc.name}"
        elif isinstance(exc, AsrAuthError):
            detail = str(exc)
        else:
            detail = type(exc).__name__
        await report_status(
            ctx.room,
            "STT_FAILED",
            f"ASR {speech_settings.asr_provider} lỗi khi nhận dạng ({detail}). Phiên thử đã dừng.",
        )
        raise


async def _recognizer_for(provider: str, prewarmed: Any) -> Any:
    """ASR cho cuộc gọi: dùng lại bản nạp sẵn khi cùng provider; khác thì tạo mới (ZipFormer nạp
    model trong thread). None khi không tạo được (thiếu key, provider lỗi) — không thay bằng
    ASR khác."""
    if prewarmed is not None and getattr(prewarmed, "name", None) == provider:
        return prewarmed
    try:
        asr = SpeechRecognizer(create_asr_gateway(provider))
        if provider == "zipformer":
            await asyncio.to_thread(warm_up, asr)
    except Exception as exc:
        logger.error(
            "worker: không tạo được ASR %s (%s) — dừng cuộc gọi", provider, type(exc).__name__
        )
        return None
    return asr


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
