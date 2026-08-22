"""CaseStorePort: the tenant-partitioned case-state + transition-history boundary.

Every method takes a ``tenant`` and the store MUST scope to it: an adapter may never return a case
from another tenant. Tenant isolation is defense in depth (the store partitions, and the API only
ever queries within the caller's tenant), so a query bug cannot leak another tenant's cases.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.cases.models import Case


@runtime_checkable
class CaseStorePort(Protocol):
    def put(self, case: Case) -> None:
        """Insert or replace a case (keyed by tenant + case_id)."""
        ...

    def get(self, tenant: str, case_id: str) -> Case | None:
        """Return the case iff it exists AND belongs to ``tenant``; otherwise ``None``."""
        ...

    def list_by_tenant(self, tenant: str) -> list[Case]:
        """Return every case for ``tenant``, oldest first."""
        ...
