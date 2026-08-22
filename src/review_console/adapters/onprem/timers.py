"""On-prem TimerPort: fail-fast portability placeholder."""

from __future__ import annotations

from datetime import datetime

from ...config import Settings

_MSG = (
    "on-prem timer is a portability placeholder: bind the client's own scheduler "
    "(see docs/onprem-migration.md)"
)


class OnPremTimerAdapter:
    """Satisfies TimerPort but refuses at call time: the client wires their own scheduler."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def schedule(self, *, tenant: str, case_id: str, clock: str, fire_at: datetime) -> None:
        raise NotImplementedError(_MSG)

    def cancel(self, *, tenant: str, case_id: str, clock: str) -> None:
        raise NotImplementedError(_MSG)
