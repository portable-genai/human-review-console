"""The case-workflow orchestrator: open a case, transition it, evaluate its clocks, escalate.

It wires the pure engines (the state machine, the clock maths, the assessment) to the storage,
timer, event and WORM-audit ports. It redacts before every audit write, records one immutable
audit event per action, schedules a deadline timer per clock, and publishes a content-free
lifecycle event. A case that breaches or stalls escalates SOFTLY to a human via the review-router
seam (in-process to the console); the engine never auto-executes a state change on a consumer's
behalf.

The engine owns no vertical policy: it is constructed with a registry of consumer-supplied
``WorkflowDefinition``s keyed by case type.
"""

from __future__ import annotations

from datetime import date, datetime

from pii_kit import redact

from ...ports.audit import AuditSinkPort
from ...ports.case_store import CaseStorePort
from ...ports.events import EventPublisherPort
from ...ports.review_router import ReviewRouterPort
from ...ports.timers import TimerPort
from ..kernel import Citation, Severity, utcnow
from ..pii import PII_PATTERNS
from .assessment import assess
from .clock import deadline_for
from .kernel import CaseAuditEvent, CaseDecision, CaseFinding
from .models import Case, CaseAssessment, WorkflowDefinition, new_case
from .state_machine import IllegalTransition, transition


class UnknownWorkflow(KeyError):
    """Raised when a case type has no registered workflow definition."""


class CaseNotFound(LookupError):
    """Raised when a case id does not exist for the caller's tenant (indistinguishable from a
    cross-tenant hit, so the API returns 404 either way and never confirms another tenant's ids).
    """


class CaseWorkflowService:
    """Open / transition / evaluate cases, with deterministic clocks and a WORM audit trail."""

    def __init__(
        self,
        store: CaseStorePort,
        audit: AuditSinkPort,
        *,
        definitions: dict[str, WorkflowDefinition],
        events: EventPublisherPort | None = None,
        timers: TimerPort | None = None,
        review_router: ReviewRouterPort | None = None,
        holidays: frozenset[date] = frozenset(),
    ) -> None:
        self._store = store
        self._audit = audit
        self._definitions = definitions
        self._events = events
        self._timers = timers
        self._review_router = review_router
        self._holidays = holidays

    def _definition(self, case_type: str) -> WorkflowDefinition:
        try:
            return self._definitions[case_type]
        except KeyError as exc:
            raise UnknownWorkflow(case_type) from exc

    def open_case(
        self,
        *,
        case_id: str,
        tenant: str,
        case_type: str,
        actor: str,
        severity: Severity = Severity.MEDIUM,
        attributes: dict[str, str] | None = None,
        summary: str = "",
        as_of: datetime | None = None,
        citations: tuple[Citation, ...] = (),
    ) -> Case:
        """Open a case in the workflow's initial state, scheduling its clocks."""
        definition = self._definition(case_type)
        case = new_case(
            case_id=case_id,
            tenant=tenant,
            definition=definition,
            severity=severity,
            opened_at=as_of,
            attributes=attributes,
            citations=citations,
        )
        self._store.put(case)
        self._schedule_clocks(case, definition, as_of=case.opened_at)
        self._emit("case.opened", case)
        self._record(
            case,
            action="open",
            actor=actor,
            from_state="",
            to_state=case.state,
            decision=CaseDecision.ALLOWED,
            summary=summary or case_type,
            findings=(),
        )
        return case

    def transition_case(
        self,
        *,
        case_id: str,
        tenant: str,
        to_state: str,
        actor: str,
        reason: str,
        as_of: datetime | None = None,
    ) -> Case:
        """Advance a case to ``to_state`` (illegal edges are refused with a REJECTED audit)."""
        stamp = as_of or utcnow()
        case = self._load(tenant, case_id)
        definition = self._definition(case.case_type)
        try:
            moved = transition(
                case, to_state, actor=actor, reason=reason, as_of=stamp, definition=definition
            )
        except IllegalTransition:
            self._record(
                case,
                action="transition",
                actor=actor,
                from_state=case.state,
                to_state=to_state,
                decision=CaseDecision.REJECTED,
                summary=reason,
                findings=(),
            )
            raise

        self._store.put(moved)
        if definition.is_terminal(moved.state):
            self._cancel_clocks(moved, definition)
        self._emit("case.transitioned", moved)
        self._record(
            moved,
            action="transition",
            actor=actor,
            from_state=case.state,
            to_state=moved.state,
            decision=CaseDecision.ALLOWED,
            summary=reason,
            findings=(),
        )
        return moved

    def evaluate_case(
        self, *, case_id: str, tenant: str, actor: str = "system", as_of: datetime | None = None
    ) -> CaseAssessment:
        """Assess a case's clocks and state; escalate softly to a human on a breach or a stall."""
        stamp = as_of or utcnow()
        case = self._load(tenant, case_id)
        definition = self._definition(case.case_type)
        assessment = assess(case, definition=definition, as_of=stamp, holidays=self._holidays)

        decision = (
            CaseDecision.ESCALATED if assessment.requires_human_review else CaseDecision.ALLOWED
        )
        self._record(
            case,
            action="evaluate",
            actor=actor,
            from_state=case.state,
            to_state=case.state,
            decision=decision,
            summary=case.case_type,
            findings=assessment.findings,
        )
        if assessment.requires_human_review:
            # Soft escalation (rule R8): emit the lifecycle event AND route the case to the review
            # console for a human to dispose. The engine records and hands off; it never
            # auto-executes.
            self._emit("case.escalated", case)
            if self._review_router is not None:
                maker = case.history[-1].actor if case.history else "case-engine@system"
                self._review_router.route(case, assessment, maker=maker)
        return assessment

    def get(self, tenant: str, case_id: str) -> Case:
        return self._load(tenant, case_id)

    def list_cases(self, tenant: str) -> list[Case]:
        return self._store.list_by_tenant(tenant)

    # ---- internals -------------------------------------------------------------------------

    def _load(self, tenant: str, case_id: str) -> Case:
        case = self._store.get(tenant, case_id)
        if case is None:
            raise CaseNotFound(case_id)
        return case

    def _schedule_clocks(
        self, case: Case, definition: WorkflowDefinition, *, as_of: datetime
    ) -> None:
        if self._timers is None:
            return
        for spec in definition.clocks:
            anchor = case.first_entered(spec.start_state, initial=definition.initial)
            status = deadline_for(spec, anchor, as_of, self._holidays)
            if status.due_at is not None:
                self._timers.schedule(
                    tenant=case.tenant, case_id=case.case_id, clock=spec.name, fire_at=status.due_at
                )

    def _cancel_clocks(self, case: Case, definition: WorkflowDefinition) -> None:
        if self._timers is None:
            return
        for spec in definition.clocks:
            self._timers.cancel(tenant=case.tenant, case_id=case.case_id, clock=spec.name)

    def _emit(self, event_type: str, case: Case) -> None:
        if self._events is None:
            return
        self._events.publish(
            event_type=event_type,
            tenant=case.tenant,
            case_id=case.case_id,
            attributes={"state": case.state, "severity": case.severity.value},
        )

    def _record(
        self,
        case: Case,
        *,
        action: str,
        actor: str,
        from_state: str,
        to_state: str,
        decision: CaseDecision,
        summary: str,
        findings: tuple[CaseFinding, ...],
    ) -> None:
        """Write one already-redacted case audit event to the WORM sink."""
        attr_blob = " ".join(f"{k}={v}" for k, v in sorted(case.attributes.items()))
        self._audit.record(
            CaseAuditEvent(
                action=action,
                case_id=case.case_id,
                tenant=case.tenant,
                actor=actor,
                from_state=from_state,
                to_state=to_state,
                decision=decision,
                severity=case.severity,
                # Redact BEFORE the write: no raw identifier reaches the audit record.
                redacted_summary=redact(f"{summary} :: {attr_blob}", PII_PATTERNS),
                findings=findings,
                citations=case.citations,
            )
        )


__all__ = ["CaseNotFound", "CaseWorkflowService", "IllegalTransition", "UnknownWorkflow"]
