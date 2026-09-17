"""Tra cứu CHỈ ĐỌC phục vụ đối soát (F-03). Không mở khóa, không sửa phiên.

    python -m callbot.engine.session.postgres.inspect blocked
    python -m callbot.engine.session.postgres.inspect call <call_id>

Không in tên / ngày sinh người gọi khai báo; transcript từng lượt vẫn in vì cần để đối soát.
Hướng dẫn: docs/reference/session-operations.md.
"""

import argparse
import json
import sys
from typing import Any

import psycopg
from psycopg.rows import dict_row

from callbot.engine.session.postgres.settings import SessionStoreSettings

_CONTEXT_SUMMARY_KEYS = (
    "state",
    "identity_step",
    "pending_action",
    "selected_slot_id",
    "outcome",
    "transfer_reason",
    "unreachable_reason",
)


def blocked_calls(conn: psycopg.Connection) -> list[dict[str, Any]]:
    return conn.execute(
        "SELECT t.call_id, t.turn, t.detail, t.updated_at,"
        " count(c.idempotency_key) FILTER (WHERE c.status <> 'SUCCEEDED'"
        "   AND c.status <> 'FAILED') AS unsettled_commands"
        " FROM call_turns t LEFT JOIN clinic_commands c USING (call_id, turn)"
        " WHERE t.status = 'RECONCILIATION_REQUIRED'"
        " GROUP BY t.call_id, t.turn, t.detail, t.updated_at ORDER BY t.updated_at"
    ).fetchall()


def call_detail(conn: psycopg.Connection, call_id: str) -> dict[str, Any]:
    session = conn.execute(
        "SELECT call_id, start_config, context, last_completed_turn, ended, created_at, updated_at"
        " FROM call_sessions WHERE call_id = %s",
        (call_id,),
    ).fetchone()
    if session is None:
        return {"call_id": call_id, "found": False}
    context = session.pop("context")
    session["context"] = {key: context.get(key) for key in _CONTEXT_SUMMARY_KEYS}
    session["turns"] = conn.execute(
        "SELECT turn, status, input, received_at, result, detail, updated_at"
        " FROM call_turns WHERE call_id = %s ORDER BY turn",
        (call_id,),
    ).fetchall()
    session["commands"] = conn.execute(
        "SELECT idempotency_key, turn, operation, endpoint, payload, if_match, status,"
        " attempts, result, error, created_at, updated_at"
        " FROM clinic_commands WHERE call_id = %s ORDER BY created_at",
        (call_id,),
    ).fetchall()
    return {"found": True, **session}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("blocked", help="Các lượt đang chờ đối soát")
    detail = sub.add_parser("call", help="Chi tiết một cuộc gọi: lượt và lệnh Clinic")
    detail.add_argument("call_id")
    args = parser.parse_args(argv)

    url = SessionStoreSettings().session_database_url
    if not url:
        print("Thiếu SESSION_DATABASE_URL", file=sys.stderr)
        return 2
    with psycopg.connect(url, row_factory=dict_row) as conn:
        conn.read_only = True
        payload = (
            blocked_calls(conn) if args.command == "blocked" else call_detail(conn, args.call_id)
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
