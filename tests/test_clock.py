"""The business-day / regulatory clock maths: the primitive this repo exists to get right once.

These tests ARE the spec for weekend and holiday counting. 2026-06-01 is a Monday, used as the
anchor throughout so the arithmetic is easy to check by eye.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from review_console.domain.cases.clock import (
    add_business_days,
    add_calendar_days,
    business_days_between,
    deadline_for,
    is_business_day,
)
from review_console.domain.cases.kernel import ClockKind
from review_console.domain.cases.models import ClockSpec

MON = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)  # a Monday
FRI = datetime(2026, 6, 5, 9, 0, tzinfo=UTC)  # the Friday of the same week


def test_is_business_day_skips_weekends_and_holidays() -> None:
    assert is_business_day(date(2026, 6, 1), frozenset())  # Monday
    assert not is_business_day(date(2026, 6, 6), frozenset())  # Saturday
    assert not is_business_day(date(2026, 6, 7), frozenset())  # Sunday
    assert not is_business_day(date(2026, 6, 1), frozenset({date(2026, 6, 1)}))  # holiday


def test_add_business_days_counts_from_the_next_day() -> None:
    # Mon + 2 business days = Wed.
    assert add_business_days(MON, 2, frozenset()).date() == date(2026, 6, 3)
    # Preserves the time of day.
    assert add_business_days(MON, 2, frozenset()).hour == 9


def test_add_business_days_jumps_the_weekend() -> None:
    # Thu 2026-06-04 + 2 business days skips Sat/Sun -> Mon 2026-06-08.
    thu = datetime(2026, 6, 4, 9, 0, tzinfo=UTC)
    assert add_business_days(thu, 2, frozenset()).date() == date(2026, 6, 8)


def test_add_business_days_skips_a_holiday() -> None:
    # Mon + 2 business days, but Wed is a holiday -> Thu.
    assert add_business_days(MON, 2, frozenset({date(2026, 6, 3)})).date() == date(2026, 6, 4)


def test_business_days_between_is_signed() -> None:
    wed = datetime(2026, 6, 3, 9, 0, tzinfo=UTC)
    assert business_days_between(MON, wed, frozenset()) == 2
    assert business_days_between(wed, MON, frozenset()) == -2
    assert business_days_between(MON, MON, frozenset()) == 0


def test_business_days_between_excludes_the_weekend() -> None:
    next_mon = datetime(2026, 6, 8, 9, 0, tzinfo=UTC)
    # Fri -> next Mon is one business day (Mon), not three calendar days.
    assert business_days_between(FRI, next_mon, frozenset()) == 1


def test_add_calendar_days_includes_weekends() -> None:
    assert add_calendar_days(FRI, 3).date() == date(2026, 6, 8)


def test_deadline_for_business_not_breached() -> None:
    spec = ClockSpec("ack", ClockKind.BUSINESS, 2, "received", warn_ratio=0.5)
    status = deadline_for(spec, MON, MON, frozenset())
    assert status.due_at is not None and status.due_at.date() == date(2026, 6, 3)
    assert status.remaining_days == 2
    assert not status.breached


def test_deadline_for_business_breached() -> None:
    spec = ClockSpec("ack", ClockKind.BUSINESS, 2, "received", warn_ratio=0.5)
    status = deadline_for(spec, MON, FRI, frozenset())  # due Wed, as_of Fri
    assert status.breached
    assert status.remaining_days == -2


def test_deadline_for_business_approaching() -> None:
    spec = ClockSpec("ack", ClockKind.BUSINESS, 2, "received", warn_ratio=0.5)
    tue = datetime(2026, 6, 2, 10, 0, tzinfo=UTC)
    status = deadline_for(spec, MON, tue, frozenset())
    assert not status.breached
    assert status.approaching  # 1 business day left, warn threshold is 1


def test_deadline_for_unstarted_clock_is_dormant() -> None:
    spec = ClockSpec("resolution", ClockKind.BUSINESS, 20, "under_review")
    # anchor None: the case has not reached the start state, so the clock has not started.
    status = deadline_for(spec, None, MON, frozenset())
    assert status.due_at is None
    assert not status.breached
    assert not status.approaching


def test_deadline_for_calendar_counts_wall_days() -> None:
    spec = ClockSpec("cooling_off", ClockKind.CALENDAR, 14, "received")
    status = deadline_for(spec, MON, MON, frozenset())
    assert status.due_at is not None and status.due_at.date() == date(2026, 6, 15)
    assert status.remaining_days == 14
