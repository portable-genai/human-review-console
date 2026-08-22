#!/usr/bin/env python3
"""Offline maker-checker demo: submit an item, show four-eyes refusing self-approval, then a
distinct approver clearing it, and print the WORM sign-off trail. Deterministic, synthetic data.

Run: ``python scripts/console_demo.py`` (writes ``console_demo.json`` for inspection).
"""

from __future__ import annotations

import json
from pathlib import Path

from hex_service_kit.serialization import to_jsonable

from review_console.adapters.local.audit import LocalAuditAdapter
from review_console.adapters.local.review_store import LocalReviewStore
from review_console.config import Settings
from review_console.domain.console_service import ConsoleService
from review_console.domain.kernel import Disposition, Severity

_MAKER = "demo.analyst@bank.example"
_APPROVER = "demo.approver@bank.example"
_APPROVER_GROUPS = ("group:analyst", "group:approver")


def main() -> int:
    store = LocalReviewStore(Settings(profile="local"))
    audit = LocalAuditAdapter(Settings(profile="local", audit_path=":memory:"))
    console = ConsoleService(store, audit)

    item = console.submit(
        review_id="demo-1",
        maker=_MAKER,
        tenant="demo-bank",
        action="disburse_facility",
        subject="Acme Holdings Pte Ltd (FICTIONAL)",
        summary="Disburse SGD 2.5m revolving facility; borrower NRIC S1234567D on file.",
        severity=Severity.HIGH,  # DEFAULT_ROUTING: high needs two distinct approvals
        sod_group="group:origination",
    )
    print(f"1. {_MAKER} submitted {item.review_id} [{item.state.value}] (high -> dual control)")

    # The maker tries to approve their own item: four-eyes refuses.
    self_try = console.dispose(
        review_id="demo-1",
        checker=_MAKER,
        checker_tenant="demo-bank",
        checker_groups=("group:analyst", "group:approver"),
        disposition=Disposition.APPROVE,
        reason="self approve",
    )
    print(f"2. {_MAKER} self-approve -> DENIED {[f.value for f in self_try.findings]}")

    # A distinct approver provides the first eye; still pending (needs two).
    first = console.dispose(
        review_id="demo-1",
        checker=_APPROVER,
        checker_tenant="demo-bank",
        checker_groups=_APPROVER_GROUPS,
        disposition=Disposition.APPROVE,
        reason="Within delegated authority.",
    )
    print(f"3. {_APPROVER} approve -> {first.item.state.value} ({first.item.approvals_count}/2)")

    # A second distinct approver clears it.
    second = console.dispose(
        review_id="demo-1",
        checker="second.approver@bank.example",
        checker_tenant="demo-bank",
        checker_groups=_APPROVER_GROUPS,
        disposition=Disposition.APPROVE,
        reason="Second review complete.",
    )
    print(f"4. second approver -> {second.item.state.value} ({second.item.approvals_count}/2)")

    chain = audit.log.verify_chain()
    print(f"5. WORM sign-off trail: {len(audit.log.read_all())} events, chain ok={chain.ok}")

    out = Path("console_demo.json")
    out.write_text(
        json.dumps(
            {
                "final_item": to_jsonable(second.item),
                "signoff_trail": audit.log.read_all(),
                "chain_ok": chain.ok,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"   wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
