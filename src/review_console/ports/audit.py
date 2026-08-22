"""AuditSinkPort: the WORM sign-off boundary (the hexagon edge for observability, rule R2).

One WORM sink serves the merged service: it records the console's ``SignOffEvent`` for every
disposition attempt AND the case engine's ``CaseAuditEvent`` for every case action. Both
are frozen dataclasses the adapters render to a JSON object, so a single ``record`` seam accepts
either.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.cases.kernel import CaseAuditEvent
from ..domain.kernel import SignOffEvent

#: Any already-redacted audit record the WORM sink accepts (console sign-off or case action).
AuditEvent = SignOffEvent | CaseAuditEvent


@runtime_checkable
class AuditSinkPort(Protocol):
    def record(self, event: AuditEvent) -> None:
        """Append one immutable, already-redacted audit record (sign-off or case action)."""
        ...
