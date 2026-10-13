"""Call context at the WebRTC/SIP boundary; SIP caller ID comes from LiveKit."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Literal

from livekit import api, rtc

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParticipantCall:
    direction: Literal["inbound", "outbound"]
    caller_number: str | None
    appointment_id: str | None
    is_sip: bool


def participant_call(participant: rtc.RemoteParticipant) -> ParticipantCall:
    attrs = participant.attributes
    is_sip = participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
    if is_sip:
        # This worker is dispatched only for inbound SIP. Outbound SIP jobs need
        # a separate dispatch path and explicit appointment context.
        # Do not fall back to web attributes or the called DID. Missing/hidden caller
        # ID must reach the core's NO_PHONE policy, rather than identify someone else.
        return ParticipantCall("inbound", attrs.get("sip.phoneNumber") or None, None, True)
    direction = attrs.get("direction") or "inbound"
    if direction not in ("inbound", "outbound"):
        raise ValueError("Invalid call direction")
    return ParticipantCall(
        direction, attrs.get("caller_number") or None, attrs.get("appointment_id") or None, False
    )


async def hangup_sip_caller(ctx, identity: str, *, playout_grace_ms: int = 0) -> None:
    """Remove only this caller, after the bridge has drained its final TTS audio.

    AudioSource drains the agent's local queue, not the handset jitter buffer.
    A bounded grace period lets the final frames traverse the SIP media path.
    Leaving the agent room alone does not send BYE to the SIP caller. A caller
    that already hung up needs no second removal. If removal fails, delete this
    dedicated call room so the SIP leg cannot remain connected in silence.
    """
    if identity in ctx.room.remote_participants and playout_grace_ms > 0:
        logger.info("SIP hangup: waiting %d ms for remote media playout", playout_grace_ms)
        await asyncio.sleep(playout_grace_ms / 1000)
    if identity in ctx.room.remote_participants:
        logger.info("SIP hangup: removing caller")
        try:
            await ctx.api.room.remove_participant(
                api.RoomParticipantIdentity(room=ctx.room.name, identity=identity)
            )
        except api.TwirpError as exc:
            if exc.code == api.TwirpErrorCode.NOT_FOUND:
                logger.info("SIP hangup: caller already absent")
                return
            logger.warning("SIP hangup: removal failed (%s); deleting room", exc.code)
            await ctx.delete_room()
            return
        except Exception as exc:
            logger.warning("SIP hangup: removal failed (%s); deleting room", type(exc).__name__)
            await ctx.delete_room()
            return
        logger.info("SIP hangup: caller removed")
    else:
        logger.info("SIP hangup: caller already absent")
