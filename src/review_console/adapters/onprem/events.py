"""On-prem EventPublisherPort: fail-fast portability placeholder."""

from __future__ import annotations

from ...config import Settings

_MSG = (
    "on-prem event publisher is a portability placeholder: bind the client's own message bus "
    "(see docs/onprem-migration.md)"
)


class OnPremEventPublisher:
    """Satisfies EventPublisherPort but refuses at call time: the client wires their own bus."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def publish(
        self, *, event_type: str, tenant: str, case_id: str, attributes: dict[str, str]
    ) -> None:
        raise NotImplementedError(_MSG)
