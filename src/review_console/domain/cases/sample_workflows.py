"""An illustrative workflow definition, so the API and demo run out of the box.

This is a SAMPLE a consumer replaces with their own vertical's states, clocks and escalation rules;
the engine owns none of it. It models a regulated complaint-handling flow: acknowledge within 2
business days, resolve within 20, escalate on breach or a case stuck awaiting the customer.
"""

from __future__ import annotations

from .kernel import CaseFinding, ClockKind
from .models import ClockSpec, WorkflowDefinition

COMPLAINT_WORKFLOW = WorkflowDefinition(
    case_type="complaint",
    states=(
        "received",
        "under_review",
        "awaiting_customer",
        "escalated",
        "resolved",
        "closed",
    ),
    initial="received",
    terminal=frozenset({"resolved", "closed"}),
    transitions=frozenset(
        {
            ("received", "under_review"),
            ("under_review", "awaiting_customer"),
            ("awaiting_customer", "under_review"),
            ("under_review", "escalated"),
            ("escalated", "under_review"),
            ("under_review", "resolved"),
            ("escalated", "resolved"),
            ("resolved", "closed"),
        }
    ),
    clocks=(
        ClockSpec(
            name="acknowledgement",
            kind=ClockKind.BUSINESS,
            duration_days=2,
            start_state="received",
            warn_ratio=0.5,
        ),
        ClockSpec(
            name="resolution",
            kind=ClockKind.BUSINESS,
            duration_days=20,
            start_state="received",
            warn_ratio=0.8,
        ),
    ),
    escalate_on=frozenset({CaseFinding.SLA_BREACH, CaseFinding.STUCK_IN_STATE}),
    stuck_after_days={"awaiting_customer": 30, "under_review": 15},
)

#: The default registry the platform ships; a deployment overrides this per vertical.
SAMPLE_DEFINITIONS: dict[str, WorkflowDefinition] = {
    COMPLAINT_WORKFLOW.case_type: COMPLAINT_WORKFLOW,
}
