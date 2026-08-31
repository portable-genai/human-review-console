"""GCP ReviewStorePort: a Firestore-backed, tenant-partitioned review queue (SDK imports lazy).

Every item is stored under a per-tenant collection path so a query for one tenant physically
cannot read another's. The ``google-cloud-firestore`` import lives inside each method so the
offline / onprem profiles import this module with no GCP SDK installed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from hex_service_kit.serialization import dataclass_from_jsonable, to_jsonable

from ...config import Settings
from ...domain.models import ReviewItem

#: The one thing this module needs from ``firestore.transactional``: it takes the transaction
#: callback and hands back something callable with the same result. Declared here so the
#: decorator is typed whether or not the SDK is installed -- see the note at its use.
_Transactional = Callable[
    [Callable[[Any], tuple[ReviewItem, bool]]], Callable[[Any], tuple[ReviewItem, bool]]
]


def _hydrate(data: dict[str, Any]) -> ReviewItem:
    item: ReviewItem = dataclass_from_jsonable(ReviewItem, data)
    return item


class FirestoreReviewStore:
    """Tenant-partitioned review queue on Firestore native mode (asia-southeast1, CMEK)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _collection(self, client: Any, tenant: str) -> Any:  # pragma: no cover - needs live GCP
        # Tenant is a path segment: reads are physically scoped to one tenant's subtree.
        return client.collection("tenants").document(tenant).collection("reviews")

    def put(self, item: ReviewItem) -> None:  # pragma: no cover - needs live GCP
        from google.cloud import firestore

        client = firestore.Client()
        doc = self._collection(client, item.tenant).document(item.review_id)
        doc.set(to_jsonable(item))

    def put_if_absent_by_source_key(
        self, item: ReviewItem
    ) -> tuple[ReviewItem, bool]:  # pragma: no cover
        if not item.request.source_key:
            self.put(item)
            return item, True

        # Query and write occur in one transaction. Firestore retries this callback if another
        # producer inserts a matching source key between the query and the write, at which point
        # the retried callback returns that already-created item instead of a duplicate.
        from google.cloud import firestore

        client = firestore.Client()
        collection = self._collection(client, item.tenant)
        query = collection.where("request.source_key", "==", item.request.source_key).limit(1)

        # Whether this decorator counted as "untyped" used to be a property of the ENVIRONMENT
        # rather than of this file: `firestore.transactional` is a typed callable where the SDK
        # is installed and `Any` where it is not. So the offline gate REQUIRED a
        # `# type: ignore[untyped-decorator]` here and the lint-gcp job reported the same comment
        # as unused, and deleting it to satisfy either check broke the other -- two checks
        # disagreeing about one line.
        #
        # (The earlier note here blamed firestore for shipping no `py.typed`. It ships one, and
        # `transactional` is annotated; the disagreement was only ever about the SDK's presence.)
        #
        # Declaring the signature this code relies on removes the disagreement in both
        # directions, and unlike the ignore it is CHECKED: if `create_or_load` stopped matching
        # `_Transactional`, mypy would say so instead of staying quiet.
        transactional = cast(_Transactional, firestore.transactional)

        @transactional
        def create_or_load(transaction: Any) -> tuple[ReviewItem, bool]:
            docs = query.get(transaction=transaction)
            if docs:
                return _hydrate(docs[0].to_dict()), False
            transaction.set(collection.document(item.review_id), to_jsonable(item))
            return item, True

        # No cast here any more: the declared decorator type carries the result through, which
        # is the erasure the old `# type: ignore` was quietly paying for. Both checks now agree
        # that this line needs nothing, where before they disagreed about the line above it.
        return create_or_load(client.transaction())

    def get(self, tenant: str, review_id: str) -> ReviewItem | None:  # pragma: no cover
        from google.cloud import firestore

        client = firestore.Client()
        snap = self._collection(client, tenant).document(review_id).get()
        if not snap.exists:
            return None
        return _hydrate(snap.to_dict())

    def find_by_source_key(
        self, tenant: str, source_key: str
    ) -> ReviewItem | None:  # pragma: no cover
        if not source_key:
            return None
        from google.cloud import firestore

        client = firestore.Client()
        docs = (
            self._collection(client, tenant)
            .where("request.source_key", "==", source_key)
            .limit(1)
            .stream()
        )
        return next((_hydrate(doc.to_dict()) for doc in docs), None)

    def list_pending(self, tenant: str) -> list[ReviewItem]:  # pragma: no cover
        return [i for i in self.list_all(tenant) if not i.is_terminal]

    def list_all(self, tenant: str) -> list[ReviewItem]:  # pragma: no cover
        from google.cloud import firestore

        client = firestore.Client()
        docs = self._collection(client, tenant).stream()
        return [_hydrate(d.to_dict()) for d in docs]
