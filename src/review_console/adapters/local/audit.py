"""Local AuditSinkPort: the SDK-free hash-chained WORM sign-off log from the commons.

Tamper classes DETECTED (C9): any edit to a stored event (the chain hash no longer reproduces),
any re-ordering or in-place deletion (the same), an update/delete attempt (the store's triggers
refuse it), and - because this adapter configures an external head anchor whenever the log is on
disk - truncation or wholesale rewriting of the tail, which leaves a perfectly valid SHORTER chain
that only an out-of-band anchored head can expose.

Tamper classes NOT detected: an attacker with write access to BOTH the database and the anchor
file can rewrite both consistently (the chain carries no secret). That is why the anchor should
live on a different volume or in a different trust domain (``REVIEW_AUDIT_ANCHOR_PATH``), and why
managed profiles use a locked Cloud Logging WORM bucket instead of this stand-in.
"""

from __future__ import annotations

from hex_service_kit.audit import HashChainedAuditLog

from ...config import Settings
from ...ports.audit import AuditEvent


class LocalAuditAdapter:
    """Append-only, hash-chained local WORM stand-in (delegates to hex-service-kit)."""

    def __init__(self, settings: Settings) -> None:
        self._log = HashChainedAuditLog(
            settings.audit_path, anchor_path=settings.resolved_audit_anchor_path
        )

    def record(self, event: AuditEvent) -> None:
        self._log.record(event)

    @property
    def log(self) -> HashChainedAuditLog:
        """Expose the underlying log for verify / export in the CLI, eval and tests."""
        return self._log
