"""Review artifact models: the console's own request / decision / queue-item types.

These are the vertical-neutral shapes the maker-checker engine reasons over. A consumer supplies
the *values* (an action name, a segregation group, how many approvals a severity needs) as
configuration; the console owns none of that policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime

from .kernel import Citation, Disposition, ReviewState, Severity, utcnow


@dataclass(frozen=True, slots=True)
class ReviewRequest:
    """One item submitted for human review: what the maker did that needs a second pair of eyes.

    ``maker`` and ``tenant`` are stamped from the submitter's server-verified principal, never
    from the request body. ``sod_group`` is the maker's segregation-of-duties group (supplied by
    the consumer): a checker sharing it is refused. ``required_approvals`` >= 2 means dual /
    N-eyes control (each approval must be a distinct person, none of them the maker).
    """

    review_id: str
    tenant: str
    action: str
    maker: str
    subject: str
    summary: str
    severity: Severity = Severity.MEDIUM
    required_approvals: int = 1
    sod_group: str = ""
    case_ref: str = ""  # optional link to a case
    citations: tuple[Citation, ...] = ()
    # An authenticated producer's stable key. It is intentionally not accepted on the normal
    # user endpoint and is used only to make S2S delivery retries idempotent.
    source_key: str = ""
    submitted_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    """A checker's disposition of a review item (the checker is a server-verified principal).

    ``checker``, ``checker_tenant`` and ``checker_groups`` are all taken from the verified
    principal, never from the request body, so a caller cannot assert an identity or an
    entitlement they do not hold.
    """

    checker: str
    checker_tenant: str
    checker_groups: tuple[str, ...]
    disposition: Disposition
    reason: str
    amendments: tuple[str, ...] = ()
    decided_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True, slots=True)
class Approval:
    """One collected approval on the path to a fully-approved item (for the N-eyes tally)."""

    checker: str
    reason: str
    at: datetime


@dataclass(frozen=True, slots=True)
class ReviewItem:
    """The queue aggregate: a request, its current state, and the approvals collected so far."""

    request: ReviewRequest
    state: ReviewState = ReviewState.PENDING
    approvals: tuple[Approval, ...] = ()
    terminal_reason: str = ""

    @property
    def review_id(self) -> str:
        return self.request.review_id

    @property
    def tenant(self) -> str:
        return self.request.tenant

    @property
    def approvals_count(self) -> int:
        return len(self.approvals)

    @property
    def approvers(self) -> tuple[str, ...]:
        return tuple(a.checker for a in self.approvals)

    @property
    def is_terminal(self) -> bool:
        return self.state.is_terminal

    def with_approval(self, approval: Approval, *, state: ReviewState) -> ReviewItem:
        return replace(self, approvals=(*self.approvals, approval), state=state)

    def resolved(self, *, state: ReviewState, reason: str) -> ReviewItem:
        return replace(self, state=state, terminal_reason=reason)
