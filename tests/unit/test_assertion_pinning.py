"""The signing algorithm and the claim set are this deployment's decision, not the token's.

Catalog work item 3 tier 1 (surface parity) asks for accepted signing algorithms and required
claims to be pinned explicitly rather than inherited from whichever verifier library the adapter
happens to call. Before this, `google.oauth2.id_token.verify_token` chose the algorithm from the
token's own header, which is the attacker telling the verifier how to check the attacker's token.

Three properties are proved here, and the third is the one that stops the pin being decorative:

1. the adapter binds the COMMONS refusals, by object identity rather than by name, so a
   look-alike helper or a stale import cannot satisfy this file;
2. each refusal actually fires on the token shape it exists for, exercised on a laptop with no
   cloud SDK installed, which is the whole reason the pin is stdlib and sits outside the lazy
   google import;
3. the algorithm pin is called BEFORE the verifier in `resolve`, read off the source with an
   AST walk. A pin that runs after the token has already been verified is a pin that never
   protected the verifier, and nothing about its presence alone would show that.
"""

from __future__ import annotations

import ast
import base64
import inspect
import json as _json

import pytest
from hex_service_kit import assertion as kit_assertion
from hex_service_kit import federation as kit_federation
from hex_service_kit.identity import IdentityError as KitIdentityError

from review_console.adapters.gcp.identity import IapIdentityAdapter

_IAP_ISSUER = kit_federation.IAP_ISSUER
_AUDIENCE = "/projects/1234567890/global/backendServices/42"


def _token(alg: str = "RS256") -> str:
    """A structurally real compact JWS. Only the header is read, and nothing is signed."""
    header = (
        base64.urlsafe_b64encode(_json.dumps({"alg": alg, "typ": "JWT"}).encode())
        .decode()
        .rstrip("=")
    )
    payload = base64.urlsafe_b64encode(b'{"sub":"1"}').decode().rstrip("=")
    return f"{header}.{payload}.c2ln"


def _claims(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "iss": _IAP_ISSUER,
        "sub": "109876543210987654321",
        "email": "reviewer@example.invalid",
        "exp": 1_900_000_000,
        "aud": _AUDIENCE,
    }
    base.update(overrides)
    return base


def _adapter_module() -> object:
    import importlib

    return importlib.import_module("review_console.adapters.gcp.identity")


class TestTheCommonsRefusalsAreTheOnesBound:
    def test_the_adapter_still_declares_that_it_authenticates(self) -> None:
        # The pin guards the adapter that stands the exposure guard down. If this
        # declaration ever moves, the rest of this file is guarding nothing.
        assert IapIdentityAdapter.end_user_auth is not None

    def test_the_algorithm_pin_is_the_commons_function(self) -> None:
        # Identity, not shape. A byte-identical local copy passes every structural check there
        # is, and the point of the commons is that one edit reaches every consumer.
        assert _adapter_module().require_pinned_algorithm is kit_assertion.require_pinned_algorithm

    def test_the_claim_pin_is_the_commons_function(self) -> None:
        assert _adapter_module().require_claims is kit_assertion.require_claims


class TestTheRefusalsFire:
    def test_an_unsigned_assertion_is_refused(self) -> None:
        with pytest.raises(KitIdentityError, match="UNSIGNED"):
            kit_assertion.require_pinned_algorithm(_token("none"))

    def test_a_symmetric_algorithm_is_refused(self) -> None:
        # HS256 against a verifier holding public keys: the key everybody already has becomes
        # the signing secret.
        with pytest.raises(KitIdentityError, match="pinned set"):
            kit_assertion.require_pinned_algorithm(_token("HS256"))

    def test_the_pinned_algorithms_pass(self) -> None:
        assert kit_assertion.require_pinned_algorithm(_token("RS256")) == "RS256"
        assert kit_assertion.require_pinned_algorithm(_token("ES256")) == "ES256"

    def test_a_complete_assertion_passes_the_claim_pin(self) -> None:
        kit_assertion.require_claims(
            _claims(),
            issuer=_IAP_ISSUER,
            audience=_AUDIENCE,
            required=("iss", "sub", "email", "exp"),
        )

    @pytest.mark.parametrize("absent", ["sub", "email", "exp"])
    def test_a_missing_claim_is_refused(self, absent: str) -> None:
        claims = _claims()
        del claims[absent]
        with pytest.raises(KitIdentityError, match=absent):
            kit_assertion.require_claims(
                claims,
                issuer=_IAP_ISSUER,
                audience=_AUDIENCE,
                required=("iss", "sub", "email", "exp"),
            )

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_a_claim_set_to_nothing_counts_as_missing(self, blank: str) -> None:
        # The three-state rule applied to claims: absent and set-to-empty both name nobody, and
        # the `claims.get("email") or claims.get("sub")` readers this replaced accepted both.
        with pytest.raises(KitIdentityError, match="email"):
            kit_assertion.require_claims(
                _claims(email=blank),
                issuer=_IAP_ISSUER,
                audience=_AUDIENCE,
                required=("iss", "sub", "email", "exp"),
            )

    def test_another_issuer_is_refused(self) -> None:
        with pytest.raises(KitIdentityError, match="does not accept"):
            kit_assertion.require_claims(
                _claims(iss="https://accounts.google.com"),
                issuer=_IAP_ISSUER,
            )

    def test_a_lookalike_issuer_is_refused(self) -> None:
        # An issuer is an identifier and not a namespace, so a prefix or suffix match is how a
        # lookalike host would have passed.
        with pytest.raises(KitIdentityError, match="does not accept"):
            kit_assertion.require_claims(
                _claims(iss=_IAP_ISSUER + ".evil.invalid"),
                issuer=_IAP_ISSUER,
            )

    def test_a_token_for_another_application_is_refused(self) -> None:
        with pytest.raises(KitIdentityError, match="different audience"):
            kit_assertion.require_claims(
                _claims(aud="/projects/9/apps/somebody-else"),
                issuer=_IAP_ISSUER,
                audience=_AUDIENCE,
            )


_PIN_NAMES = {"require_pinned_algorithm", "_refuse_unpinned_algorithm"}
_VERIFY_NAMES = {"_verify", "verify_token", "verify_oauth2_token"}
#: The one method that pins and then verifies. Every entry point that reads a claim must reach
#: the verifier through it and through nothing else.
_VERIFYING_HELPER = "_verified_claims"
#: The adapter's entry points: the reviewer path and the service intake behind the IAP edge.
_ENTRY_POINTS = ("resolve", "verify_service_assertion")


def _method(tree: ast.AST, name: str) -> ast.FunctionDef:
    return next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _call_lines(function: ast.FunctionDef, names: set[str]) -> list[int]:
    return [
        node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id in names)
            or (isinstance(node.func, ast.Attribute) and node.func.attr in names)
        )
    ]


def test_the_algorithm_is_pinned_before_the_verifier_runs() -> None:
    """Read off the source: the pin precedes verification on every path that reads a claim.

    A pin that runs after the token was verified never protected the verifier, and a test that
    only checks the pin is PRESENT cannot tell those apart. The walk records the source line of
    the first algorithm-pin call and of the first verification call inside the verifying helper,
    and compares them. It then requires each entry point to reach the verifier ONLY through that
    helper: an entry point that called ``_verify`` itself would skip the pin, and this test would
    otherwise still pass.
    """
    tree = ast.parse(inspect.getsource(_adapter_module()))
    helper = _method(tree, _VERIFYING_HELPER)
    pins = _call_lines(helper, _PIN_NAMES)
    verifies = _call_lines(helper, _VERIFY_NAMES)
    assert pins, f"{_VERIFYING_HELPER}() never pins the signature algorithm"
    assert verifies, f"{_VERIFYING_HELPER}() never verifies the assertion"
    assert min(pins) < min(verifies), (
        f"the algorithm pin is called at line {min(pins)} and the verifier at line "
        f"{min(verifies)}. A pin after verification never protected the verifier."
    )
    for entry in _ENTRY_POINTS:
        method = _method(tree, entry)
        assert _call_lines(method, {_VERIFYING_HELPER}), (
            f"{entry}() does not verify through {_VERIFYING_HELPER}(), so nothing here shows "
            "it pins the algorithm first"
        )
        assert not _call_lines(method, _VERIFY_NAMES), (
            f"{entry}() calls a verifier directly, bypassing the pin in {_VERIFYING_HELPER}()"
        )


def test_the_transport_facts_are_the_commons_values() -> None:
    """The header, the issuer and the key set are REBOUND from the kit, not re-declared.

    These three strings were copied into every repository that verifies an IAP assertion,
    which is fifty-four chances for one of them to be edited alone. Asserting them against the
    kit means a local re-declaration that drifts fails here rather than in a deployment.
    """
    from review_console.adapters.gcp import identity

    assert identity._IAP_ASSERTION_HEADER == kit_federation.IAP_ASSERTION_HEADER
    assert identity._IAP_ISSUER == kit_federation.IAP_ISSUER
    assert identity._IAP_KEYS_URL == kit_federation.IAP_KEYS_URL
