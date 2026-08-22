"""TimerPort: the deadline-timer boundary (Cloud Tasks / Cloud Scheduler in production).

The engine schedules a timer to fire when a clock's deadline is reached, so a breach is acted on
even if no one polls the case. The domain computes the deadline deterministically; the timer is
only the wake-up. The local adapter records timers in memory (no real wall-clock wait) so the
scheduling path is exercised in tests without a scheduler.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class TimerPort(Protocol):
    def schedule(self, *, tenant: str, case_id: str, clock: str, fire_at: datetime) -> None:
        """Schedule (or replace) a timer that fires at ``fire_at`` for one case clock."""
        ...

    def cancel(self, *, tenant: str, case_id: str, clock: str) -> None:
        """Cancel a scheduled timer (for example when the case reaches a terminal state)."""
        ...
