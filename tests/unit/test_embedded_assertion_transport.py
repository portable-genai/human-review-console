"""The header an assertion arrives under once this console is MOUNTED, and what it costs.

This console is the surface every deployed application routes a human decision to, and the
portal mounts it same-origin. So the embedded case is not hypothetical here: it is the only case
that matters in the deployment.

**The transport fact.** ``x-goog-*`` is Google's reserved namespace and the serverless frontend
REMOVES that whole namespace from a request entering a service, so the portal cannot forward the
assertion its own IAP edge handed it under the standard name: the portal sets the reserved name,
the frontend drops it, and this console refuses "request did not pass through IAP" about a
request that passed through IAP one hop earlier. The portal sends the same value as
``x-portal-iap-assertion`` as well, precisely because that name is NOT reserved.

**Why the suite next door could not see it.** ``tests/test_gcp_identity.py`` hands the adapter
its assertion as ``RequestContext(headers={"x-goog-iap-jwt-assertion": ...})`` and passes. It is
right about the entitlement mapping it asserts and silent about the transport, which is the shape
of a test that builds its own request: the fixture chooses the header, so it can only ever choose
the one the author had in mind. The same contradiction -- a green claim suite beside a live 401 --
was observed on two deployed applications on 2026-09-12 and cost hours before the header was the
suspect.

Nothing here needs a cloud SDK, a project or a network.
"""

from __future__ import annotations

import base64
import json

import pytest
from hex_service_kit import federation as kit_federation
from hex_service_kit.identity import IdentityError, RequestContext

from review_console.adapters.gcp.identity import (
    _IAP_ASSERTION_HEADER,
    _PORTAL_ASSERTION_HEADER,
    IapIdentityAdapter,
)
from review_console.config import Settings

AUDIENCE = "/projects/1/apps/app"

MAPPING = """
{
  "approver@bank.example": {
    "tenant": "bank-one",
    "hosted_domain": "bank.example",
    "principals": ["group:risk", "group:approver"]
  }
}
"""

CLAIMS = {
    "iss": kit_federation.IAP_ISSUER,
    "sub": "accounts.google.com:100000000000000000001",
    "email": "approver@bank.example",
    "hd": "bank.example",
    "exp": 1_900_000_000,
}


def signed_assertion() -> str:
    """A structurally real compact JWS; only the JOSE header is ever parsed, nothing is signed."""
    header = (
        base64.urlsafe_b64encode(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        .decode()
        .rstrip("=")
    )
    payload = base64.urlsafe_b64encode(b'{"sub":"1"}').decode().rstrip("=")
    return f"{header}.{payload}.c2ln"


def adapter() -> IapIdentityAdapter:
    return IapIdentityAdapter(
        Settings(profile="gcp", iap_audience=AUDIENCE, iap_entitlements_json=MAPPING)
    )


def resolving_adapter(
    monkeypatch: pytest.MonkeyPatch, seen: list[str] | None = None
) -> IapIdentityAdapter:
    """The shipped adapter with ONLY the cryptography stubbed.

    Every check the adapter owns still runs: the algorithm pin, the required claims, the issuer,
    the audience, the reviewed entitlement mapping and the hosted-domain match.
    """
    built = adapter()

    def _verify(assertion: str) -> dict[str, object]:
        if seen is not None:
            seen.append(assertion)
        return {**CLAIMS, "aud": AUDIENCE}

    monkeypatch.setattr(built, "_verify", _verify)
    return built


def test_the_forwarded_header_name_is_the_commons_value_and_is_not_reserved() -> None:
    """Rebound from the kit, never re-declared, and OUTSIDE the stripped namespace.

    Putting the fallback back inside ``x-goog-*`` would reintroduce the exact defect it fixes,
    silently, because the frontend strips the whole namespace rather than one name.
    """
    assert _PORTAL_ASSERTION_HEADER == kit_federation.PORTAL_ASSERTION_HEADER
    assert _PORTAL_ASSERTION_HEADER == "x-portal-iap-assertion"
    assert not _PORTAL_ASSERTION_HEADER.startswith("x-goog-")
    assert _IAP_ASSERTION_HEADER.startswith("x-goog-"), "the reserved name is the stripped one"


def test_an_approver_resolves_when_the_portal_forwarded_the_assertion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The offline reproduction: identical claims and mapping, only the header name differs.

    Under the forwarded name -- the only one a mounted console ever sees -- the adapter as it
    shipped refused with "missing IAP assertion header" and the reviewed entitlement mapping was
    never read.
    """
    principal = resolving_adapter(monkeypatch).resolve(
        RequestContext(headers={_PORTAL_ASSERTION_HEADER: signed_assertion()})
    )
    assert principal.subject == "approver@bank.example"
    assert principal.tenant == "bank-one"
    assert "group:approver" in principal.principals


def test_both_names_yield_the_same_principal_from_the_same_assertion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fallback is TRANSPORT, not a second trust path with its own outcome.

    If the two names could ever produce different identities, the header would be vouching for
    something, and a caller could choose what it vouched for.
    """
    token = signed_assertion()
    edge = resolving_adapter(monkeypatch).resolve(
        RequestContext(headers={_IAP_ASSERTION_HEADER: token})
    )
    forwarded = resolving_adapter(monkeypatch).resolve(
        RequestContext(headers={_PORTAL_ASSERTION_HEADER: token})
    )
    assert edge == forwarded


def test_the_edge_injected_name_still_wins_when_both_are_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Precedence is about diagnosis, not trust: the direct edge's assertion needs no forwarding."""
    edge = signed_assertion()
    seen: list[str] = []
    resolving_adapter(monkeypatch, seen=seen).resolve(
        RequestContext(
            headers={
                _IAP_ASSERTION_HEADER: edge,
                _PORTAL_ASSERTION_HEADER: "forwarded-and-different",
            }
        )
    )
    assert seen == [edge]


def test_the_header_is_found_whatever_case_the_hop_wrote_it_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hop that capitalises the name must not make the identity go missing.

    HTTP header names are case-insensitive, and the selection is a dictionary lookup.
    """
    principal = resolving_adapter(monkeypatch).resolve(
        RequestContext(headers={_PORTAL_ASSERTION_HEADER.upper(): signed_assertion()})
    )
    assert principal.subject == "approver@bank.example"


def test_neither_name_present_is_still_a_missing_assertion() -> None:
    """And the refusal must NAME both headers it examined.

    An operator who reads only "missing IAP assertion header" goes to the load balancer. The one
    who reads which two names were looked for goes to the hop that dropped one of them.
    """
    with pytest.raises(IdentityError) as caught:
        adapter().resolve(RequestContext(headers={}))
    message = str(caught.value)
    assert "missing IAP assertion header" in message
    assert kit_federation.IAP_ASSERTION_HEADER in message
    assert kit_federation.PORTAL_ASSERTION_HEADER in message


@pytest.mark.parametrize("blank", ["", "   ", "\t", "\n"])
@pytest.mark.parametrize(
    "header",
    [kit_federation.IAP_ASSERTION_HEADER, kit_federation.PORTAL_ASSERTION_HEADER],
    ids=["edge-injected", "host-forwarded"],
)
def test_a_whitespace_only_header_is_an_absent_one_under_either_name(
    header: str, blank: str
) -> None:
    """A blank value is TRUTHY, so unstripped it would be refused as a malformed token instead.

    That refusal reports the wrong fault: a proxy that rendered the variable empty is a missing
    assertion, not a caller presenting a broken one.
    """
    with pytest.raises(IdentityError, match="missing IAP assertion header"):
        adapter().resolve(RequestContext(headers={header: blank}))
