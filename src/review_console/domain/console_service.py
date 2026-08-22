"""The review-console orchestrator: submit an item, list a tenant's queue, dispose with sign-off.

It wires the pure ``MakerCheckerService`` to the storage and WORM-audit ports, redacts every
reason and summary BEFORE the audit write (R1 / P-04), and records one immutable sign-off event
for every disposition attempt, allowed or denied, so the trail proves who approved (or was
refused approval of) what and when.

The console never auto-executes the underlying action. It records the human's sign-off and
returns the outcome; the consuming vertical acts on an ``APPROVED`` item. That is P-06 with a
system enforcer instead of a per-repo boolean.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from pii_kit import redact

from ..ports.audit import AuditSinkPort
from ..ports.review_store import ReviewStorePort
from .kernel import (
    Citation,
    Decision,
    Disposition,
    EligibilityFinding,
    Severity,
    SignOffEvent,
    utcnow,
)
from .maker_checker_service import (
    DEFAULT_ROUTING,
    AlreadyResolved,
    DispositionOutcome,
    MakerCheckerService,
    RoutingPolicy,
)
from .models import ReviewDecision, ReviewItem, ReviewRequest
from .pii import PII_PATTERNS


class ReviewNotFound(LookupError):
    """Raised when a review id does not exist for the caller's tenant (indistinguishable from a
    cross-tenant hit, so the API returns 404 either way and never confirms another tenant's ids).
    """


class ConsoleService:
    """Submit, queue and dispose reviews, with fail-closed eligibility and a WORM sign-off trail."""

    def __init__(
        self,
        store: ReviewStorePort,
        audit: AuditSinkPort,
        *,
        policy: RoutingPolicy = DEFAULT_ROUTING,
    ) -> None:
        self._store = store
        self._audit = audit
        self._engine = MakerCheckerService(policy)

    def submit(
        self,
        *,
        review_id: str,
        maker: str,
        tenant: str,
        action: str,
        subject: str,
        summary: str,
        severity: Severity = Severity.MEDIUM,
        required_approvals: int = 1,
        sod_group: str = "",
        case_ref: str = "",
        citations: tuple[Citation, ...] = (),
        source_key: str = "",
    ) -> ReviewItem:
        """Enqueue an item for review. ``maker`` and ``tenant`` come from the verified principal."""
        item = self._new_item(
            review_id=review_id,
            maker=maker,
            tenant=tenant,
            action=action,
            subject=subject,
            summary=summary,
            severity=severity,
            required_approvals=required_approvals,
            sod_group=sod_group,
            case_ref=case_ref,
            citations=citations,
            source_key=source_key,
        )
        self._store.put(item)
        self._record_submission(item)
        return item

    def submit_idempotent(
        self,
        *,
        review_id: str,
        maker: str,
        tenant: str,
        action: str,
        subject: str,
        summary: str,
        severity: Severity = Severity.MEDIUM,
        required_approvals: int = 1,
        sod_group: str = "",
        case_ref: str = "",
        citations: tuple[Citation, ...] = (),
        source_key: str = "",
    ) -> ReviewItem:
        """Submit a trusted producer's review exactly once per tenant/source key."""
        item = self._new_item(
            review_id=review_id,
            maker=maker,
            tenant=tenant,
            action=action,
            subject=subject,
            summary=summary,
            severity=severity,
            required_approvals=required_approvals,
            sod_group=sod_group,
            case_ref=case_ref,
            citations=citations,
            source_key=source_key,
        )
        persisted, created = self._store.put_if_absent_by_source_key(item)
        persisted = self._with_effective_routing(persisted)
        if created:
            self._record_submission(persisted)
        return persisted

    def _new_item(
        self,
        *,
        review_id: str,
        maker: str,
        tenant: str,
        action: str,
        subject: str,
        summary: str,
        severity: Severity,
        required_approvals: int,
        sod_group: str,
        case_ref: str,
        citations: tuple[Citation, ...],
        source_key: str,
    ) -> ReviewItem:
        request = ReviewRequest(
            review_id=review_id,
            tenant=tenant,
            action=action,
            maker=maker,
            subject=subject,
            summary=summary,
            severity=severity,
            required_approvals=required_approvals,
            sod_group=sod_group,
            case_ref=case_ref,
            citations=citations,
            source_key=source_key,
        )
        item = ReviewItem(request=request)
        return self._with_effective_routing(item)

    def _with_effective_routing(self, item: ReviewItem) -> ReviewItem:
        """Project the active routing floor into evidence, including legacy stored items."""
        effective_approvals = self._engine.required_approvals(item)
        if effective_approvals != item.request.required_approvals:
            item = replace(
                item,
                request=replace(item.request, required_approvals=effective_approvals),
            )
        return item

    def _record_submission(self, item: ReviewItem) -> None:
        self._record(
            item,
            action="submit",
            checker="",
            disposition=Disposition.AMEND,  # a submit is not a disposition; recorded as an event
            decision=Decision.ALLOWED,
            reason="submitted for review",
            findings=(),
        )

    def get_by_source_key(self, tenant: str, source_key: str) -> ReviewItem | None:
        """Find an S2S submission without relaxing tenant isolation."""
        return self._store.find_by_source_key(tenant, source_key)

    def list_queue(self, tenant: str) -> list[ReviewItem]:
        """The pending review queue for ``tenant`` only."""
        return [self._with_effective_routing(item) for item in self._store.list_pending(tenant)]

    def list_all(self, tenant: str) -> list[ReviewItem]:
        return [self._with_effective_routing(item) for item in self._store.list_all(tenant)]

    def get(self, tenant: str, review_id: str) -> ReviewItem:
        item = self._store.get(tenant, review_id)
        if item is None:
            raise ReviewNotFound(review_id)
        return self._with_effective_routing(item)

    def dispose(
        self,
        *,
        review_id: str,
        checker: str,
        checker_tenant: str,
        checker_groups: tuple[str, ...],
        disposition: Disposition,
        reason: str,
        amendments: tuple[str, ...] = (),
        as_of: datetime | None = None,
    ) -> DispositionOutcome:
        """Apply a checker's disposition. Records a sign-off for the attempt (allowed or denied).

        Fail-closed: an ineligible checker (self-approval, wrong tenant, missing role, SoD breach,
        duplicate approver) yields a ``DENIED`` outcome, nothing is persisted as an approval, and
        the denial itself is written to the WORM trail.
        """
        # Load within the checker's own tenant: a cross-tenant id simply does not resolve.
        item = self._store.get(checker_tenant, review_id)
        if item is None:
            raise ReviewNotFound(review_id)
        item = self._with_effective_routing(item)

        decision = ReviewDecision(
            checker=checker,
            checker_tenant=checker_tenant,
            checker_groups=checker_groups,
            disposition=disposition,
            reason=reason,
            amendments=amendments,
            decided_at=as_of or utcnow(),
        )
        outcome = self._engine.dispose(item, decision, as_of=as_of)

        if outcome.allowed:
            self._store.put(outcome.item)

        self._record(
            outcome.item,
            action="dispose",
            checker=checker,
            disposition=disposition,
            decision=outcome.decision,
            reason=reason,
            findings=outcome.findings,
        )
        return outcome

    def _record(
        self,
        item: ReviewItem,
        *,
        action: str,
        checker: str,
        disposition: Disposition,
        decision: Decision,
        reason: str,
        findings: tuple[EligibilityFinding, ...],
    ) -> None:
        """Write one already-redacted sign-off event to the WORM sink."""
        req = item.request
        self._audit.record(
            SignOffEvent(
                action=action,
                review_id=req.review_id,
                tenant=req.tenant,
                maker=req.maker,
                checker=checker,
                disposition=disposition,
                decision=decision,
                state=item.state,
                severity=req.severity,
                # Redact BEFORE the write: no raw identifier reaches the sign-off record.
                redacted_reason=redact(reason, PII_PATTERNS),
                redacted_summary=redact(f"{req.subject} :: {req.summary}", PII_PATTERNS),
                findings=tuple(findings),
                citations=req.citations,
            )
        )


__all__ = ["AlreadyResolved", "ConsoleService", "ReviewNotFound"]
