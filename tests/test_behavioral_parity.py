"""Behavioral parity at the Hrz7 profile seam.

Managed adapters need live cloud services for I/O, so the offline contract proves what can be
proved without inventing integration state: the pure decision is profile-neutral, the local
binding is deterministic, the platform profile is an explicit reviewed managed binding, and the
on-prem profile refuses rather than silently using another adapter.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from review_console.config import _BINDINGS, Settings, build_container
from review_console.domain.kernel import Disposition, Severity


def _exercise_local() -> tuple[str, tuple[str, ...], str]:
    container = build_container(Settings(profile="local", audit_path=":memory:"))
    item = container.console.submit(
        review_id="parity-review",
        maker="demo.analyst@bank.example",
        tenant="demo-bank",
        action="release_payment",
        subject="Example Bank Facility (FICTIONAL)",
        summary="Offline profile parity fixture.",
        severity=Severity.MEDIUM,
    )
    result = container.console.dispose(
        review_id=item.review_id,
        checker="demo.approver@bank.example",
        checker_tenant="demo-bank",
        checker_groups=("group:approver",),
        disposition=Disposition.APPROVE,
        reason="Independent review completed.",
        as_of=datetime(2026, 7, 27, 9, 0, tzinfo=UTC),
    )
    return result.decision.value, tuple(f.value for f in result.findings), result.item.state.value


def test_local_decision_is_deterministic_across_fresh_containers() -> None:
    assert _exercise_local() == _exercise_local() == ("allowed", (), "approved")


def test_platform_profile_is_an_explicit_managed_binding() -> None:
    assert all(bindings["platform"] == bindings["gcp"] for bindings in _BINDINGS.values())
    container = build_container(Settings(profile="platform"))
    assert container.review_store.__class__.__name__ == "FirestoreReviewStore"


def test_onprem_profile_fails_before_any_fallback_io() -> None:
    container = build_container(Settings(profile="onprem"))
    with pytest.raises(NotImplementedError):
        container.review_store.list_all("demo-bank")
