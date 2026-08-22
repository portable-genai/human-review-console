"""C9: the local WORM log detects tail truncation, not only record doctoring.

A truncated hash chain is still a perfectly valid chain, just shorter, so verification alone
cannot see it. Only an external head anchor can. These tests assert the DEFAULT local binding
configures one for an on-disk log (an adopter should not have to opt in to detecting the easiest
tamper of all), and that the anchor actually catches a deleted tail.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from review_console.adapters.local.audit import LocalAuditAdapter
from review_console.config import Settings
from review_console.domain.kernel import (
    Decision,
    Disposition,
    ReviewState,
    Severity,
    SignOffEvent,
)


def _event(seq: int) -> SignOffEvent:
    return SignOffEvent(
        action="disburse",
        review_id=f"rev-{seq}",
        tenant="demo-bank",
        maker="demo.analyst@bank.example",
        checker="demo.approver@bank.example",
        disposition=Disposition.APPROVE,
        decision=Decision.ALLOWED,
        state=ReviewState.APPROVED,
        severity=Severity.MEDIUM,
        redacted_reason="within delegated authority (FICTIONAL)",
        redacted_summary="disburse facility",
        timestamp=datetime(2026, 7, 19, 12, seq, tzinfo=UTC),
    )


def _on_disk(tmp_path: Path) -> Settings:
    return Settings(profile="local", audit_path=str(tmp_path / "audit.sqlite3"))


def test_an_on_disk_log_is_anchored_by_default(tmp_path: Path) -> None:
    settings = _on_disk(tmp_path)
    assert settings.resolved_audit_anchor_path == f"{settings.audit_path}.anchor"

    adapter = LocalAuditAdapter(settings)
    adapter.record(_event(1))
    assert Path(settings.resolved_audit_anchor_path).is_file()
    assert adapter.log.verify_chain().ok


def test_an_in_memory_log_needs_no_anchor() -> None:
    settings = Settings(profile="local", audit_path=":memory:")
    assert settings.resolved_audit_anchor_path == ""
    adapter = LocalAuditAdapter(settings)
    adapter.record(_event(1))
    assert adapter.log.verify_chain().ok


def test_an_adopter_can_relocate_the_anchor_to_another_volume(tmp_path: Path) -> None:
    elsewhere = tmp_path / "other-volume" / "head.json"
    elsewhere.parent.mkdir()
    settings = Settings(
        profile="local",
        audit_path=str(tmp_path / "audit.sqlite3"),
        audit_anchor_path=str(elsewhere),
    )
    LocalAuditAdapter(settings).record(_event(1))
    assert elsewhere.is_file()


def test_truncating_the_tail_is_caught_by_the_anchor(tmp_path: Path) -> None:
    settings = _on_disk(tmp_path)
    adapter = LocalAuditAdapter(settings)
    for seq in (1, 2, 3):
        adapter.record(_event(seq))
    assert adapter.log.verify_chain().ok

    # Delete the last sign-off directly in the database, bypassing the adapter entirely: the
    # remaining chain still verifies link by link, which is exactly why the anchor is needed.
    connection = sqlite3.connect(settings.audit_path)
    try:
        connection.execute("DROP TRIGGER IF EXISTS audit_log_no_delete")
        connection.execute("DELETE FROM audit_log WHERE seq = (SELECT MAX(seq) FROM audit_log)")
        connection.commit()
    finally:
        connection.close()

    reopened = LocalAuditAdapter(settings)
    report = reopened.log.verify_chain()
    assert not report.ok
    assert "anchor" in report.detail.lower()


def test_the_module_documents_which_tamper_classes_are_detected() -> None:
    import review_console.adapters.local.audit as module

    doc = (module.__doc__ or "").lower()
    assert "detected" in doc and "not detected" in doc
    assert "truncat" in doc


def test_settings_reject_nothing_silently_for_an_unknown_profile() -> None:
    with pytest.raises(ValueError):
        Settings(profile="typo")
