"""Real Core -> HTTP Clinic Mock booking proof, without SIP or speech providers.

Uses synthetic contract patient fixtures and the configured Redis. The optional
--restore flag restores a Clinic Mock harness snapshot after retaining evidence.
Run only against a dedicated test mock when using --restore.
"""

import argparse
import json
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import dotenv_values

from callbot.engine import (
    CallerInput,
    CallStart,
    EngineSettings,
    RedisSessionStore,
    create_orchestrator,
)
from callbot.engine.tools.clinic_mock_client import ClinicMockClient
from callbot.engine.tools.telemetry import collect_api_calls


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--restore", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    values = dotenv_values(".env")
    base = values["CLINIC_MOCK_BASE_URL"].rstrip("/")
    headers = {"Authorization": "Bearer " + values["CLINIC_MOCK_API_KEY"]}
    redis_url = values.get("REDIS_URL") or "redis://localhost:6379/0"
    # The local Compose Redis requires the configured password. Preserve explicit
    # non-local URLs and URLs that already contain authentication.
    from urllib.parse import quote, urlsplit

    address = urlsplit(redis_url)
    if address.hostname in ("localhost", "127.0.0.1") and not address.password:
        redis_url = (
            "redis://:"
            + quote(values["REDIS_PASSWORD"], safe="")
            + "@"
            + address.netloc
            + address.path
        )
    store = RedisSessionStore.from_url(redis_url, key_prefix="sip-baseline-smoke:" + uuid4().hex)
    results = {"scope": "core-http-clinic-mock; no SIP/ASR/TTS", "calls": []}
    with httpx.Client(base_url=base.removesuffix("/v1"), headers=headers, timeout=5) as harness:
        snapshot = None
        if args.restore:
            response = harness.post("/_harness/snapshot")
            response.raise_for_status()
            snapshot = response.json()["snapshot_id"]
        try:
            with ClinicMockClient(base, values["CLINIC_MOCK_API_KEY"]) as clinic:
                bot = create_orchestrator(
                    clinic, EngineSettings(semantic_fallback_enabled=False), store=store
                )
                for _ in range(args.runs):
                    call_id = "core-booking-" + uuid4().hex
                    before = harness.get("/_harness/appointments")
                    before.raise_for_status()
                    ids = {a["appointment_id"] for a in before.json()}
                    with collect_api_calls() as calls:
                        action = bot.start_call(
                            CallStart(
                                call_id=call_id, direction="inbound", caller_number="+84912345600"
                            )
                        )
                        states = [action.state]
                        for turn, line in enumerate(
                            [
                                "Nguyễn Văn A",
                                "14/03/1978",
                                "Tôi muốn đặt lịch",
                                "khung 1",
                                "Đồng ý",
                            ],
                            1,
                        ):
                            action = bot.handle_turn(call_id, CallerInput(turn, text=line))
                            states.append(action.state)
                    after = harness.get("/_harness/appointments")
                    after.raise_for_status()
                    created = [a for a in after.json() if a["appointment_id"] not in ids]
                    writes = [c for c in calls if c.operation == "create_appointment"]
                    passed = (
                        action.outcome == "BOOKED"
                        and action.ended
                        and len(created) == len(writes) == 1
                        and created[0]["status"] == "BOOKED"
                    )
                    results["calls"].append(
                        {
                            "call_id": call_id,
                            "states": states,
                            "outcome": action.outcome,
                            "passed": passed,
                            "created": [
                                {"appointment_id": a["appointment_id"], "status": a["status"]}
                                for a in created
                            ],
                            "api": [
                                {"method": c.method, "path": c.path, "status": c.status}
                                for c in calls
                            ],
                        }
                    )
                    if not passed:
                        raise RuntimeError("Booking proof failed; see evidence file")
        finally:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")
            if snapshot:
                response = harness.post("/_harness/snapshot/" + snapshot + "/restore")
                response.raise_for_status()
            store.close()
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
