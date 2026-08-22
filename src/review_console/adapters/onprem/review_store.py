"""On-prem ReviewStorePort: fail-fast portability placeholder."""

from __future__ import annotations

from ...config import Settings
from ...domain.models import ReviewItem


class OnPremReviewStore:
    """Satisfies ReviewStorePort but refuses at call time: the client wires its own store."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def put(self, item: ReviewItem) -> None:
        raise NotImplementedError(
            "on-prem review store is a portability placeholder: bind the client's own "
            "tenant-partitioned store (see docs/onprem-migration.md)"
        )

    def put_if_absent_by_source_key(self, item: ReviewItem) -> tuple[ReviewItem, bool]:
        raise NotImplementedError(
            "on-prem review store is a portability placeholder: bind the client's own "
            "tenant-partitioned store (see docs/onprem-migration.md)"
        )

    def get(self, tenant: str, review_id: str) -> ReviewItem | None:
        raise NotImplementedError(
            "on-prem review store is a portability placeholder (see docs/onprem-migration.md)"
        )

    def find_by_source_key(self, tenant: str, source_key: str) -> ReviewItem | None:
        raise NotImplementedError(
            "on-prem review store is a portability placeholder (see docs/onprem-migration.md)"
        )

    def list_pending(self, tenant: str) -> list[ReviewItem]:
        raise NotImplementedError(
            "on-prem review store is a portability placeholder (see docs/onprem-migration.md)"
        )

    def list_all(self, tenant: str) -> list[ReviewItem]:
        raise NotImplementedError(
            "on-prem review store is a portability placeholder (see docs/onprem-migration.md)"
        )
