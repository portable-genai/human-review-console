"""The pure case assessment: compute every clock, flag findings, decide whether to escalate.

Given a case, its workflow definition, an ``as_of`` instant and a holiday set, this returns a
deterministic ``CaseAssessment``: the status of each SLA / regulatory clock, the findings
(breach, approaching, stuck), and whether the case must escalate to a human reviewer. No I/O.
"""

from __future__ import annotations

from datetime import date, datetime

from .clock import calendar_days_between, deadline_for
from .kernel import CaseFinding
from .models import Case, CaseAssessment, DeadlineStatus, WorkflowDefinition

# The canonical, stable order findings are reported in (most urgent first).
_FINDING_ORDER: tuple[CaseFinding, ...] = (
    CaseFinding.SLA_BREACH,
    CaseFinding.APPROACHING_DEADLINE,
    CaseFinding.STUCK_IN_STATE,
)


def assess(
    case: Case,
    *,
    definition: WorkflowDefinition,
    as_of: datetime,
    holidays: frozenset[date] = frozenset(),
) -> CaseAssessment:
    """Deterministically assess a case's clocks and state; decide escalation."""
    deadlines: list[DeadlineStatus] = []
    found: set[CaseFinding] = set()

    for spec in definition.clocks:
        anchor = case.first_entered(spec.start_state, initial=definition.initial)
        status = deadline_for(spec, anchor, as_of, holidays)
        deadlines.append(status)
        if status.breached:
            found.add(CaseFinding.SLA_BREACH)
        elif status.approaching:
            found.add(CaseFinding.APPROACHING_DEADLINE)

    # Stuck-in-state: a non-terminal case sitting in one state past its allowed dwell time.
    if not definition.is_terminal(case.state):
        limit = definition.stuck_after_days.get(case.state)
        if limit is not None:
            days_in_state = calendar_days_between(case.entered_current_at(), as_of)
            if days_in_state >= limit:
                found.add(CaseFinding.STUCK_IN_STATE)

    findings = tuple(f for f in _FINDING_ORDER if f in found)
    requires_human_review = any(f in definition.escalate_on for f in findings)

    return CaseAssessment(
        case_id=case.case_id,
        state=case.state,
        severity=case.severity,
        deadlines=tuple(deadlines),
        findings=findings,
        requires_human_review=requires_human_review,
    )
