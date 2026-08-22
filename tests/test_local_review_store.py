"""Durability and idempotency checks for the SDK-free local Hrz7 review store."""

from __future__ import annotations

from pathlib import Path

from review_console.adapters.local.audit import LocalAuditAdapter
from review_console.adapters.local.review_store import LocalReviewStore
from review_console.config import Settings
from review_console.domain.console_service import ConsoleService


def _console(path: str) -> ConsoleService:
    settings = Settings(profile="local", audit_path=":memory:", review_db_path=path)
    return ConsoleService(LocalReviewStore(settings), LocalAuditAdapter(settings))


def test_source_key_is_idempotent_and_tenant_scoped_after_restart(tmp_path: Path) -> None:
    path = str(tmp_path / "hrz7.sqlite3")
    first = _console(path)
    created = first.submit_idempotent(
        review_id="first-id",
        maker="demo.analyst@bank.example",
        tenant="demo-bank",
        action="cdd_dossier",
        subject="Acme (FICTIONAL)",
        summary="CDD needs independent review",
        source_key="doc1:demo-bank:case-001:cdd_dossier",
    )
    restarted = _console(path)
    retry = restarted.submit_idempotent(
        review_id="second-id",
        maker="demo.analyst@bank.example",
        tenant="demo-bank",
        action="cdd_dossier",
        subject="Acme (FICTIONAL)",
        summary="retry must reuse the original",
        source_key="doc1:demo-bank:case-001:cdd_dossier",
    )
    other_tenant = restarted.submit_idempotent(
        review_id="other-tenant-id",
        maker="demo.analyst@other.example",
        tenant="other-bank",
        action="cdd_dossier",
        subject="Acme (FICTIONAL)",
        summary="same producer key is allowed in another tenant",
        source_key="doc1:demo-bank:case-001:cdd_dossier",
    )

    assert retry.review_id == created.review_id
    assert restarted.list_queue("demo-bank")[0].review_id == created.review_id
    assert other_tenant.review_id == "other-tenant-id"
    assert restarted.get_by_source_key("other-bank", "doc1:demo-bank:case-001:cdd_dossier")
    assert restarted.get_by_source_key("demo-bank", "different-key") is None
