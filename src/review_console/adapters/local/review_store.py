"""Local ReviewStorePort: durable SQLite, tenant-partitioned and SDK-free.

The database belongs to Hrz7 only. Each operation uses a short-lived connection with WAL and a
busy timeout, so the local demo survives restarts while concurrent request threads remain safe.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from hex_service_kit.serialization import dataclass_from_jsonable, to_jsonable

from ...config import Settings
from ...domain.models import ReviewItem


class LocalReviewStore:
    """Durable local review queue + sign-off store for the offline profile."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._path = settings.review_db_path
        self._memory_connection: sqlite3.Connection | None = None
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        else:
            # Each sqlite ``:memory:`` connection is a distinct database. Keep one anchor so
            # tests and explicitly ephemeral local runs still see the initialized schema.
            self._memory_connection = sqlite3.connect(
                ":memory:", timeout=5.0, check_same_thread=False
            )
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        if self._memory_connection is not None:
            return self._memory_connection
        connection = sqlite3.connect(self._path, timeout=5.0)
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reviews (
                    tenant TEXT NOT NULL,
                    review_id TEXT NOT NULL,
                    source_key TEXT NOT NULL DEFAULT '',
                    submitted_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (tenant, review_id)
                )
                """
            )
            # Empty is the non-S2S sentinel, so it intentionally remains repeatable.
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS reviews_tenant_source_key_unique
                ON reviews (tenant, source_key) WHERE source_key <> ''
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS reviews_tenant_submitted_at
                ON reviews (tenant, submitted_at)
                """
            )

    @staticmethod
    def _hydrate(payload: str) -> ReviewItem:
        import json

        data: dict[str, Any] = json.loads(payload)
        item: ReviewItem = dataclass_from_jsonable(ReviewItem, data)
        return item

    def put(self, item: ReviewItem) -> None:
        import json

        payload = json.dumps(to_jsonable(item), sort_keys=True)
        source_key = item.request.source_key
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO reviews (tenant, review_id, source_key, submitted_at, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (tenant, review_id) DO UPDATE SET
                    source_key = excluded.source_key,
                    submitted_at = excluded.submitted_at,
                    payload = excluded.payload
                """,
                (
                    item.tenant,
                    item.review_id,
                    source_key,
                    item.request.submitted_at.isoformat(),
                    payload,
                ),
            )

    def put_if_absent_by_source_key(self, item: ReviewItem) -> tuple[ReviewItem, bool]:
        if not item.request.source_key:
            self.put(item)
            return item, True

        import json

        payload = json.dumps(to_jsonable(item), sort_keys=True)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO reviews (tenant, review_id, source_key, submitted_at, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (tenant, source_key) WHERE source_key <> '' DO NOTHING
                """,
                (
                    item.tenant,
                    item.review_id,
                    item.request.source_key,
                    item.request.submitted_at.isoformat(),
                    payload,
                ),
            )
            if cursor.rowcount == 1:
                return item, True
            row = connection.execute(
                "SELECT payload FROM reviews WHERE tenant = ? AND source_key = ?",
                (item.tenant, item.request.source_key),
            ).fetchone()
        if row is None:  # pragma: no cover - defensive: the unique index guarantees a row.
            raise RuntimeError("idempotent review insert did not create or locate an item")
        return self._hydrate(str(row[0])), False

    def get(self, tenant: str, review_id: str) -> ReviewItem | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM reviews WHERE tenant = ? AND review_id = ?",
                (tenant, review_id),
            ).fetchone()
        return self._hydrate(str(row[0])) if row else None

    def find_by_source_key(self, tenant: str, source_key: str) -> ReviewItem | None:
        if not source_key:
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM reviews WHERE tenant = ? AND source_key = ?",
                (tenant, source_key),
            ).fetchone()
        return self._hydrate(str(row[0])) if row else None

    def list_pending(self, tenant: str) -> list[ReviewItem]:
        return [item for item in self.list_all(tenant) if not item.is_terminal]

    def list_all(self, tenant: str) -> list[ReviewItem]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM reviews "
                "WHERE tenant = ? ORDER BY submitted_at ASC, review_id ASC",
                (tenant,),
            ).fetchall()
        return [self._hydrate(str(row[0])) for row in rows]
