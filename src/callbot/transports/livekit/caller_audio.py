"""Mic người gọi trong room LiveKit thành frame PCM — dùng chung cho cuộc gọi (`CallBridge`) và
trang thử STT (`SttSession`), để trang thử chạy đúng đường audio của cuộc gọi (Krisp, dump)."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Awaitable, Callable, Optional

from callbot.transports.livekit.audio_adapter import livekit_frame_to_segment

if TYPE_CHECKING:
    from livekit import rtc

logger = logging.getLogger(__name__)


def accept_caller_track(
    track: "rtc.Track", publication: object, participant: object, caller_identity: Optional[str]
) -> tuple[bool, Optional[str]]:
    """(có nghe track này không, identity người gọi sau khi xét). Chỉ nghe mic của MỘT người:
    `caller_identity` None thì khoá vào participant đầu tiên có track mic. Trước đây mọi track
    audio của mọi participant (người thứ hai, track share màn hình) cùng đổ vào MỘT hàng đợi —
    hai luồng PCM xen kẽ nhau."""
    from livekit import rtc

    if track.kind != rtc.TrackKind.KIND_AUDIO:
        return False, caller_identity
    identity = getattr(participant, "identity", None)
    source = getattr(publication, "source", rtc.TrackSource.SOURCE_UNKNOWN)
    if source not in (rtc.TrackSource.SOURCE_MICROPHONE, rtc.TrackSource.SOURCE_UNKNOWN):
        logger.info("caller_audio: bỏ qua track audio nguồn %s của %s", source, identity)
        return False, caller_identity
    if caller_identity is None:
        return True, identity
    if identity != caller_identity:
        logger.info("caller_audio: bỏ qua track audio của participant khác %s", identity)
        return False, caller_identity
    return True, caller_identity


def krisp_processor(enabled: bool) -> object | None:
    """THỬ NGHIỆM (docs/evidence §8) — None nếu tắt hoặc package chưa cài. Processor tạo mới mỗi
    lần pump (không tái dùng qua re-publish): auto_close mặc định của AudioStream đóng nó khi
    stream đóng, tái dùng instance đã đóng sẽ lỗi."""
    if not enabled:
        return None
    try:
        from livekit.plugins import krisp
    except ImportError:
        logger.warning(
            "caller_audio: krisp_noise_suppression_enabled=true nhưng livekit-plugins-krisp "
            "chưa cài — bỏ qua, chạy không lọc"
        )
        return None
    return krisp.KrispVivaFilterFrameProcessor(
        mode=krisp.viva_filter.VivaMode.VOICE_ISOLATION, noise_suppression_level=90.0
    )


async def pump_caller_track(
    track: "rtc.Track",
    *,
    call_id: str,
    sample_rate: int,
    frame_ms: int,
    capacity_frames: int,
    krisp_enabled: bool,
    put: Callable[[bytes], Awaitable[None]],
) -> None:
    """Đọc track mic tới khi đóng, đưa từng frame PCM16 mono `sample_rate` vào `put`."""
    from livekit import rtc

    stream = rtc.AudioStream.from_track(
        track=track,
        sample_rate=sample_rate,
        num_channels=1,
        frame_size_ms=frame_ms,
        capacity=capacity_frames,
        noise_cancellation=krisp_processor(krisp_enabled),
    )
    # LIVEKIT_DEBUG_DUMP_AUDIO=1: ghi PCM thật (đã qua livekit_frame_to_segment, đúng đường dữ
    # liệu đưa vào ASR) ra 1 file wav/call trong temp/audio/ — cách duy nhất để xác nhận chắc
    # chắn ASR hallucinate do audio bị méo (sample rate/capture sai) hay do model thật sự nghe
    # nhầm giọng nói rõ ràng. Tắt mặc định: PII + I/O per-frame không nên bật ở production.
    dump_writer = (
        _open_debug_dump(call_id, sample_rate)
        if os.environ.get("LIVEKIT_DEBUG_DUMP_AUDIO")
        else None
    )
    try:
        async for event in stream:
            segment = livekit_frame_to_segment(event.frame, target_rate=sample_rate)
            if segment.pcm:
                if dump_writer is not None:
                    dump_writer.writeframes(segment.pcm)
                await put(segment.pcm)
    finally:
        if dump_writer is not None:
            dump_writer.close()
        await stream.aclose()


def _open_debug_dump(call_id: str, sample_rate: int):
    import wave

    os.makedirs("temp/audio", exist_ok=True)
    path = f"temp/audio/livekit_debug_{call_id}.wav"
    writer = wave.open(path, "wb")
    writer.setnchannels(1)
    writer.setsampwidth(2)
    writer.setframerate(sample_rate)
    logger.warning("caller_audio: LIVEKIT_DEBUG_DUMP_AUDIO bật — ghi PCM vào %s", path)
    return writer
