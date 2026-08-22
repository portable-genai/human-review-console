"""The hexagon boundary: every external edge the console reaches is a ``typing.Protocol`` here.

Enumerate ports by NAME (one entry per port) rather than by count, so the parity contract test
and this ``__all__`` together are the source of truth for what exists. The case-workflow ports
sit alongside the review ports on the same hexagon.

``IdentityPort`` itself is not declared here: it comes from the shared ``hex-service-kit``
commons. What an identity adapter DECLARES about the authentication it provides is this
service's own vocabulary, not the commons', and lives in :mod:`.identity`.
"""

from __future__ import annotations

from .audit import AuditSinkPort
from .case_store import CaseStorePort
from .events import EventPublisherPort
from .identity import (
    CLIENT_ASSERTED,
    END_USER_AUTH_ATTR,
    END_USER_AUTH_KINDS,
    UNIMPLEMENTED,
    VERIFIED,
    EndUserAuthUnavailableError,
    declared_end_user_auth,
)
from .review_router import ReviewRouterPort
from .review_store import ReviewStorePort
from .timers import TimerPort

__all__ = [
    "CLIENT_ASSERTED",
    "END_USER_AUTH_ATTR",
    "END_USER_AUTH_KINDS",
    "UNIMPLEMENTED",
    "VERIFIED",
    "AuditSinkPort",
    "CaseStorePort",
    "EndUserAuthUnavailableError",
    "EventPublisherPort",
    "ReviewRouterPort",
    "ReviewStorePort",
    "TimerPort",
    "declared_end_user_auth",
]
