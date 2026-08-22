"""ReviewStorePort: the tenant-partitioned review queue + sign-off store (the hexagon edge).

Every method takes a ``tenant`` and the store MUST scope to it: an adapter may never return an
item from another tenant. Tenant isolation is enforced in the domain too (the eligibility check),
but the store keeping its own partition is defense in depth, so a query bug cannot leak a queue.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import ReviewItem


@runtime_checkable
class ReviewStorePort(Protocol):
    def put(self, item: ReviewItem) -> None:
        """Insert or replace an item (keyed by tenant + review_id)."""
        ...

    def put_if_absent_by_source_key(self, item: ReviewItem) -> tuple[ReviewItem, bool]:
        """Persist an S2S item atomically, returning ``(item, created)``.

        For an empty source key this is equivalent to ``put`` and returns ``True``. For a
        non-empty key, adapters must return the existing same-tenant item on a retry.
        """
        ...

    def get(self, tenant: str, review_id: str) -> ReviewItem | None:
        """Return the item iff it exists AND belongs to ``tenant``; otherwise ``None``."""
        ...

    def find_by_source_key(self, tenant: str, source_key: str) -> ReviewItem | None:
        """Return the S2S-created item for this tenant/key, or ``None``.

        The caller supplies a producer-owned, stable source key. The tenant parameter is
        mandatory so an identifier collision cannot cross the tenant boundary.
        """
        ...

    def list_pending(self, tenant: str) -> list[ReviewItem]:
        """Return the pending queue for ``tenant`` only, oldest first."""
        ...

    def list_all(self, tenant: str) -> list[ReviewItem]:
        """Return every item for ``tenant`` (any state), oldest first."""
        ...
