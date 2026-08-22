"""Case artifact models and the consumer-supplied ``WorkflowDefinition``.

The engine owns none of the policy in a ``WorkflowDefinition``: a consumer names its own states,
the legal transitions between them, the SLA / regulatory clocks, and which findings escalate. The
engine owns the mechanics (is this transition legal? has this clock breached? does this escalate?),
which is exactly what many verticals were about to rebuild.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..kernel import Citation, Severity, utcnow
from .kernel import CaseFinding, ClockKind


@dataclass(frozen=True, slots=True)
class ClockSpec:
    """An SLA or regulatory clock: a named deadline of ``duration_days`` from a start state.

    ``warn_ratio`` is the fraction of the window that may elapse before the deadline is flagged as
    approaching (0.8 warns in the last fifth). ``kind`` selects calendar vs business-day counting.
    """

    name: str
    kind: ClockKind
    duration_days: int
    start_state: str
    warn_ratio: float = 0.8


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    """The consumer's workflow: states, legal transitions, clocks, and what escalates.

    ``transitions`` is the set of legal ``(from_state, to_state)`` edges. ``stuck_after_days`` caps
    how long a case may sit in a given non-terminal state before it is flagged ``STUCK_IN_STATE``.
    """

    case_type: str
    states: tuple[str, ...]
    initial: str
    terminal: frozenset[str]
    transitions: frozenset[tuple[str, str]]
    clocks: tuple[ClockSpec, ...] = ()
    escalate_on: frozenset[CaseFinding] = frozenset()
    stuck_after_days: dict[str, int] = field(default_factory=dict)

    def is_legal(self, from_state: str, to_state: str) -> bool:
        return (from_state, to_state) in self.transitions

    def is_terminal(self, state: str) -> bool:
        return state in self.terminal


@dataclass(frozen=True, slots=True)
class Transition:
    """One recorded state change (the full, append-only history of a case)."""

    seq: int
    from_state: str
    to_state: str
    actor: str
    reason: str
    at: datetime


@dataclass(frozen=True, slots=True)
class Case:
    """A live case: its current state, severity, full transition history, and free attributes."""

    case_id: str
    tenant: str
    case_type: str
    state: str
    severity: Severity
    opened_at: datetime
    history: tuple[Transition, ...] = ()
    attributes: dict[str, str] = field(default_factory=dict)
    citations: tuple[Citation, ...] = ()

    @property
    def next_seq(self) -> int:
        return len(self.history) + 1

    def entered_current_at(self) -> datetime:
        """When the case entered its current state (the last transition, else opened_at)."""
        return self.history[-1].at if self.history else self.opened_at

    def first_entered(self, state: str, *, initial: str) -> datetime | None:
        """When the case first entered ``state`` (opened_at if it is the initial state)."""
        if state == initial:
            return self.opened_at
        for t in self.history:
            if t.to_state == state:
                return t.at
        return None


@dataclass(frozen=True, slots=True)
class DeadlineStatus:
    """The computed status of one clock against an ``as_of`` instant."""

    clock: str
    kind: str
    due_at: datetime | None
    remaining_days: int
    breached: bool
    approaching: bool


@dataclass(frozen=True, slots=True)
class CaseAssessment:
    """The deterministic assessment of a case: deadlines, findings, and the escalation decision."""

    case_id: str
    state: str
    severity: Severity
    deadlines: tuple[DeadlineStatus, ...]
    findings: tuple[CaseFinding, ...]
    requires_human_review: bool

    @classmethod
    def empty(cls, case: Case) -> CaseAssessment:
        return cls(
            case_id=case.case_id,
            state=case.state,
            severity=case.severity,
            deadlines=(),
            findings=(),
            requires_human_review=False,
        )


def new_case(
    *,
    case_id: str,
    tenant: str,
    definition: WorkflowDefinition,
    severity: Severity = Severity.MEDIUM,
    opened_at: datetime | None = None,
    attributes: dict[str, str] | None = None,
    citations: tuple[Citation, ...] = (),
) -> Case:
    """Open a new case in the definition's initial state."""
    return Case(
        case_id=case_id,
        tenant=tenant,
        case_type=definition.case_type,
        state=definition.initial,
        severity=severity,
        opened_at=opened_at or utcnow(),
        attributes=dict(attributes or {}),
        citations=citations,
    )
