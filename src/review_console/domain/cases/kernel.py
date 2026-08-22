"""Case-specific domain taxonomies and the case audit event.

The vertical-neutral primitives ``Severity``, ``Citation`` and ``utcnow`` are shared with the
console and imported from ``review_console.domain.kernel`` (one copy). This module adds only the
case-workflow-specific taxonomies (clock kinds, case findings, the case audit decision) and the
already-redacted case audit event. ``CaseDecision`` is DISTINCT from the console's ``Decision``
(different members: a case action can be ``ESCALATED`` / ``REJECTED``), so it keeps its own name.
Nothing here imports a web framework or a cloud SDK.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from hex_service_kit.enums import LenientStrEnum

from ..kernel import Citation, Severity, utcnow


class ClockKind(LenientStrEnum):
    """How a deadline's duration is counted."""

    CALENDAR = "calendar"  # wall-clock days, weekends and holidays included
    BUSINESS = "business"  # business days only, skipping weekends and configured holidays


class CaseFinding(LenientStrEnum):
    """What the assessment flagged about a case's clocks and state."""

    SLA_BREACH = "sla_breach"  # a deadline has passed
    APPROACHING_DEADLINE = "approaching_deadline"  # inside the warning window
    STUCK_IN_STATE = "stuck_in_state"  # in one non-terminal state longer than allowed
    ILLEGAL_TRANSITION = "illegal_transition"  # (recorded when a transition is rejected)


class CaseDecision(LenientStrEnum):
    """The audit decision recorded for a case action.

    Distinct from the console's ``Decision`` (which is ``ALLOWED`` / ``DENIED``): a case action can
    also be ``ESCALATED`` (routed to a human, never auto-executed) or ``REJECTED`` (an illegal
    transition refused), so the two enums are kept separately named and never merged.
    """

    ALLOWED = "allowed"  # the action was applied
    ESCALATED = "escalated"  # routed to a human reviewer, never auto-executed
    REJECTED = "rejected"  # an illegal transition was refused


@dataclass(frozen=True, slots=True)
class CaseAuditEvent:
    """An immutable, already-redacted record of one case action (P-04 / rule R2)."""

    action: str
    case_id: str
    tenant: str
    actor: str
    from_state: str
    to_state: str
    decision: CaseDecision
    severity: Severity
    redacted_summary: str
    findings: tuple[CaseFinding, ...] = ()
    citations: tuple[Citation, ...] = ()
    timestamp: datetime = field(default_factory=utcnow)
