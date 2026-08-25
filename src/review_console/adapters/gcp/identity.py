"""GCP IdentityPort: verify the IAP-injected signed assertion (SDK imports stay lazy).

The verified principal's ``tenant`` (the IAP ``hd`` hosted-domain claim) and group memberships
become the console's tenant partition and approver entitlement, so the four-eyes / SoD checks run
against a real, server-verified identity in production exactly as they do against a persona
locally.
"""

from __future__ import annotations

import json
from typing import Any

from hex_service_kit.assertion import require_claims, require_pinned_algorithm
from hex_service_kit.federation import IAP_ASSERTION_HEADER, IAP_ISSUER, IAP_KEYS_URL
from hex_service_kit.identity import IdentityError, Principal, RequestContext

from ...config import Settings
from ...ports.identity import VERIFIED

# This repository's names for the kit's transport facts. They are REBOUND, not re-declared:
# the header name, the issuer and the key-set URL are the same three strings in every
# repository that verifies an IAP assertion, and while each kept its own copy the population
# could drift without anything noticing. Rebinding makes a divergence between this adapter and
# the reviewed set impossible rather than merely unlikely.
#
#: ``verify_token`` does not check the issuer at all (``verify_oauth2_token`` is the wrapper
#: that does), so this adapter checks it itself against the kit's value.
_IAP_ASSERTION_HEADER = IAP_ASSERTION_HEADER
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
        assertion = ctx.header(_IAP_ASSERTION_HEADER)
        if not assertion:
            raise IdentityError("missing IAP assertion header; request did not pass through IAP")
        if not self._audience:
            raise IdentityError(
                "REVIEW_IAP_AUDIENCE is not configured; cannot verify IAP assertion"
            )
        if not self._entitlements:
            raise IdentityError(
                "REVIEW_IAP_ENTITLEMENTS_JSON is not configured; cannot authorize IAP subject"
            )
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
        subject = str(claims["email"]).strip()

        entitlement = self._entitlements.get(subject)
        if entitlement is None:
            raise IdentityError("verified IAP subject has no reviewed Hrz3 entitlement mapping")
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
