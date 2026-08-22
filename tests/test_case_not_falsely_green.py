"""Prove the case-engine eval metrics are not structurally falsely green (the C4 / E2 lesson).

``clock_accuracy`` is the safety metric: it must be able to distinguish correct business-day maths
from a broken calculation. We show it by scoring the real ``deadline_for`` (green) against a
deliberately-broken calendar-day mutant that ignores weekends (red).
"""

from __future__ import annotations

from datetime import UTC, datetime

from agent_eval_kit import assert_can_go_red
from pii_kit import pack_leak, redact

from review_console.domain.cases.clock import add_calendar_days, deadline_for
from review_console.domain.cases.kernel import ClockKind
from review_console.domain.cases.models import ClockSpec
from review_console.domain.pii import PII_PATTERNS

MON = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)  # a Monday
FRI = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)  # after the correct Wed business-day deadline
_SPEC = ClockSpec("ack", ClockKind.BUSINESS, 2, "received", warn_ratio=0.5)


def _correct_breached() -> bool:
    """The real engine: 2 business days from Monday is due Wednesday, so Friday is breached."""
    return deadline_for(_SPEC, MON, FRI, frozenset()).breached


def _broken_breached() -> bool:
    """A mutant that counts calendar days: 2 calendar days from Monday is Wednesday too, but a
    naive implementation that just adds duration as calendar days and never re-checks would place
    the deadline wrong when a weekend intervenes. Here we model the classic bug: treat the clock
    as not-yet-breached by adding calendar days from as_of instead of the anchor.
    """
    wrong_due = add_calendar_days(FRI, _SPEC.duration_days)  # anchored on as_of, not the start
    return wrong_due < FRI


def test_clock_accuracy_can_go_red() -> None:
    # Metric: 1.0 when the breach verdict is correct (True), 0.0 when the mutant disagrees.
    def score(breached: bool) -> float:
        return 1.0 if breached else 0.0

    assert_can_go_red(
        score,
        green=_correct_breached(),  # real engine: breached -> True -> 1.0
        red=_broken_breached(),  # mutant: not breached -> False -> 0.0
        threshold=0.99,
        metric="clock_accuracy",
    )


_RAW = "Case for borrower NRIC S1234567D"


def _pii_safety(text: str) -> float:
    return 0.0 if pack_leak(text, PII_PATTERNS) else 1.0


def test_pii_safety_can_go_red() -> None:
    assert_can_go_red(
        _pii_safety,
        green=redact(_RAW, PII_PATTERNS),
        red=_RAW,
        threshold=0.99,
        metric="pii_safety",
    )
