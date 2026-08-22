#!/usr/bin/env python3
"""Bounded, executable portability proof for Hrz7.

This proof runs offline. It exercises the complete profile map, a profile-neutral deterministic
decision, the local audit chain, and the fail-fast on-prem boundary. It deliberately does not
claim a live managed deployment, a working on-prem migration, a channel swap, or full data exit.
"""

from __future__ import annotations

from datetime import UTC, datetime

from review_console.adapters.local.audit import LocalAuditAdapter
from review_console.config import (
    _BINDINGS,
    _IDENTITY_BINDINGS,
    RUNTIME_PROFILES,
    Settings,
    build_container,
)
from review_console.domain.kernel import Disposition, Severity


def _decision() -> tuple[str, str, int]:
    container = build_container(Settings(profile="local", audit_path=":memory:"))
    item = container.console.submit(
        review_id="portable-demo-review",
        maker="demo.analyst@bank.example",
        tenant="demo-bank",
        action="release_payment",
        subject="Example Bank Facility (FICTIONAL)",
        summary="Portable domain decision fixture.",
        severity=Severity.MEDIUM,
    )
    outcome = container.console.dispose(
        review_id=item.review_id,
        checker="demo.approver@bank.example",
        checker_tenant="demo-bank",
        checker_groups=("group:approver",),
        disposition=Disposition.APPROVE,
        reason="Independent review completed.",
        as_of=datetime(2026, 7, 27, 9, 0, tzinfo=UTC),
    )
    audit = container.audit
    assert isinstance(audit, LocalAuditAdapter)
    chain = audit.log.verify_chain()
    assert chain.ok
    return outcome.decision.value, outcome.item.state.value, len(audit.log.read_all())


def main() -> int:
    print("Hrz7 bounded portability proof")

    assert set(_IDENTITY_BINDINGS) == RUNTIME_PROFILES
    assert all(set(bindings) == RUNTIME_PROFILES for bindings in _BINDINGS.values())
    assert all(bindings["platform"] == bindings["gcp"] for bindings in _BINDINGS.values())
    print("PASS profile map: local, gcp, platform, and onprem are explicit for every port")

    first = _decision()
    second = _decision()
    assert first == second == ("allowed", "approved", 2)
    print("PASS deterministic seam: fresh offline stacks produce the same approved result")
    print("PASS audit seam: each run writes two events and verifies the local hash chain")

    gcp = build_container(Settings(profile="gcp"))
    platform = build_container(Settings(profile="platform"))
    assert gcp.review_store.__class__ is platform.review_store.__class__
    print("PASS managed binding: platform explicitly selects Hrz7's reviewed GCP adapters")

    onprem = build_container(Settings(profile="onprem"))
    try:
        onprem.review_store.list_all("demo-bank")
    except NotImplementedError:
        print("PASS exit boundary: the unconfigured on-prem store refuses instead of falling back")
    else:
        raise AssertionError("on-prem profile did not fail fast")

    try:
        Settings(profile="misspelled")
    except ValueError:
        print("PASS selector: an unknown profile is rejected before adapter construction")
    else:
        raise AssertionError("unknown profile did not fail closed")

    print(
        "LIMITS not proved here: live GCP behavior, a completed on-prem adapter, channel "
        "portability, cross-store export and reload, or production identity."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
