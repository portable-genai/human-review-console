"""EventPublisherPort: the case-lifecycle event boundary (Pub/Sub in production).

The engine publishes a content-free event on open / transition / escalation so downstream
verticals (and the review console's own queue) can react. Events carry ids and the decision, never
raw case content. The local adapter appends to an in-memory list so the publish path is testable.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EventPublisherPort(Protocol):
    def publish(
        self, *, event_type: str, tenant: str, case_id: str, attributes: dict[str, str]
    ) -> None:
        """Publish one content-free case-lifecycle event."""
        ...
