"""Auto-widening scene search windows (design spec §6: +15-day steps, +60-day cap)."""

from datetime import date, timedelta


def candidate_windows(
    start: date, end: date, *, step_days: int = 15, cap_days: int = 60
) -> list[tuple[date, date]]:
    """The original window plus end-extended windows in step_days increments up to cap_days."""
    if end < start:
        raise ValueError(f"end {end} is before start {start}")
    return [(start, end + timedelta(days=d)) for d in range(0, cap_days + 1, step_days)]
