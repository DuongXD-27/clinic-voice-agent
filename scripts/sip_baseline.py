"""Inspect or provision the authenticated inbound softphone baseline.

Reads LiveKit credentials from .env through LiveKitSettings. Provisioning creates
one trunk and one rule; re-running reuses them and never deletes other resources.
SIP authentication password is kept in .env, never printed in the inventory.
"""

import argparse
import asyncio
import json
import secrets
from pathlib import Path

import aiohttp
from dotenv import dotenv_values
from livekit import api

from callbot.transports.livekit.settings import LiveKitSettings

TRUNK_NAME = "vinmec-softphone-baseline"
RULE_NAME = "vinmec-inbound-booking-baseline"


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["inspect", "provision"])
    args = parser.parse_args()
    settings = LiveKitSettings()
    if not all([settings.livekit_url, settings.livekit_api_key, settings.livekit_api_secret]):
        raise SystemExit("Set LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET in .env")
    if args.command == "provision" and not settings.agent_name:
        raise SystemExit("Set LIVEKIT_AGENT_NAME for deterministic dispatch")
    async with api.LiveKitAPI(
        settings.livekit_url,
        settings.livekit_api_key,
        settings.livekit_api_secret,
        timeout=aiohttp.ClientTimeout(total=20),
    ) as lk:
        trunks = (await lk.sip.list_inbound_trunk(api.ListSIPInboundTrunkRequest())).items
        rules = (await lk.sip.list_dispatch_rule(api.ListSIPDispatchRuleRequest())).items
        trunk = next((t for t in trunks if t.name == TRUNK_NAME), None)
        rule = next((r for r in rules if r.name == RULE_NAME), None)
        if args.command == "provision":
            if trunk is None:
                values = dotenv_values(".env")
                password = values.get("SIP_BASELINE_PASSWORD")
                if not password:
                    password = secrets.token_urlsafe(24)
                    with Path(".env").open("a", encoding="utf-8") as env:
                        env.write("\nSIP_BASELINE_PASSWORD=" + password + "\n")
                trunk = await lk.sip.create_inbound_trunk(
                    api.CreateSIPInboundTrunkRequest(
                        trunk=api.SIPInboundTrunkInfo(
                            name=TRUNK_NAME,
                            numbers=["1000"],
                            auth_username="vinmec-baseline",
                            auth_password=password,
                        )
                    )
                )
            if rule is None:
                rule = await lk.sip.create_dispatch_rule(
                    api.CreateSIPDispatchRuleRequest(
                        dispatch_rule=api.SIPDispatchRuleInfo(
                            name=RULE_NAME,
                            trunk_ids=[trunk.sip_trunk_id],
                            hide_phone_number=False,
                            rule=api.SIPDispatchRule(
                                dispatch_rule_individual=api.SIPDispatchRuleIndividual(
                                    room_prefix="sip-booking-"
                                )
                            ),
                            room_config=api.RoomConfiguration(
                                agents=[api.RoomAgentDispatch(agent_name=settings.agent_name)]
                            ),
                        )
                    )
                )
            print("Baseline resources ready; SIP password is in .env (SIP_BASELINE_PASSWORD)")
            # Creation responses are authoritative; avoid a second pair of list
            # calls just to display resources we have already read or created.
            if not any(t.sip_trunk_id == trunk.sip_trunk_id for t in trunks):
                trunks = [*trunks, trunk]
            if not any(r.sip_dispatch_rule_id == rule.sip_dispatch_rule_id for r in rules):
                rules = [*rules, rule]
        print(
            json.dumps(
                {
                    "trunks": [
                        {"id": t.sip_trunk_id, "name": t.name, "numbers": list(t.numbers)}
                        for t in trunks
                    ],
                    "rules": [
                        {
                            "id": r.sip_dispatch_rule_id,
                            "name": r.name,
                            "trunk_ids": list(r.trunk_ids),
                            "agents": [a.agent_name for a in r.room_config.agents],
                            "hide_phone_number": r.hide_phone_number,
                        }
                        for r in rules
                    ],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
