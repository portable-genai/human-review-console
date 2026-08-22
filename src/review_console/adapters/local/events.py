"""Local EventPublisherPort: appends content-free events to an in-memory list (SDK-free)."""

from __future__ import annotations

import threading


class _Event:
    __slots__ = ("event_type", "tenant", "case_id", "attributes")

    def __init__(
        self, event_type: str, tenant: str, case_id: str, attributes: dict[str, str]
    ) -> None:
        self.event_type = event_type
        self.tenant = tenant
        self.case_id = case_id
        self.attributes = attributes


class LocalEventPublisher:
    """In-memory event log for the offline profile."""

    def __init__(self, settings: object) -> None:
        self._lock = threading.Lock()
        self._events: list[_Event] = []

    def publish(
        self, *, event_type: str, tenant: str, case_id: str, attributes: dict[str, str]
    ) -> None:
        with self._lock:
            self._events.append(_Event(event_type, tenant, case_id, dict(attributes)))

    def published(self) -> list[_Event]:
        """Expose published events for inspection in tests and the demo."""
        with self._lock:
            return list(self._events)
