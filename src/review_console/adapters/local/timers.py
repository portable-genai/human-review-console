"""Local TimerPort: records scheduled timers in memory (no real wall-clock wait).

Exercises the scheduling path in tests and the demo without a scheduler: a production deploy binds
Cloud Tasks / Cloud Scheduler instead. Keyed by ``(tenant, case_id, clock)`` so a reschedule
replaces rather than duplicates.
"""

from __future__ import annotations

import threading
from datetime import datetime

from ...config import Settings


class LocalTimerAdapter:
    """In-memory timer register for the offline profile."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._timers: dict[tuple[str, str, str], datetime] = {}

    def schedule(self, *, tenant: str, case_id: str, clock: str, fire_at: datetime) -> None:
        with self._lock:
            self._timers[(tenant, case_id, clock)] = fire_at

    def cancel(self, *, tenant: str, case_id: str, clock: str) -> None:
        with self._lock:
            self._timers.pop((tenant, case_id, clock), None)

    def scheduled(self) -> dict[tuple[str, str, str], datetime]:
        """Expose scheduled timers for inspection in tests and the demo."""
        with self._lock:
            return dict(self._timers)
