"""Local, dependency-free completed-span JSONL sink."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import monotonic

from callbot.tracing.models import CompletedSpan
from callbot.tracing.privacy import validate_completed_span


class JsonlTraceSink:
    def __init__(
        self,
        directory: str | Path,
        *,
        max_file_bytes: int = 50 * 1024 * 1024,
        retention_days: int = 7,
        total_cap_bytes: int = 1024 * 1024 * 1024,
        cleanup_interval_s: float = 60.0,
        pid: int | None = None,
    ) -> None:
        if (
            max_file_bytes <= 0
            or retention_days < 0
            or total_cap_bytes <= 0
            or cleanup_interval_s < 0
        ):
            raise ValueError("invalid JSONL retention settings")
        self._directory = Path(directory)
        self._max_file_bytes = max_file_bytes
        self._retention_days = retention_days
        self._total_cap_bytes = total_cap_bytes
        self._cleanup_interval_s = cleanup_interval_s
        self._pid = os.getpid() if pid is None else pid
        self._lock = threading.Lock()
        self._day = ""
        self._sequence = 0
        self._path: Path | None = None
        self._last_cleanup_at: float | None = None

    @property
    def current_path(self) -> Path | None:
        return self._path

    def emit(self, span: CompletedSpan) -> None:
        validate_completed_span(span)
        payload = (
            json.dumps(
                span.to_dict(), ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
            + b"\n"
        )
        with self._lock:
            self._directory.mkdir(parents=True, exist_ok=True)
            path = self._select_path(len(payload))
            descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
            try:
                written = os.write(descriptor, payload)
                if written != len(payload):
                    raise OSError("incomplete trace append")
            finally:
                os.close(descriptor)
            self._cleanup_if_due()

    def _cleanup_if_due(self) -> None:
        now = monotonic()
        if (
            self._last_cleanup_at is not None
            and now - self._last_cleanup_at < self._cleanup_interval_s
        ):
            return
        self._cleanup()
        self._last_cleanup_at = now

    def _select_path(self, payload_size: int) -> Path:
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        if day != self._day:
            self._day = day
            self._sequence = 0
            self._path = self._make_path()
        assert self._path is not None
        try:
            size = self._path.stat().st_size
        except FileNotFoundError:
            size = 0
        if size and size + payload_size > self._max_file_bytes:
            self._sequence += 1
            self._path = self._make_path()
        return self._path

    def _make_path(self) -> Path:
        suffix = "" if self._sequence == 0 else f"-{self._sequence}"
        return self._directory / f"trace-{self._day}-p{self._pid}{suffix}.jsonl"

    def _cleanup(self) -> None:
        files = list(self._directory.glob("trace-????????-p*.jsonl"))
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._retention_days)
        for path in files:
            try:
                modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
                if modified < cutoff:
                    path.unlink(missing_ok=True)
            except OSError:
                continue

        files_with_stats: list[tuple[Path, os.stat_result]] = []
        for path in self._directory.glob("trace-????????-p*.jsonl"):
            try:
                files_with_stats.append((path, path.stat()))
            except OSError:
                continue
        total = sum(stat.st_size for _, stat in files_with_stats)
        for path, stat in sorted(files_with_stats, key=lambda item: item[1].st_mtime):
            if total <= self._total_cap_bytes:
                break
            try:
                path.unlink()
                total -= stat.st_size
            except OSError:
                continue
