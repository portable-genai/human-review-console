"""Deterministic SLA / regulatory clock maths: business-day and calendar deadlines.

This is the primitive the whole catalog was about to rebuild per vertical, so it is written once,
here, as pure functions an auditor can re-run and a test can pin. "Within N business days" is a
regulatory phrase (MAS, APRA, HKMA turnaround rules), and getting weekend / holiday counting wrong
is a real compliance defect, so the maths is exhaustively unit-tested rather than trusted.

All functions are pure: pass ``as_of`` and the holiday set in; no clock is read here.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta

from .kernel import ClockKind
from .models import ClockSpec, DeadlineStatus


def is_business_day(day: date, holidays: frozenset[date]) -> bool:
    """A weekday (Mon-Fri) that is not a configured holiday."""
    return day.weekday() < 5 and day not in holidays


def add_business_days(start: datetime, n: int, holidays: frozenset[date]) -> datetime:
    """Return ``start`` advanced by ``n`` business days, preserving the time of day.

    Counting begins on the day AFTER ``start``: "3 business days from Monday" lands on Thursday
    (assuming no holidays). ``n`` must be non-negative.
    """
    if n < 0:
        raise ValueError("add_business_days requires n >= 0")
    day = start.date()
    counted = 0
    while counted < n:
        day = day + timedelta(days=1)
        if is_business_day(day, holidays):
            counted += 1
    return datetime.combine(day, start.timetz())


def business_days_between(start: datetime, end: datetime, holidays: frozenset[date]) -> int:
    """Signed count of business days in the interval (min, max], negative if ``end`` precedes.

    Same-day (or same business-day span) is 0. Used to report how many business days remain until
    a deadline (positive) or how many it is overdue by (negative).
    """
    if end == start:
        return 0
    sign = 1 if end > start else -1
    lo, hi = (start, end) if end > start else (end, start)
    day = lo.date()
    count = 0
    while day < hi.date():
        day = day + timedelta(days=1)
        if is_business_day(day, holidays):
            count += 1
    return sign * count


def add_calendar_days(start: datetime, n: int) -> datetime:
    return start + timedelta(days=n)


def calendar_days_between(start: datetime, end: datetime) -> int:
    return (end.date() - start.date()).days


def deadline_for(
    spec: ClockSpec,
    anchor: datetime | None,
    as_of: datetime,
    holidays: frozenset[date] = frozenset(),
) -> DeadlineStatus:
    """Compute one clock's status. ``anchor`` is when the clock's start state was entered.

    ``anchor is None`` means the case has not yet reached the start state, so the clock has not
    started: it is neither breached nor approaching and its due date is unknown.
    """
    if anchor is None:
        return DeadlineStatus(
            clock=spec.name,
            kind=spec.kind.value,
            due_at=None,
            remaining_days=spec.duration_days,
            breached=False,
            approaching=False,
        )

    if spec.kind is ClockKind.BUSINESS:
        due_at = add_business_days(anchor, spec.duration_days, holidays)
        remaining = business_days_between(as_of, due_at, holidays)
    else:
        due_at = add_calendar_days(anchor, spec.duration_days)
        remaining = calendar_days_between(as_of, due_at)

    breached = as_of > due_at
    warn_threshold = math.ceil((1.0 - spec.warn_ratio) * spec.duration_days)
    approaching = (not breached) and remaining <= warn_threshold

    return DeadlineStatus(
        clock=spec.name,
        kind=spec.kind.value,
        due_at=due_at,
        remaining_days=remaining,
        breached=breached,
        approaching=approaching,
    )
