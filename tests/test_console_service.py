"""The orchestrator: submit / queue, tenant partitioning, redact-before-audit, denied sign-off."""

from __future__ import annotations

from review_console.adapters.local.audit import LocalAuditAdapter
from review_console.adapters.local.review_store import LocalReviewStore
from review_console.config import Settings
from review_console.domain.console_service import ConsoleService, ReviewNotFound
from review_console.domain.kernel import Decision, Disposition, Severity
from review_console.domain.models import ReviewItem, ReviewRequest


def _console() -> tuple[ConsoleService, LocalAuditAdapter]:
    store = LocalReviewStore(Settings(profile="local"))
    audit = LocalAuditAdapter(Settings(profile="local", audit_path=":memory:"))
    return ConsoleService(store, audit), audit


def test_submit_enqueues_for_the_makers_tenant() -> None:
    console, _ = _console()
    item = console.submit(
        review_id="r1",
        maker="demo.analyst@bank.example",
        tenant="demo-bank",
        action="disburse",
        subject="Acme (FICTIONAL)",
        summary="disburse facility",
        severity=Severity.MEDIUM,
    )
    assert item.tenant == "demo-bank"
    assert [i.review_id for i in console.list_queue("demo-bank")] == ["r1"]
    # Another tenant sees an empty queue: fail-closed partition.
    assert console.list_queue("other-bank") == []


def test_submit_persists_the_effective_routing_threshold() -> None:
    console, _ = _console()
    item = console.submit(
        review_id="r1",
        maker="demo.analyst@bank.example",
        tenant="demo-bank",
        action="disburse",
        subject="Acme (FICTIONAL)",
        summary="disburse facility",
        severity=Severity.HIGH,
    )
    assert item.request.required_approvals == 2
    assert console.get("demo-bank", "r1").request.required_approvals == 2


def test_legacy_item_projects_the_effective_threshold_before_decision() -> None:
    store = LocalReviewStore(Settings(profile="local"))
    audit = LocalAuditAdapter(Settings(profile="local", audit_path=":memory:"))
    store.put(
        ReviewItem(
            request=ReviewRequest(
                review_id="legacy-r1",
                tenant="demo-bank",
                action="disburse",
                maker="demo.analyst@bank.example",
                subject="Acme (FICTIONAL)",
                summary="legacy record",
                severity=Severity.HIGH,
                required_approvals=1,
            )
        )
    )
    console = ConsoleService(store, audit)

    projected = console.get("demo-bank", "legacy-r1")
    assert projected.request.required_approvals == 2
    first = console.dispose(
        review_id="legacy-r1",
        checker="demo.approver@bank.example",
        checker_tenant="demo-bank",
        checker_groups=("group:approver",),
        disposition=Disposition.APPROVE,
        reason="first independent review",
    )
    assert first.item.request.required_approvals == 2
    assert first.item.state.value == "pending"


def test_get_across_tenant_is_not_found() -> None:
    console, _ = _console()
    console.submit(
        review_id="r1",
        maker="demo.analyst@bank.example",
        tenant="demo-bank",
        action="disburse",
        subject="X",
        summary="y",
    )
    try:
        console.get("other-bank", "r1")
    except ReviewNotFound:
        pass
    else:  # pragma: no cover
        raise AssertionError("cross-tenant get must not resolve")


def test_valid_approval_is_recorded_and_leaves_the_queue() -> None:
    console, audit = _console()
    console.submit(
        review_id="r1",
        maker="demo.analyst@bank.example",
        tenant="demo-bank",
        action="disburse",
        subject="Acme (FICTIONAL)",
        summary="disburse facility",
        severity=Severity.MEDIUM,
    )
    outcome = console.dispose(
        review_id="r1",
        checker="demo.approver@bank.example",
        checker_tenant="demo-bank",
        checker_groups=("group:analyst", "group:approver"),
        disposition=Disposition.APPROVE,
        reason="within limits",
    )
    assert outcome.allowed
    assert console.list_queue("demo-bank") == []  # approved, no longer pending
    assert audit.log.verify_chain().ok


def test_self_approval_records_a_denied_signoff_and_persists_nothing() -> None:
    console, audit = _console()
    console.submit(
        review_id="r1",
        maker="demo.approver@bank.example",
        tenant="demo-bank",
        action="disburse",
        subject="X",
        summary="y",
        severity=Severity.MEDIUM,
    )
    outcome = console.dispose(
        review_id="r1",
        checker="demo.approver@bank.example",
        checker_tenant="demo-bank",
        checker_groups=("group:approver",),
        disposition=Disposition.APPROVE,
        reason="self approve",
    )
    assert not outcome.allowed
    # The item is still pending (nothing recorded as an approval) ...
    assert console.get("demo-bank", "r1").state.value == "pending"
    # ... and the denial itself is on the WORM trail.
    records = audit.log.read_all()
    dispositions = [r for r in records if r.get("action") == "dispose"]
    assert dispositions and dispositions[-1]["decision"] == Decision.DENIED.value


def test_pii_in_reason_and_summary_is_redacted_before_the_signoff_write() -> None:
    console, audit = _console()
    console.submit(
        review_id="r1",
        maker="demo.analyst@bank.example",
        tenant="demo-bank",
        action="disburse",
        subject="Borrower NRIC S1234567D (FICTIONAL)",
        summary="NRIC S1234567D on file",
        severity=Severity.MEDIUM,
    )
    console.dispose(
        review_id="r1",
        checker="demo.approver@bank.example",
        checker_tenant="demo-bank",
        checker_groups=("group:approver",),
        disposition=Disposition.APPROVE,
        reason="Verified NRIC S1234567D against source.",
    )
    for record in audit.log.read_all():
        blob = f"{record.get('redacted_reason', '')} {record.get('redacted_summary', '')}"
        assert "S1234567D" not in blob
    assert audit.log.verify_chain().ok
