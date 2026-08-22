"""The deterministic maker-checker engine: four-eyes, segregation of duties, N-eyes routing.

This is the console's consequential decision, and by the deterministic-domain-service discipline
it is pure stdlib and replayable: the same (item, checker, policy) always yields the same
outcome, an auditor can re-run it, and no LLM is anywhere near it. The engine decides *whether a
checker may dispose of an item* and *what the item becomes*; it does no I/O. Persistence and the
WORM audit write live in the orchestrator.

The load-bearing rule is ``SELF_APPROVAL``: principle P-06 ("escalates softly to a human, never
auto-executes") made mechanical, so a maker can never approve their own work. Every eligibility
check fails closed: any finding denies the disposition and records nothing as an approval.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .kernel import Decision, Disposition, EligibilityFinding, ReviewState, Severity
from .models import Approval, ReviewDecision, ReviewItem

#: The entitlement a principal must hold to act as a checker (an Hrz3 registry scope in prod).
APPROVER_GROUP = "group:approver"


@dataclass(frozen=True, slots=True)
class RoutingPolicy:
    """Consumer-supplied routing: how many distinct approvals an action needs, and whether to
    enforce segregation of duties. The console ships a neutral default and owns no vertical policy.
    """

    min_approvals_by_severity: dict[Severity, int] = field(default_factory=dict)
    enforce_sod: bool = True
    approver_group: str = APPROVER_GROUP

    def required_approvals(self, *, severity: Severity, requested: int) -> int:
        """The number of distinct approvals required: the stricter of the request and the policy."""
        floor = self.min_approvals_by_severity.get(severity, 1)
        return max(1, requested, floor)

    @staticmethod
    def from_mapping(raw: Mapping[str, Any]) -> RoutingPolicy:
        """Build a routing policy from the parsed ``policy.routing`` configuration section.

        Every key is optional and falls back to the reference default, so a partial institution
        policy file changes only what it names. Unknown severities are rejected rather than
        silently ignored: a typo in a compliance-owned floor must fail loudly at load.
        """
        defaults = DEFAULT_ROUTING
        floors_raw = raw.get("min_approvals_by_severity")
        if floors_raw is None:
            floors = dict(defaults.min_approvals_by_severity)
        elif isinstance(floors_raw, Mapping):
            floors = {Severity(str(k)): int(v) for k, v in floors_raw.items()}
        else:
            raise ValueError("policy.routing.min_approvals_by_severity must be a mapping")
        if any(count < 1 for count in floors.values()):
            raise ValueError("policy.routing severity floors must be at least 1")
        enforce_sod = raw.get("enforce_sod")
        approver_group = raw.get("approver_group")
        return RoutingPolicy(
            min_approvals_by_severity=floors,
            enforce_sod=defaults.enforce_sod if enforce_sod is None else bool(enforce_sod),
            approver_group=(defaults.approver_group if not approver_group else str(approver_group)),
        )


#: A sensible default (critical / high actions need dual control). Consumers override per vertical.
#: ``config/policy.json`` ships exactly these numbers, so the configured policy reproduces the
#: reference behavior byte for byte and an institution only edits what it wants to change.
DEFAULT_ROUTING = RoutingPolicy(
    min_approvals_by_severity={
        Severity.CRITICAL: 2,
        Severity.HIGH: 2,
        Severity.MEDIUM: 1,
        Severity.LOW: 1,
    },
)


@dataclass(frozen=True, slots=True)
class DispositionOutcome:
    """The pure result of one disposition attempt: the (possibly unchanged) item and the verdict.

    ``decision`` is ``DENIED`` with a non-empty ``findings`` tuple when an eligibility rule fails
    closed (the item is returned unchanged), or ``ALLOWED`` when the disposition was applied.
    """

    item: ReviewItem
    decision: Decision
    findings: tuple[EligibilityFinding, ...] = ()

    @property
    def allowed(self) -> bool:
        return self.decision is Decision.ALLOWED


class AlreadyResolved(ValueError):
    """Raised when a disposition is attempted on an item that is already terminal (HTTP 409)."""


class MakerCheckerService:
    """Pure four-eyes / SoD / N-eyes engine. Inject a ``RoutingPolicy``; call ``dispose``."""

    def __init__(self, policy: RoutingPolicy = DEFAULT_ROUTING) -> None:
        self._policy = policy

    def check_eligibility(
        self,
        item: ReviewItem,
        *,
        checker: str,
        checker_tenant: str,
        checker_groups: tuple[str, ...],
    ) -> tuple[EligibilityFinding, ...]:
        """Every reason this checker may NOT act on this item. Empty means eligible.

        All findings are collected (not short-circuited) so a reviewer sees every reason at once;
        any single finding is a fail-closed denial.
        """
        findings: list[EligibilityFinding] = []
        req = item.request

        # Cross-tenant isolation: a checker only ever sees or acts within their own tenant.
        if checker_tenant != req.tenant:
            findings.append(EligibilityFinding.WRONG_TENANT)
        # Four-eyes (P-06): the maker can never be the checker, however the request is shaped.
        if checker == req.maker:
            findings.append(EligibilityFinding.SELF_APPROVAL)
        # Segregation of duties: a checker in the maker's SoD group is conflicted.
        if self._policy.enforce_sod and req.sod_group and req.sod_group in checker_groups:
            findings.append(EligibilityFinding.SEGREGATION_OF_DUTIES)
        # Least privilege: only a holder of the approver entitlement may dispose.
        if self._policy.approver_group not in checker_groups:
            findings.append(EligibilityFinding.INSUFFICIENT_ROLE)
        # N-eyes distinctness: an approver may not approve the same item twice.
        if checker in item.approvers:
            findings.append(EligibilityFinding.DUPLICATE_APPROVER)

        return tuple(findings)

    def required_approvals(self, item: ReviewItem) -> int:
        return self._policy.required_approvals(
            severity=item.request.severity, requested=item.request.required_approvals
        )

    def dispose(
        self, item: ReviewItem, decision: ReviewDecision, *, as_of: datetime | None = None
    ) -> DispositionOutcome:
        """Apply a checker's disposition, fail-closed. Pure: returns a new item, does no I/O.

        ``as_of`` is the timestamp recorded on an approval, passed in so the result is reproducible
        and testable; it defaults to the decision's own ``decided_at``.
        """
        if item.is_terminal:
            raise AlreadyResolved(
                f"review {item.review_id} is already {item.state.value}; it cannot be re-disposed"
            )

        findings = self.check_eligibility(
            item,
            checker=decision.checker,
            checker_tenant=decision.checker_tenant,
            checker_groups=decision.checker_groups,
        )
        if findings:
            return DispositionOutcome(item=item, decision=Decision.DENIED, findings=findings)

        stamp = as_of if as_of is not None else decision.decided_at

        if decision.disposition is Disposition.APPROVE:
            approval = Approval(checker=decision.checker, reason=decision.reason, at=stamp)
            new_count = item.approvals_count + 1
            required = self.required_approvals(item)
            new_state = ReviewState.APPROVED if new_count >= required else ReviewState.PENDING
            new_item = item.with_approval(approval, state=new_state)
        elif decision.disposition is Disposition.REJECT:
            new_item = item.resolved(state=ReviewState.REJECTED, reason=decision.reason)
        else:  # AMEND
            new_item = item.resolved(state=ReviewState.AMENDED, reason=decision.reason)

        return DispositionOutcome(item=new_item, decision=Decision.ALLOWED, findings=())
