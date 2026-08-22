"""In-process ReviewRouterPort: hand an escalated case straight to the console (rule R8).

In the merged service the case engine and the review console are the same process, so an
escalation no longer makes an S2S hop through ``review-kit``: this adapter calls
``ConsoleService.submit`` DIRECTLY, against the SAME review store the console's own API serves, so
a routed case appears immediately in the tenant's review queue. The subject and summary are still
redacted here (defense in depth) before the console redacts again for its WORM sign-off record.

The ``ReviewRouterPort`` seam is kept precisely so a SPLIT deployment can bind a different adapter
that targets a remote console over the network; this in-process adapter is the merged-service
default.
"""

from __future__ import annotations

import uuid

from pii_kit import redact

from ..domain.cases.models import Case, CaseAssessment
from ..domain.console_service import ConsoleService
from ..domain.pii import PII_PATTERNS


class InProcessReviewRouter:
    """Route an escalated case into the console's queue via a direct in-process submit."""

    def __init__(self, console: ConsoleService) -> None:
        self._console = console

    def route(self, case: Case, assessment: CaseAssessment, *, maker: str) -> None:
        findings = ", ".join(f.value for f in assessment.findings) or "escalated"
        subject = redact(
            f"Case {case.case_id} ({case.case_type}) in state {case.state}", PII_PATTERNS
        )
        summary = redact(f"Escalated on: {findings}", PII_PATTERNS)
        self._console.submit(
            review_id=uuid.uuid4().hex,
            maker=maker,
            tenant=case.tenant,
            action=f"case_review:{case.case_type}",
            subject=subject,
            summary=summary,
            severity=case.severity,
            required_approvals=1,
            case_ref=case.case_id,
            citations=case.citations,
        )
