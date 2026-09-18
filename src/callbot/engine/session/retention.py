"""Temporary customer content; only a technical tombstone survives retirement."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RetentionPolicy:
    idle_seconds: int = 1800
    max_age_seconds: int = 7200

    def __post_init__(self) -> None:
        if not 0 < self.idle_seconds <= self.max_age_seconds:
            raise ValueError("Retention requires 0 < idle_seconds <= max_age_seconds")

    def cutoffs(self) -> tuple[datetime, datetime]:
        now = utcnow()
        return (
            now - timedelta(seconds=self.idle_seconds),
            now - timedelta(seconds=self.max_age_seconds),
        )
