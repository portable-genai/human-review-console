"""GCP IdentityPort: verify the IAP-injected signed assertion (SDK imports stay lazy).

The verified principal's ``tenant`` (the IAP ``hd`` hosted-domain claim) and group memberships
become the console's tenant partition and approver entitlement, so the four-eyes / SoD checks run
against a real, server-verified identity in production exactly as they do against a persona
locally.

The assertion is read under BOTH names it can arrive under, and for this console that is not a
hypothetical. ``x-goog-*`` is Google's reserved namespace and the serverless frontend strips it
from a request entering a service, so the portal that MOUNTS this console cannot forward the
assertion its own edge was handed under the standard name; it sends the same value as
``x-portal-iap-assertion`` too. Reading the reserved name alone would answer 401 to every
authenticated approver the day this console is embedded -- with a green gate, a healthy-looking
page, and a passing offline suite, because the console's first calls need no identity at all.
Both names take the identical verification path: the header is TRANSPORT and vouches for nothing.
"""

from __future__ import annotations

import json
from typing import Any

from hex_service_kit.assertion import require_claims, require_pinned_algorithm
from hex_service_kit.federation import (
    IAP_ASSERTION_HEADER,
    IAP_ISSUER,
    IAP_KEYS_URL,
    PORTAL_ASSERTION_HEADER,
    select_assertion,
)
from hex_service_kit.identity import IdentityError, Principal, RequestContext

from ...config import Settings
from ...ports.identity import VERIFIED, AudienceUnconfiguredError

# This repository's names for the kit's transport facts. They are REBOUND, not re-declared:
# the header name, the issuer and the key-set URL are the same three strings in every
# repository that verifies an IAP assertion, and while each kept its own copy the population
# could drift without anything noticing. Rebinding makes a divergence between this adapter and
# the reviewed set impossible rather than merely unlikely.
#
#: ``verify_token`` does not check the issuer at all (``verify_oauth2_token`` is the wrapper
#: that does), so this adapter checks it itself against the kit's value.
_IAP_ASSERTION_HEADER = IAP_ASSERTION_HEADER

#: The SAME assertion under a name the platform does NOT reserve, which is the only name the
#: embedding portal can forward it under. A fallback for TRANSPORT and never a second trust path:
#: what arrives under it is verified identically, so a caller gains nothing by choosing it.
_PORTAL_ASSERTION_HEADER = PORTAL_ASSERTION_HEADER
_IAP_KEYS_URL = IAP_KEYS_URL
_IAP_ISSUER = IAP_ISSUER

#: The claims this deployment requires before it reads any of them. A claim that is present
#: but empty counts as missing, which a per-field `or` chain cannot express.
_REQUIRED_CLAIMS = ("iss", "sub", "email", "exp")


class IapIdentityAdapter:
    """Resolve a verified Principal from the Identity-Aware-Proxy assertion header.

    This is the one adapter in the shipped set that declares :data:`VERIFIED`, and it earns it
    in :meth:`resolve`: the assertion's signature, issuer, expiry and audience are checked by
    ``id_token.verify_token`` before any claim is read, and the verified subject must then match
    a reviewed entitlement mapping. A caller cannot name itself by writing a header. That
    declaration is what lets the exposure guard stand down.
    """

    #: A signed assertion, verified here. See ``ports/identity.py``.
    end_user_auth = VERIFIED

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._audience = settings.iap_audience
        self._entitlements = self._parse_entitlements(settings.iap_entitlements_json)

    @staticmethod
    def _parse_entitlements(raw: str) -> dict[str, dict[str, object]]:
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise IdentityError("REVIEW_IAP_ENTITLEMENTS_JSON is not valid JSON") from exc
        if not isinstance(value, dict) or not all(
            isinstance(subject, str) and isinstance(entry, dict) for subject, entry in value.items()
        ):
            raise IdentityError(
                "REVIEW_IAP_ENTITLEMENTS_JSON must map subjects to entitlement objects"
            )
        return value

    def resolve(self, ctx: RequestContext) -> Principal:
        assertion = self._select_assertion(ctx)
        self._require_audience()
        if not self._entitlements:
            raise IdentityError(
                "REVIEW_IAP_ENTITLEMENTS_JSON is not configured; cannot authorize IAP subject"
            )
        claims = self._verified_claims(assertion)
        subject = str(claims["email"]).strip()

        entitlement = self._entitlements.get(subject)
        if entitlement is None:
            raise IdentityError(
                "verified IAP subject has no reviewed agent-registry entitlement mapping"
            )
        tenant = str(entitlement.get("tenant") or "").strip()
        groups = entitlement.get("principals")
        if (
            not tenant
            or not isinstance(groups, list)
            or not all(isinstance(group, str) and group.strip() for group in groups)
        ):
            raise IdentityError(
                "IAP entitlement mapping needs a tenant and a string principals list"
            )
        expected_domain = str(entitlement.get("hosted_domain") or "").strip()
        claim_domain = str(claims.get("hd") or "").strip()
        if expected_domain and claim_domain != expected_domain:
            raise IdentityError("IAP hosted-domain claim does not match the reviewed mapping")

        principals = tuple(dict.fromkeys((f"user:{subject}", *(group.strip() for group in groups))))
        return Principal(
            subject=subject,
            principals=principals,
            tenant=tenant,
            assurance="iap",
            source="gcp-iap",
        )

    def verify_service_assertion(self, ctx: RequestContext) -> str:
        """The verified email of the caller IAP authenticated, for the SERVICE intake.

        Behind the portal's IAP edge a producer's request arrives with the PORTAL's token in
        ``Authorization`` (the portal replaces it on every request it forwards) and the edge's
        assertion about the ORIGINAL caller in the forwarded header. This verifies that
        assertion on exactly the path :meth:`resolve` uses (header selection, audience,
        algorithm pin, signature, issuer, required claims) and returns its ``email``,
        lower-cased. It reads no entitlement mapping: whether that address may submit is the
        machine-caller allowlist's decision, made by the caller of this method.

        Raises :class:`~review_console.ports.identity.AudienceUnconfiguredError` when
        ``REVIEW_IAP_AUDIENCE`` is unset (a deployment fault, not a caller's), and
        :class:`IdentityError` for a missing or unverifiable assertion.
        """
        # The policy before the token, as the commons S2S check orders it: with no audience this
        # deployment can verify NOBODY, and that is the answer whatever the request carried.
        self._require_audience()
        assertion = self._select_assertion(ctx)
        claims = self._verified_claims(assertion)
        return str(claims["email"]).strip().lower()

    @staticmethod
    def _select_assertion(ctx: RequestContext) -> str:
        # ONE selection function, in the commons, rather than another copy of an `or` chain. It
        # examines BOTH names an assertion travels under, prefers the edge-injected one, and
        # strips, so a header the portal rendered blank is ABSENT rather than an assertion: a
        # whitespace-only value is truthy, and unstripped it would skip this refusal and be
        # refused further down by the algorithm pin, which reports a malformed token for what is
        # actually a missing one.
        #
        # The keys are lower-cased here rather than assumed. ``RequestContext`` documents them as
        # lower-cased and the web layer supplies them that way, but this is a dictionary lookup
        # rather than ``ctx.header``, and an identity that goes missing because of header CASE is
        # the same class of silent refusal this line exists to end.
        try:
            source = select_assertion({k.lower(): v for k, v in ctx.headers.items()})
        except IdentityError as exc:
            # This console's own sentence, kept so the refusal reads as it always has, with the
            # commons reason appended because that reason names BOTH headers it examined. An
            # operator who reads only "missing IAP assertion header" goes to the load balancer;
            # the one who reads which two names were looked for goes to the hop that dropped one.
            raise IdentityError(
                f"missing IAP assertion header; request did not pass through IAP: {exc}"
            ) from exc
        return source.assertion

    def _require_audience(self) -> None:
        if not self._audience:
            raise AudienceUnconfiguredError(
                "REVIEW_IAP_AUDIENCE is not configured; cannot verify IAP assertion"
            )

    def _verified_claims(self, assertion: str) -> dict[str, Any]:
        # The algorithm is judged before the verifier is handed the token: no cryptography, no
        # cloud SDK, so the refusal is exercised by the offline gate. `alg: none` is an unsigned
        # assertion and HS* would let the public key everybody already has sign one.
        require_pinned_algorithm(assertion)
        claims = self._verify(assertion)
        # The issuer and the claim SET are stated here rather than inherited from verify_token,
        # which checks neither. `email` is required outright now: the previous `email or sub`
        # reader could key the entitlement mapping below off a numeric subject when the email
        # claim was absent, and the reviewed mapping is written in email addresses.
        require_claims(
            claims, issuer=_IAP_ISSUER, audience=self._audience, required=_REQUIRED_CLAIMS
        )
        return claims

    def _verify(self, assertion: str) -> dict[str, Any]:  # pragma: no cover - needs live GCP
        # Lazy imports keep local/onprem import-clean.
        from google.auth.transport import requests as ga_requests
        from google.oauth2 import id_token

        try:
            return dict(
                id_token.verify_token(
                    assertion,
                    ga_requests.Request(),
                    audience=self._audience,
                    certs_url=_IAP_KEYS_URL,
                )
            )
        except Exception as exc:
            raise IdentityError(f"IAP assertion verification failed: {exc}") from exc
