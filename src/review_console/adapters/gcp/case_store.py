"""GCP CaseStorePort: a Firestore-backed, tenant-partitioned case store (SDK imports lazy).

Every case is stored under a per-tenant collection path so a query for one tenant physically
cannot read another's. The ``google-cloud-firestore`` import lives inside each method so the
offline / onprem profiles import this module with no GCP SDK installed.
"""

from __future__ import annotations

from typing import Any

from hex_service_kit.serialization import dataclass_from_jsonable, to_jsonable

from ...config import Settings
from ...domain.cases.models import Case


def _hydrate(data: dict[str, Any]) -> Case:
    case: Case = dataclass_from_jsonable(Case, data)
    return case


class FirestoreCaseStore:
    """Tenant-partitioned case store on Firestore native mode (asia-southeast1, CMEK)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _collection(self, client: Any, tenant: str) -> Any:  # pragma: no cover - needs live GCP
        return client.collection("tenants").document(tenant).collection("cases")

    def put(self, case: Case) -> None:  # pragma: no cover - needs live GCP
        from google.cloud import firestore

        client = firestore.Client()
        self._collection(client, case.tenant).document(case.case_id).set(to_jsonable(case))

    def get(self, tenant: str, case_id: str) -> Case | None:  # pragma: no cover
        from google.cloud import firestore

        client = firestore.Client()
        snap = self._collection(client, tenant).document(case_id).get()
        if not snap.exists:
            return None
        return _hydrate(snap.to_dict())

    def list_by_tenant(self, tenant: str) -> list[Case]:  # pragma: no cover
        from google.cloud import firestore

        client = firestore.Client()
        docs = self._collection(client, tenant).stream()
        return [_hydrate(d.to_dict()) for d in docs]
