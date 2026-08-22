"""On-prem CaseStorePort: fail-fast portability placeholder."""

from __future__ import annotations

from ...config import Settings
from ...domain.cases.models import Case

_MSG = (
    "on-prem case store is a portability placeholder: bind the client's own tenant-partitioned "
    "store (see docs/onprem-migration.md)"
)


class OnPremCaseStore:
    """Satisfies CaseStorePort but refuses at call time: the client wires their own store."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def put(self, case: Case) -> None:
        raise NotImplementedError(_MSG)

    def get(self, tenant: str, case_id: str) -> Case | None:
        raise NotImplementedError(_MSG)

    def list_by_tenant(self, tenant: str) -> list[Case]:
        raise NotImplementedError(_MSG)
