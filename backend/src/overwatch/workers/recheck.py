"""Weekly re-check due logic — pure and unit-tested (design doc §4)."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta


@dataclass(frozen=True)
class RecheckWindows:
    before: tuple[date, date]
    after: tuple[date, date]


def is_due(cadence_days: int | None, last_checked_at: datetime | None, now: datetime) -> bool:
    if cadence_days is None:
        return False
    if last_checked_at is None:
        return True
    return last_checked_at + timedelta(days=cadence_days) <= now


def recheck_windows(last_after_capture: date, today: date) -> RecheckWindows | None:
    """Baseline = the previous run's after scene (exact day); search window = everything newer."""
    day_after = last_after_capture + timedelta(days=1)
    if day_after >= today:
        return None
    return RecheckWindows(before=(last_after_capture, day_after), after=(day_after, today))
