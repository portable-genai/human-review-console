"""Why this repository keeps its own claim half, proved by running both.

Every other user-facing repository in this fleet now ends `resolve()` with one
:func:`hex_service_kit.federation.principal_from_iap_claims` call. This one does not, and the
difference is not cosmetic: this adapter is an AUTHORIZATION gate, and the commons is not.

``REVIEW_IAP_ENTITLEMENTS_JSON`` is a reviewed map from a verified address to the tenant and
the group principals that address holds. A subject absent from it is REFUSED, and so is a
deployment that has not configured it at all. Nothing in ``FederationPolicy`` expresses that:
its ``domain_groups`` grants groups by DOMAIN and grants nothing to a domain it does not
name, so an unlisted subject there resolves to a well-formed principal holding no role. Those
two are not the same posture, and the difference reads, at the point a resource is refused,
exactly like a permissions bug rather than a caller who was never admitted. ``Hrz3`` is the
console a human uses to release a consequential decision, so "admitted with nothing" is the
wrong answer to give.

``allowed_machine_subjects`` is the closest the commons comes, and it is an allowlist for
MACHINE callers only: ``principal_from_iap_claims`` applies it when the address ends
``.gserviceaccount.com`` and never to a human. There is no human-subject allowlist, and adding
this repository's one to the commons would push a deployment-specific reviewed map into a
module whose whole point is the half that must not vary.

The tests below run the shipped adapter and the commons over the same claim sets and assert
that they disagree, with the reason attached, so this is an exclusion the suite can check
rather than a comment somebody has to believe. What this repository DOES take from the commons
is the transport half and the assertion pins, and the last test says so.
"""

from __future__ import annotations

from typing import Any

import pytest
from hex_service_kit.federation import (
    IAP_ISSUER,
    FederationPolicy,
    principal_from_iap_claims,
)
from hex_service_kit.identity import IdentityError, RequestContext

from review_console.adapters.gcp.identity import IapIdentityAdapter

_AUDIENCE = "/projects/1234567890/global/backendServices/42"
_REVIEWER = "avery.stone@example-bank.test"
_STRANGER = "morgan.reyes@example-bank.test"
_ENTITLEMENTS: dict[str, Any] = {
    _REVIEWER: {
        "tenant": "reference-bank",
        "principals": ["group:reviewer", "group:approver"],
        "hosted_domain": "example-bank.test",
    }
}


def _claims(**overrides: Any) -> dict[str, Any]:
    claims: dict[str, Any] = {
        "iss": IAP_ISSUER,
        "aud": _AUDIENCE,
        "sub": "accounts.google.com:100000000000000000001",
        "email": _REVIEWER,
        "hd": "example-bank.test",
        "exp": 4102444800,
    }
    claims.update(overrides)
    return {name: value for name, value in claims.items() if value is not None}


def _adapter(entitlements: dict[str, Any] | None = None) -> IapIdentityAdapter:
    adapter = object.__new__(IapIdentityAdapter)
    adapter._settings = None
    adapter._audience = _AUDIENCE
    adapter._entitlements = _ENTITLEMENTS if entitlements is None else entitlements
    return adapter


def _resolved(claims: dict[str, Any], entitlements: dict[str, Any] | None = None) -> Any:
    """The shipped adapter's claim half, with only the cryptography stubbed."""
    adapter = _adapter(entitlements)
    object.__setattr__(adapter, "_verify", lambda assertion: dict(claims))
    ctx = RequestContext(headers={"x-goog-iap-jwt-assertion": "eyJhbGciOiJSUzI1NiJ9.e30.c2ln"})
    return adapter.resolve(ctx)


def _commons(claims: dict[str, Any]) -> Any:
    return principal_from_iap_claims(
        claims,
        FederationPolicy(tenant_from_hosted_domain=True),
        source="gcp-iap",
        include_subject_principal=False,
    )


# --------------------------------------------------------------------------------------- #
# The gate the commons cannot express.
# --------------------------------------------------------------------------------------- #
def test_a_verified_subject_with_no_reviewed_entitlement_is_refused_here() -> None:
    """The commons admits the same caller with an empty entitlement, which is a different thing.

    A principal that exists but holds nothing is indistinguishable, at the point it is refused
    a resource, from a reviewer whose role has not been granted yet. This console releases
    consequential decisions, so an unreviewed subject is refused at the door instead.
    """
    claims = _claims(email=_STRANGER)
    with pytest.raises(IdentityError, match="no reviewed Hrz3 entitlement mapping"):
        _resolved(claims)
    admitted = _commons(claims)
    assert admitted.subject == _STRANGER
    assert admitted.principals == ()


def test_an_unconfigured_entitlement_map_refuses_everybody_here() -> None:
    """Three states, and the empty one is a refusal rather than an inherited permissive default."""
    with pytest.raises(IdentityError, match="REVIEW_IAP_ENTITLEMENTS_JSON is not configured"):
        _resolved(_claims(), entitlements={})
    assert _commons(_claims()).subject == _REVIEWER


def test_the_reviewed_groups_come_from_the_subject_map_and_not_from_a_domain_map() -> None:
    """``domain_groups`` grants by domain; this grants by subject, which is the reviewed unit."""
    principal = _resolved(_claims())
    assert principal.tenant == "reference-bank"
    assert principal.principals == (
        f"user:{_REVIEWER}",
        "group:reviewer",
        "group:approver",
    )
    # The same claim set under the commons: no groups, because no domain was mapped, and a
    # tenant that came from the assertion rather than from a reviewed mapping.
    assert _commons(_claims()).principals == ()


def test_the_hosted_domain_must_match_the_reviewed_mapping() -> None:
    """A reviewed subject signing in from an unexpected organisation is refused, not remapped."""
    with pytest.raises(IdentityError, match="hosted-domain claim does not match"):
        _resolved(_claims(hd="somewhere-else.test"))
    assert _commons(_claims(hd="somewhere-else.test")).tenant == "somewhere-else.test"


# --------------------------------------------------------------------------------------- #
# The exclusion is the claim half alone.
# --------------------------------------------------------------------------------------- #
def test_the_transport_facts_are_still_the_commons_values() -> None:
    from hex_service_kit import federation as kit

    from review_console.adapters.gcp import identity

    assert identity._IAP_ASSERTION_HEADER == kit.IAP_ASSERTION_HEADER
    assert identity._IAP_ISSUER == kit.IAP_ISSUER
    assert identity._IAP_KEYS_URL == kit.IAP_KEYS_URL
