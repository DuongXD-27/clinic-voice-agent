"""Chạy migration SQL có phiên bản — MỘT lần trước khi khởi động worker.

    python -m callbot.engine.session.postgres.migrate

Đọc `SESSION_DATABASE_URL`. Nhiều tiến trình chạy cùng lúc vẫn an toàn nhờ advisory lock riêng.
"""

import logging
import sys

import psycopg

from callbot.engine.session.postgres.schema import LATEST_SCHEMA_VERSION, migration_files
from callbot.engine.session.postgres.settings import SessionStoreSettings

logger = logging.getLogger(__name__)

# Khóa riêng của migration, khác không gian khóa theo call_id (hashtextextended)
_MIGRATION_LOCK = 7_310_424_001


def migrate(conninfo: str) -> list[int]:
    """Áp các migration chưa chạy, mỗi file một transaction. Trả về các phiên bản vừa áp."""
    applied_now: list[int] = []
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (_MIGRATION_LOCK,))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version INTEGER PRIMARY KEY,"
                " name TEXT NOT NULL,"
                " applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
            for version, path in migration_files():
                if version in applied:
                    continue
                with conn.transaction():
                    conn.execute(path.read_text(encoding="utf-8"))
                    conn.execute(
                        "INSERT INTO schema_migrations (version, name) VALUES (%s, %s)",
                        (version, path.name),
                    )
                applied_now.append(version)
                logger.info("Đã áp migration %s", path.name)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (_MIGRATION_LOCK,))
    return applied_now


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    url = SessionStoreSettings().session_database_url
    if not url:
        logger.error("Thiếu SESSION_DATABASE_URL")
        return 2
    applied = migrate(url)
    logger.info("Schema ở phiên bản %s (vừa áp: %s)", LATEST_SCHEMA_VERSION, applied or "không có")
    return 0


if __name__ == "__main__":
    sys.exit(main())
