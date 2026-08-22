"""Prove the eval metrics are not structurally falsely green (the C4 / E2 lesson).

Two safety metrics guard this repo, and a metric that cannot go red is worse than none: it reports
success unconditionally. We prove each can distinguish a good world from a broken one.
"""

from __future__ import annotations

from datetime import UTC, datetime

from agent_eval_kit import assert_can_go_red
from pii_kit import pack_leak, redact

from review_console.domain.kernel import Disposition, Severity
from review_console.domain.maker_checker_service import MakerCheckerService
from review_console.domain.models import ReviewDecision, ReviewItem, ReviewRequest
from review_console.domain.pii import PII_PATTERNS

_AS_OF = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


def _item(maker: str) -> ReviewItem:
    return ReviewItem(
        request=ReviewRequest(
            review_id="r",
            tenant="demo-bank",
            action="disburse",
            maker=maker,
            subject="X",
            summary="y",
            severity=Severity.MEDIUM,
        )
    )


def _four_eyes_holds(maker: str) -> float:
    """1.0 iff a same-person approval by ``maker`` (as both maker and checker) is DENIED."""
    engine = MakerCheckerService()
    decision = ReviewDecision(
        checker=maker,
        checker_tenant="demo-bank",
        checker_groups=("group:approver",),
        disposition=Disposition.APPROVE,
        reason="ok",
        decided_at=_AS_OF,
    )
    outcome = engine.dispose(_item(maker), decision, as_of=_AS_OF)
    return 0.0 if outcome.allowed else 1.0


def test_four_eyes_integrity_can_go_red() -> None:
    # green: a real maker/checker collision is correctly denied (score 1.0).
    # red: a "fixed" world where check_eligibility never fires would ALLOW it (score 0.0).
    assert_can_go_red(
        lambda allowed: 0.0 if allowed else 1.0,
        green=False,  # the engine denied the self-approval
        red=True,  # a broken engine that allowed it
        threshold=0.99,
        metric="four_eyes_integrity",
    )
    # And the real engine is on the green side.
    assert _four_eyes_holds("demo.approver@bank.example") == 1.0


_RAW = "Verified borrower NRIC S1234567D on file"


def _pii_safety(text: str) -> float:
    return 0.0 if pack_leak(text, PII_PATTERNS) else 1.0


def test_pii_safety_can_go_red() -> None:
    assert_can_go_red(
        _pii_safety,
        green=redact(_RAW, PII_PATTERNS),  # redaction on: the NRIC is masked
        red=_RAW,  # redaction off (the mutant): the raw NRIC survives
        threshold=0.99,
        metric="pii_safety",
    )
