"""Local IdentityPort: seeded dev personas (no IdP / AD / LDAP), from the commons.

The seeded personas carry the ``tenant`` and ``principals`` (group) fields the console's
four-eyes / SoD / tenant checks rely on: ``demo.approver@bank.example`` holds
``group:approver`` in tenant ``demo-bank``; ``user@other-tenant.example`` sits in ``other-bank``
so the cross-tenant denial path is demoable with no cloud IdP.

These personas are an UNAUTHENTICATED grant of the approver entitlement, so this adapter refuses
to construct unless the local profile was chosen deliberately: the profile must actually be
``local`` AND (when the settings came from the environment) ``REVIEW_PROFILE`` must have been set
rather than inherited from the fallback. A missing env var therefore fails closed instead of
serving a maker-checker control plane with dev approvers.
"""

from __future__ import annotations

from hex_service_kit.identity import (
    LocalPersonaIdentityAdapter,
    Principal,
    RequestContext,
)

from ...config import Settings
from ...ports.identity import CLIENT_ASSERTED, EndUserAuthUnavailableError


class LocalPersonaProfileError(EndUserAuthUnavailableError):
    """Raised when seeded dev personas would be served under a non-deliberate local profile.

    An :class:`~hex_service_kit.identity.IdentityError`, so a caller gets a 401 rather than a
    500: the caller is not authenticated, and that is the honest answer whether the cause is a
    bad persona name or an unconfigured deployment. It is the "nobody can authenticate here"
    subclass, so the API answers with the message below rather than with a bare "authentication
    required" that points an operator at the wrong problem; the status stays 401, because a
    caller with no credential is exactly what this refuses.
    """


class LocalIdentityAdapter:
    """Resolve a Principal from a seeded dev persona (local profile only, CLIENT-ASSERTED).

    The declaration below is the load-bearing line for the exposure guard. These personas are
    chosen by a header the CALLER writes, so this adapter authenticates nobody and says so; the
    guard reads that and keeps the console on loopback. It says so whatever else is configured,
    because no other credential makes ``X-Dev-Persona`` a verified identity.
    """

    #: Seeded personas come from a header the client wrote. See ``ports/identity.py``.
    end_user_auth = CLIENT_ASSERTED

    def __init__(self, settings: Settings) -> None:
        if settings.profile != "local":
            raise LocalPersonaProfileError(
                "seeded dev personas are local-profile only; "
                f"refusing to serve them under profile {settings.profile!r}"
            )
        if not settings.profile_explicit:
            raise LocalPersonaProfileError(
                "REVIEW_PROFILE is not set, so the local profile was inherited rather than "
                "chosen; seeded dev personas grant the approver entitlement with no "
                "authentication and are refused. Set REVIEW_PROFILE=local deliberately for a "
                "dev or demo run, or REVIEW_PROFILE=gcp for a real deployment."
            )
        self._settings = settings
        self._inner = LocalPersonaIdentityAdapter(
            (
                Principal(
                    subject="demo.analyst@bank.example",
                    principals=("group:analyst", "group:risk"),
                    tenant="demo-bank",
                    assurance="local-demo",
                    source="local-persona:analyst",
                ),
                Principal(
                    subject="demo.approver@bank.example",
                    principals=("group:analyst", "group:risk", "group:approver"),
                    tenant="demo-bank",
                    assurance="local-demo",
                    source="local-persona:approver",
                ),
                Principal(
                    subject="second.approver@bank.example",
                    principals=("group:risk", "group:approver"),
                    tenant="demo-bank",
                    assurance="local-demo",
                    source="local-persona:second-approver",
                ),
                Principal(
                    subject="demo.auditor@bank.example",
                    principals=("group:audit",),
                    tenant="demo-bank",
                    assurance="local-demo",
                    source="local-persona:auditor",
                ),
                Principal(
                    subject="user@other-tenant.example",
                    principals=("group:analyst",),
                    tenant="other-bank",
                    assurance="local-demo",
                    source="local-persona:other-tenant",
                ),
            )
        )

    def resolve(self, ctx: RequestContext) -> Principal:
        return self._inner.resolve(ctx)

    def personas(self) -> tuple[dict[str, str], ...]:
        return self._inner.personas()
