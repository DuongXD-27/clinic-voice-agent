"""Danh sách migration SQL có phiên bản (`NNN_ten.sql`)."""

import re
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
_FILE_NAME = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")


def migration_files() -> list[tuple[int, Path]]:
    files = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        match = _FILE_NAME.match(path.name)
        if match is None:
            raise ValueError(f"Tên migration không hợp lệ: {path.name}")
        files.append((int(match.group(1)), path))
    return files


LATEST_SCHEMA_VERSION = max(version for version, _ in migration_files())
