"""The deterministic maker-checker engine: four-eyes, SoD, N-eyes, roles, tenant, determinism.

These tests ARE the spec. Every eligibility finding gets a test that constructs the minimal input
triggering exactly it; the self-approval case is the load-bearing one (principle P-06).
"""

from __future__ import annotations

from datetime import UTC, datetime

from review_console.domain.kernel import (
    Decision,
    Disposition,
    EligibilityFinding,
    ReviewState,
    Severity,
)
from review_console.domain.maker_checker_service import (
    DEFAULT_ROUTING,
    AlreadyResolved,
    MakerCheckerService,
    RoutingPolicy,
)
from review_console.domain.models import ReviewDecision, ReviewItem, ReviewRequest

_AS_OF = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
_APPROVER_GROUPS = ("group:analyst", "group:approver")


def _item(
    *,
    maker: str = "demo.analyst@bank.example",
    tenant: str = "demo-bank",
    severity: Severity = Severity.MEDIUM,
    required_approvals: int = 1,
    sod_group: str = "",
    approvals: tuple = (),
) -> ReviewItem:
    request = ReviewRequest(
        review_id="rev-1",
        tenant=tenant,
        action="disburse",
        maker=maker,
        subject="Acme (FICTIONAL)",
        summary="disburse facility",
        severity=severity,
        required_approvals=required_approvals,
        sod_group=sod_group,
    )
    return ReviewItem(request=request, approvals=approvals)


def _decide(
    *,
    checker: str = "demo.approver@bank.example",
    checker_tenant: str = "demo-bank",
    groups: tuple = _APPROVER_GROUPS,
    disposition: Disposition = Disposition.APPROVE,
    reason: str = "ok",
) -> ReviewDecision:
    return ReviewDecision(
        checker=checker,
        checker_tenant=checker_tenant,
        checker_groups=groups,
        disposition=disposition,
        reason=reason,
        decided_at=_AS_OF,
    )


def test_valid_approval_of_a_medium_item_becomes_approved() -> None:
    engine = MakerCheckerService()
    outcome = engine.dispose(_item(), _decide(), as_of=_AS_OF)
    assert outcome.allowed
    assert outcome.decision is Decision.ALLOWED
    assert outcome.item.state is ReviewState.APPROVED
    assert outcome.item.approvers == ("demo.approver@bank.example",)


def test_self_approval_is_denied_fail_closed() -> None:
    engine = MakerCheckerService()
    # The maker IS the checker: the four-eyes breach, no matter the request shape.
    outcome = engine.dispose(
        _item(maker="demo.approver@bank.example"),
        _decide(checker="demo.approver@bank.example"),
        as_of=_AS_OF,
    )
    assert not outcome.allowed
    assert outcome.decision is Decision.DENIED
    assert EligibilityFinding.SELF_APPROVAL in outcome.findings
    # Nothing is recorded as an approval; the item is returned unchanged and still pending.
    assert outcome.item.state is ReviewState.PENDING
    assert outcome.item.approvals_count == 0


def test_cross_tenant_checker_is_denied() -> None:
    engine = MakerCheckerService()
    outcome = engine.dispose(
        _item(tenant="demo-bank"),
        _decide(checker="user@other-tenant.example", checker_tenant="other-bank"),
        as_of=_AS_OF,
    )
    assert not outcome.allowed
    assert EligibilityFinding.WRONG_TENANT in outcome.findings


def test_checker_without_approver_role_is_denied() -> None:
    engine = MakerCheckerService()
    outcome = engine.dispose(
        _item(maker="demo.maker@bank.example"),
        _decide(checker="demo.analyst@bank.example", groups=("group:analyst", "group:risk")),
        as_of=_AS_OF,
    )
    assert not outcome.allowed
    assert EligibilityFinding.INSUFFICIENT_ROLE in outcome.findings


def test_segregation_of_duties_breach_is_denied() -> None:
    engine = MakerCheckerService()
    outcome = engine.dispose(
        _item(sod_group="group:risk"),
        _decide(groups=("group:analyst", "group:risk", "group:approver")),
        as_of=_AS_OF,
    )
    assert not outcome.allowed
    assert EligibilityFinding.SEGREGATION_OF_DUTIES in outcome.findings


def test_sod_not_enforced_when_policy_disables_it() -> None:
    engine = MakerCheckerService(RoutingPolicy(enforce_sod=False))
    outcome = engine.dispose(
        _item(sod_group="group:risk"),
        _decide(groups=("group:risk", "group:approver")),
        as_of=_AS_OF,
    )
    assert outcome.allowed


def test_dual_control_needs_two_distinct_approvers() -> None:
    engine = MakerCheckerService()  # DEFAULT_ROUTING: HIGH needs 2 approvals
    item = _item(severity=Severity.HIGH)

    first = engine.dispose(item, _decide(checker="demo.approver@bank.example"), as_of=_AS_OF)
    assert first.allowed
    # One of two approvals collected: still pending, not yet executable.
    assert first.item.state is ReviewState.PENDING
    assert first.item.approvals_count == 1

    second = engine.dispose(
        first.item, _decide(checker="second.approver@bank.example"), as_of=_AS_OF
    )
    assert second.allowed
    assert second.item.state is ReviewState.APPROVED
    assert second.item.approvals_count == 2


def test_same_approver_cannot_satisfy_dual_control_twice() -> None:
    engine = MakerCheckerService()
    item = _item(severity=Severity.HIGH)
    first = engine.dispose(item, _decide(checker="demo.approver@bank.example"), as_of=_AS_OF)
    # The SAME approver tries to provide the second eye.
    second = engine.dispose(first.item, _decide(checker="demo.approver@bank.example"), as_of=_AS_OF)
    assert not second.allowed
    assert EligibilityFinding.DUPLICATE_APPROVER in second.findings
    assert first.item.state is ReviewState.PENDING


def test_reject_is_terminal_and_allowed() -> None:
    engine = MakerCheckerService()
    outcome = engine.dispose(_item(), _decide(disposition=Disposition.REJECT), as_of=_AS_OF)
    assert outcome.allowed
    assert outcome.item.state is ReviewState.REJECTED


def test_amend_sends_back_to_the_maker() -> None:
    engine = MakerCheckerService()
    outcome = engine.dispose(_item(), _decide(disposition=Disposition.AMEND), as_of=_AS_OF)
    assert outcome.allowed
    assert outcome.item.state is ReviewState.AMENDED


def test_disposing_a_terminal_item_raises() -> None:
    engine = MakerCheckerService()
    rejected = engine.dispose(_item(), _decide(disposition=Disposition.REJECT), as_of=_AS_OF).item
    try:
        engine.dispose(rejected, _decide(), as_of=_AS_OF)
    except AlreadyResolved:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected AlreadyResolved on a terminal item")


def test_decision_is_deterministic() -> None:
    engine = MakerCheckerService()
    # Same input twice -> identical output (the engine reads no clock and no randomness of its own;
    # the item's submitted_at is fixed by reusing one item, so any drift would be the engine's).
    item = _item()
    decision = _decide()
    a = engine.dispose(item, decision, as_of=_AS_OF)
    b = engine.dispose(item, decision, as_of=_AS_OF)
    assert a == b


def test_required_approvals_is_stricter_of_request_and_policy() -> None:
    engine = MakerCheckerService(DEFAULT_ROUTING)
    # LOW severity floors at 1, but a request may demand more.
    assert engine.required_approvals(_item(severity=Severity.LOW, required_approvals=3)) == 3
    # CRITICAL severity floors at 2 even if the request asked for 1.
    assert engine.required_approvals(_item(severity=Severity.CRITICAL, required_approvals=1)) == 2
