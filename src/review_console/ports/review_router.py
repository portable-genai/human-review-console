"""ReviewRouterPort: the boundary that routes an escalated case into human review (rule R8).

When a case escalates (a breach or a stall sets ``requires_human_review``), the engine does not
act on it: it routes it to the maker-checker console for a human to dispose. In the merged service
the default adapter submits the review IN-PROCESS (a direct call to ``ConsoleService.submit``,
no S2S hop). The port is kept as a seam so a SPLIT deployment can instead bind a remote adapter
that targets a separate console over the network; the domain stays pure either way.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.cases.models import Case, CaseAssessment


@runtime_checkable
class ReviewRouterPort(Protocol):
    def route(self, case: Case, assessment: CaseAssessment, *, maker: str) -> None:
        """Route an escalated case into human review (idempotent per case is ideal)."""
        ...
