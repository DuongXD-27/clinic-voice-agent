"""Run a dedicated HTTP Clinic Mock with enough future slots for repeated SIP calls.

Reads Clinic Mock source without modifying its checkout. Fixtures exist only in
this process; restarting restores them. Keep this separate from shared demos.
"""

import argparse
import json
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import dotenv_values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clinic-source", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument(
        "--snapshot-file", type=Path, help="Preserve an existing dedicated mock's harness snapshot"
    )
    parser.add_argument("--future-slot-count", type=int, default=6)
    args = parser.parse_args()
    if not 1 <= args.future_slot_count <= 24:
        parser.error("--future-slot-count must be between 1 and 24")
    saved = (
        json.loads(args.snapshot_file.read_text(encoding="utf-8")) if args.snapshot_file else None
    )
    source = args.clinic_source.resolve() / "src"
    if not (source / "clinic_mock" / "app.py").is_file():
        parser.error("--clinic-source must contain src/clinic_mock/app.py")
    values = dotenv_values(".env")
    key = values.get("CLINIC_MOCK_API_KEY")
    if not key:
        parser.error("Set CLINIC_MOCK_API_KEY in .env")
    os.environ["MOCK_API_KEYS"] = "baseline:" + key
    os.environ["LANGFUSE_TRACES_ENABLED"] = "false"
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(source))
    import uvicorn
    from clinic_mock.app import app
    from clinic_mock.schemas import Appointment, Patient, Slot
    from clinic_mock.store import db

    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with original(application):
            template = db.slots.get("slot_91d2")
            if template is None:
                raise RuntimeError("Clinic Mock lacks canonical slot_91d2 fixture")
            if saved is not None:
                # Harness snapshots include tenant/slot/provider fields omitted by public APIs.
                db.patients = {
                    row["patient_id"]: Patient.model_validate(row) for row in saved["patients"]
                }
                db.slots = {row["slot_id"]: Slot.model_validate(row) for row in saved["slots"]}
                db.appointments = {
                    row["appointment_id"]: Appointment.model_validate(row)
                    for row in saved["appointments"]
                }
                db.writelog.entries = list(saved.get("writelog", []))
                db.system_clock_offset_sec = saved.get("system_clock_offset_sec", 0)
            reserved = {
                appointment.slot_id
                for appointment in db.appointments.values()
                if appointment.status in {"SCHEDULED", "BOOKED", "CONFIRMED"}
            }
            tomorrow = (datetime.now(timezone(timedelta(hours=7))) + timedelta(days=1)).replace(
                hour=10, minute=0, second=0, microsecond=0
            )
            added = 0
            for index in range(args.future_slot_count):
                slot_id = f"slot_sip_baseline_{index + 1}"
                if slot_id in db.slots or slot_id in reserved:
                    continue
                start = tomorrow + timedelta(hours=index)
                slot = template.model_copy(
                    update={
                        "slot_id": slot_id,
                        "start_time": start.isoformat(),
                        "end_time": (start + timedelta(minutes=30)).isoformat(),
                    }
                )
                db.slots[slot.slot_id] = slot
                added += 1
            print(
                f"Dedicated baseline mock: {added} future slots added; {len(db.appointments)} appointments retained"
            )
            yield

    app.router.lifespan_context = lifespan
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
