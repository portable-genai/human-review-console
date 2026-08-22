"""Local CaseStorePort: an in-memory, tenant-partitioned case store (SDK-free, deterministic).

Keyed by ``(tenant, case_id)`` so a lookup for one tenant can never return another's case. Thread
-safe for the TestClient and demo server.
"""

from __future__ import annotations

import threading

from ...config import Settings
from ...domain.cases.models import Case


class LocalCaseStore:
    """In-memory case-state + transition-history store for the offline profile."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._cases: dict[tuple[str, str], Case] = {}

    def put(self, case: Case) -> None:
        with self._lock:
            self._cases[(case.tenant, case.case_id)] = case

    def get(self, tenant: str, case_id: str) -> Case | None:
        with self._lock:
            return self._cases.get((tenant, case_id))

    def list_by_tenant(self, tenant: str) -> list[Case]:
        with self._lock:
            return [case for (t, _), case in self._cases.items() if t == tenant]
