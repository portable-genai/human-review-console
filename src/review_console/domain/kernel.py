"""Vertical-neutral domain kernel: the pure-stdlib taxonomies and provenance types.

Taxonomies are ``LenientStrEnum``s from the commons (a member IS its wire value, and lookup is
case-insensitive so an inbound ``"APPROVE"`` or ``"approve"`` both resolve). Citations carry
provenance; the WORM sign-off event is stored already-redacted. Nothing here imports a web
framework or a cloud SDK.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from hex_service_kit.enums import LenientStrEnum


def utcnow() -> datetime:
    """Timezone-aware UTC now (the single clock the domain uses when no ``as_of`` is supplied)."""
    return datetime.now(UTC)


class Severity(LenientStrEnum):
    """How consequential the underlying action is (drives the default approval count)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Disposition(LenientStrEnum):
    """A checker's verdict on a review item."""

    APPROVE = "approve"
    REJECT = "reject"
    AMEND = "amend"  # send back to the maker to change and resubmit


class ReviewState(LenientStrEnum):
    """The lifecycle state of a review item."""

    PENDING = "pending"  # awaiting one or more approvals
    APPROVED = "approved"  # every required approval collected (four-eyes satisfied)
    REJECTED = "rejected"  # a checker rejected it (terminal)
    AMENDED = "amended"  # sent back to the maker (terminal for this item)

    @property
    def is_terminal(self) -> bool:
        return self is not ReviewState.PENDING


class EligibilityFinding(LenientStrEnum):
    """Why a checker may NOT dispose of an item. Any finding is a fail-closed denial.

    ``SELF_APPROVAL`` is the load-bearing one: it is principle P-06 four-eyes made mechanical, so
    a maker can never approve their own work no matter how the request is shaped.
    """

    WRONG_TENANT = "wrong_tenant"  # checker is not in the item's tenant (cross-tenant denial)
    SELF_APPROVAL = "self_approval"  # checker IS the maker (four-eyes breach, P-06)
    SEGREGATION_OF_DUTIES = "segregation_of_duties"  # checker shares the maker's SoD group
    INSUFFICIENT_ROLE = "insufficient_role"  # checker lacks the approver entitlement
    DUPLICATE_APPROVER = "duplicate_approver"  # checker already approved (N-eyes must be distinct)


class Decision(LenientStrEnum):
    """The audit decision recorded for one disposition attempt."""

    ALLOWED = "allowed"  # the checker was eligible and the disposition was recorded
    DENIED = "denied"  # a fail-closed eligibility finding blocked the disposition


@dataclass(frozen=True, slots=True)
class Citation:
    """Provenance attached to a review (the originating case, evidence, or upstream decision)."""

    source_id: str
    title: str
    snippet: str = ""


@dataclass(frozen=True, slots=True)
class SignOffEvent:
    """An immutable, already-redacted record of one disposition attempt (P-04 / rule R2).

    Written to the WORM audit sink for every attempt, allowed or denied, so the sign-off trail
    proves who approved (or was refused approval of) what and when. Carries no raw identifiers:
    the reason and summary are redacted before this is constructed.
    """

    action: str
    review_id: str
    tenant: str
    maker: str
    checker: str
    disposition: Disposition
    decision: Decision
    state: ReviewState
    severity: Severity
    redacted_reason: str
    redacted_summary: str
    findings: tuple[EligibilityFinding, ...] = ()
    citations: tuple[Citation, ...] = ()
    timestamp: datetime = field(default_factory=utcnow)
