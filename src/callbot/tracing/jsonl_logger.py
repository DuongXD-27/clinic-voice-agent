"""Trace mỗi lượt ra JSONL (Appendix B.1) — dùng chung cho mọi transport."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class JsonlLogger:
    def __init__(self, path: str = "traces.jsonl") -> None:
        self._path = Path(path)

    def log(self, call_id: str, turn: int, event: dict[str, Any]) -> None:
        record = {
            "call_id": call_id,
            "turn": turn,
            "ts": datetime.now(timezone.utc).isoformat(),
            # Allowlist: không lưu transcript, hồ sơ, audio URL hay payload Clinic.
            **{
                key: event[key]
                for key in (
                    "event",
                    "direction",
                    "state",
                    "outcome",
                    "transfer_reason",
                    "unreachable_reason",
                )
                if key in event
            },
        }
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
