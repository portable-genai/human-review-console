from __future__ import annotations

import base64
import json

import pytest
from hex_service_kit.identity import IdentityError, RequestContext

from review_console.adapters.gcp.identity import IapIdentityAdapter
from review_console.config import Settings

MAPPING = """
{
  "approver@bank.example": {
    "tenant": "bank-one",
    "hosted_domain": "bank.example",
    "principals": ["group:risk", "group:approver"]
  }
}
"""


def _signed_assertion(alg: str = "RS256") -> str:
    """A structurally real compact JWS, because the algorithm pin reads the JOSE header.

    This fixture was the literal `"signed.jwt"`, which was fine while nothing looked at the token
    before the (stubbed) verifier did. `require_pinned_algorithm` looks, so a fixture that is not
    a JWS is refused before it reaches the stub. Making the fixture real is the correct repair:
    a test whose token could never exist proves nothing about a token that can. Nothing is
    signed here; only the header is ever parsed.
    """
    header = (
        base64.urlsafe_b64encode(json.dumps({"alg": alg, "typ": "JWT"}).encode())
        .decode()
        .rstrip("=")
    )
    payload = base64.urlsafe_b64encode(b'{"sub":"1"}').decode().rstrip("=")
    return f"{header}.{payload}.c2ln"


def _context() -> RequestContext:
    return RequestContext(headers={"x-goog-iap-jwt-assertion": _signed_assertion()})


def test_gcp_identity_requires_exact_audience_before_verification() -> None:
    adapter = IapIdentityAdapter(Settings(profile="gcp", iap_entitlements_json=MAPPING))
    with pytest.raises(IdentityError, match="REVIEW_IAP_AUDIENCE"):
        adapter.resolve(_context())


def test_gcp_identity_requires_reviewed_entitlement_mapping() -> None:
    adapter = IapIdentityAdapter(Settings(profile="gcp", iap_audience="/projects/1/apps/app"))
    with pytest.raises(IdentityError, match="REVIEW_IAP_ENTITLEMENTS_JSON"):
        adapter.resolve(_context())


def test_gcp_identity_maps_verified_subject_to_tenant_and_approver_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = IapIdentityAdapter(
        Settings(
            profile="gcp",
            iap_audience="/projects/1/apps/app",
            iap_entitlements_json=MAPPING,
        )
    )
    monkeypatch.setattr(
        adapter,
        "_verify",
        lambda assertion: {
            "iss": "https://cloud.google.com/iap",
            "sub": "accounts.google.com:100000000000000000001",
            "exp": 1_900_000_000,
            "aud": "/projects/1/apps/app",
            "email": "approver@bank.example",
            "hd": "bank.example",
        },
    )
    principal = adapter.resolve(_context())
    assert principal.subject == "approver@bank.example"
    assert principal.tenant == "bank-one"
    assert principal.principals == (
        "user:approver@bank.example",
        "group:risk",
        "group:approver",
    )


def test_gcp_identity_rejects_unmapped_subject(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = IapIdentityAdapter(
        Settings(
            profile="gcp",
            iap_audience="/projects/1/apps/app",
            iap_entitlements_json=MAPPING,
        )
    )
    monkeypatch.setattr(
        adapter,
        "_verify",
        lambda assertion: {
            "iss": "https://cloud.google.com/iap",
            "sub": "accounts.google.com:100000000000000000001",
            "exp": 1_900_000_000,
            "aud": "/projects/1/apps/app",
            "email": "unknown@bank.example",
            "hd": "bank.example",
        },
    )
    with pytest.raises(IdentityError, match="no reviewed Hrz3 entitlement mapping"):
        adapter.resolve(_context())


def test_gcp_identity_rejects_wrong_issuer_or_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = IapIdentityAdapter(
        Settings(
            profile="gcp",
            iap_audience="/projects/1/apps/app",
            iap_entitlements_json=MAPPING,
        )
    )
    monkeypatch.setattr(
        adapter,
        "_verify",
        lambda assertion: {
            "iss": "https://accounts.google.com",
            "sub": "accounts.google.com:100000000000000000001",
            "exp": 1_900_000_000,
            "aud": "/projects/1/apps/app",
            "email": "approver@bank.example",
            "hd": "bank.example",
        },
    )
    # The refusal moved into `hex_service_kit.assertion.require_claims`, so the wording is the
    # commons' rather than this repository's. The behaviour asserted is unchanged.
    with pytest.raises(IdentityError, match="does not accept"):
        adapter.resolve(_context())

    monkeypatch.setattr(
        adapter,
        "_verify",
        lambda assertion: {
            "iss": "https://cloud.google.com/iap",
            "sub": "accounts.google.com:100000000000000000001",
            "exp": 1_900_000_000,
            "aud": "/projects/1/apps/app",
            "email": "approver@bank.example",
            "hd": "other.example",
        },
    )
    with pytest.raises(IdentityError, match="hosted-domain"):
        adapter.resolve(_context())


def test_gcp_identity_rejects_invalid_mapping_at_construction() -> None:
    with pytest.raises(IdentityError, match="not valid JSON"):
        IapIdentityAdapter(
            Settings(
                profile="gcp",
                iap_audience="/projects/1/apps/app",
                iap_entitlements_json="{",
            )
        )
