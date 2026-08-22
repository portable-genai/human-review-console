"""The pure assessment: breach / approaching / stuck findings and the escalation decision."""

from __future__ import annotations

from datetime import UTC, datetime

from review_console.domain.cases.assessment import assess
from review_console.domain.cases.kernel import CaseFinding
from review_console.domain.cases.models import Transition, new_case
from review_console.domain.cases.sample_workflows import COMPLAINT_WORKFLOW

MON = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)


def _fresh_case():
    return new_case(case_id="c1", tenant="demo-bank", definition=COMPLAINT_WORKFLOW, opened_at=MON)


def test_fresh_case_has_no_findings() -> None:
    a = assess(_fresh_case(), definition=COMPLAINT_WORKFLOW, as_of=MON)
    assert a.findings == ()
    assert not a.requires_human_review


def test_breached_ack_flags_sla_breach_and_escalates() -> None:
    fri = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)  # ack (2 bd) due Wed, so breached
    a = assess(_fresh_case(), definition=COMPLAINT_WORKFLOW, as_of=fri)
    assert CaseFinding.SLA_BREACH in a.findings
    assert a.requires_human_review  # SLA_BREACH is in escalate_on


def test_approaching_deadline_does_not_escalate() -> None:
    tue = datetime(2026, 6, 2, 10, 0, tzinfo=UTC)  # 1 business day left on the 2-day ack clock
    a = assess(_fresh_case(), definition=COMPLAINT_WORKFLOW, as_of=tue)
    assert CaseFinding.APPROACHING_DEADLINE in a.findings
    # APPROACHING_DEADLINE is not in escalate_on, so no escalation.
    assert not a.requires_human_review


def test_stuck_in_state_flags_and_escalates() -> None:
    # Enter awaiting_customer at Tue 06-02, evaluate 31 calendar days later (limit is 30).
    case = new_case(case_id="c1", tenant="demo-bank", definition=COMPLAINT_WORKFLOW, opened_at=MON)
    hist = (
        Transition(1, "received", "under_review", "a", "", MON),
        Transition(
            2, "under_review", "awaiting_customer", "a", "", datetime(2026, 6, 2, 9, 0, tzinfo=UTC)
        ),
    )
    stuck_case = type(case)(
        case_id=case.case_id,
        tenant=case.tenant,
        case_type=case.case_type,
        state="awaiting_customer",
        severity=case.severity,
        opened_at=case.opened_at,
        history=hist,
    )
    as_of = datetime(2026, 7, 3, 9, 0, tzinfo=UTC)  # 31 days in awaiting_customer
    a = assess(stuck_case, definition=COMPLAINT_WORKFLOW, as_of=as_of)
    assert CaseFinding.STUCK_IN_STATE in a.findings
    assert a.requires_human_review


def test_findings_are_reported_in_canonical_order() -> None:
    # A long-overdue awaiting_customer case has both a breach and a stall; order is stable.
    case = new_case(case_id="c1", tenant="demo-bank", definition=COMPLAINT_WORKFLOW, opened_at=MON)
    hist = (
        Transition(1, "received", "under_review", "a", "", MON),
        Transition(
            2, "under_review", "awaiting_customer", "a", "", datetime(2026, 6, 2, 9, 0, tzinfo=UTC)
        ),
    )
    both = type(case)(
        case_id=case.case_id,
        tenant=case.tenant,
        case_type=case.case_type,
        state="awaiting_customer",
        severity=case.severity,
        opened_at=case.opened_at,
        history=hist,
    )
    a = assess(both, definition=COMPLAINT_WORKFLOW, as_of=datetime(2026, 7, 3, 9, 0, tzinfo=UTC))
    # SLA_BREACH always precedes STUCK_IN_STATE in the canonical order.
    assert a.findings.index(CaseFinding.SLA_BREACH) < a.findings.index(CaseFinding.STUCK_IN_STATE)
