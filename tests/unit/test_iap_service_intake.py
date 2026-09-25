"""The service intake behind the portal's IAP edge authenticates the ORIGINAL caller.

A deployed producer reaches ``POST /v1/service/reviews`` through the portal's IAP edge: it sends
an ID token minted for the IAP OAuth client, IAP verifies it and hands the portal an assertion
naming the producer's service account, and the portal forwards that assertion as
``x-portal-iap-assertion`` while REPLACING ``Authorization`` with the portal's own service token.
Every browser request a signed-in reviewer makes through the portal carries that same portal
token. So behind the edge a bearer names the portal and nobody else, and an intake that accepted
it as a service caller let any reviewer POST a maker and tenant of their choosing into the
maker-checker queue.

Under the IAP profiles (``gcp``, ``platform``) the intake now verifies the forwarded assertion on
the identity adapter's own path and admits only the service accounts named in
``REVIEW_IAP_SERVICE_CALLERS_JSON``. Only the signature check is stubbed here; the header
selection, algorithm pin, audience, issuer and claim-set checks all run for real.
"""

from __future__ import annotations

import base64
import importlib
import json
import subprocess
import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hex_service_kit.federation import IAP_ISSUER
from hex_service_kit.identity import IdentityError
from hex_service_kit.netdefaults import ConfiguredEmptyError

from review_console.adapters.gcp.identity import IapIdentityAdapter
from review_console.api.app import app
from review_console.config import (
    IAP_EDGE_PROFILES,
    IAP_SERVICE_CALLERS_ENV,
    ProfileChoice,
    Settings,
    build_container,
    iap_service_callers,
)
from review_console.domain.console_service import ConsoleService

# The MODULE, not the FastAPI object: ``review_console.api`` re-exports ``app`` under the same name.
app_module = importlib.import_module("review_console.api.app")

_ROOT = Path(__file__).resolve().parents[2]
_AUDIENCE = "/projects/1234567890/global/backendServices/42"
_PRODUCER = "aml-alert-triage@example-project.iam.gserviceaccount.com"
_OTHER_SA = "unreviewed-job@example-project.iam.gserviceaccount.com"
_PORTAL_SA = "journey-portal@example-project.iam.gserviceaccount.com"
_HUMAN = "avery.stone@example-bank.test"

_FORGED = {
    "maker": "attacker@evil.example",
    "tenant": "reference-bank",
    "action": "payout.release",
    "subject": "acct-4471",
    "summary": "submitted through the portal edge",
    "severity": "high",
    "source_key": "edge-1",
}


def _b64(value: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


def _assertion(email: str, *, alg: str = "RS256", signature: str = "c2ln", **claims: Any) -> str:
    """A structurally real compact JWS whose payload the stubbed verifier returns."""
    payload: dict[str, Any] = {
        "iss": IAP_ISSUER,
        "aud": _AUDIENCE,
        "sub": f"accounts.google.com:{abs(hash(email))}",
        "email": email,
        "exp": 4102444800,
    }
    payload.update(claims)
    return f"{_b64({'alg': alg, 'typ': 'JWT'})}.{_b64(payload)}.{signature}"


#: The portal's own service token, as it arrives on EVERY request the portal forwards. A
#: structurally real RS256 JWS, so the old bearer path's algorithm pin would pass it to the
#: verifier rather than refusing it for being malformed.
_PORTAL_BEARER = _assertion(_PORTAL_SA)


def _fake_verify(assertion: str) -> dict[str, Any]:
    """Stand-in for Google's signature check: a signature of ``bad`` does not verify."""
    header_b64, payload_b64, signature = assertion.split(".")
    if signature == "bad":
        raise IdentityError("IAP assertion verification failed: signature mismatch")
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    return dict(json.loads(base64.urlsafe_b64decode(padded)))


def _iap_adapter(audience: str = _AUDIENCE) -> IapIdentityAdapter:
    adapter = IapIdentityAdapter(Settings(profile="gcp", iap_audience=audience))
    object.__setattr__(adapter, "_verify", _fake_verify)
    return adapter


@pytest.fixture
def console() -> ConsoleService:
    return build_container(Settings(profile="local")).console


@pytest.fixture
def edge(monkeypatch: pytest.MonkeyPatch, console: ConsoleService) -> Iterator[TestClient]:
    """The app as deployed behind the edge: ``gcp`` profile, IAP adapter, one reviewed caller."""
    monkeypatch.setattr(app.state, "profile_choice", ProfileChoice(profile="gcp", explicit=True))
    monkeypatch.setattr(app.state, "iap_service_callers", frozenset({_PRODUCER}), raising=False)
    monkeypatch.setattr(app_module, "_identity", _iap_adapter)
    monkeypatch.setattr(app_module, "_console", lambda: console)
    for name in ("REVIEW_S2S_TOKEN", "REVIEW_S2S_AUDIENCE", "REVIEW_S2S_ALLOWED_CALLERS"):
        monkeypatch.delenv(name, raising=False)
    yield TestClient(app, client=("127.0.0.1", 51234))


def _through_portal(email: str | None, **assertion_kw: Any) -> dict[str, str]:
    """The headers the portal forwards: ITS bearer, plus the edge's assertion when there is one."""
    headers = {"Authorization": f"Bearer {_PORTAL_BEARER}"}
    if email is not None:
        headers["x-portal-iap-assertion"] = _assertion(email, **assertion_kw)
    return headers


# --------------------------------------------------------------------------------------------- #
# Who is admitted
# --------------------------------------------------------------------------------------------- #
def test_an_allowlisted_machine_caller_is_accepted_through_the_portal(
    edge: TestClient, console: ConsoleService
) -> None:
    resp = edge.post("/v1/service/reviews", json=_FORGED, headers=_through_portal(_PRODUCER))
    assert resp.status_code == 201, resp.text
    assert resp.json()["maker"] == _FORGED["maker"]
    assert [item.request.subject for item in console.list_queue("reference-bank")] == ["acct-4471"]


def test_the_edge_injected_header_takes_the_same_path(edge: TestClient) -> None:
    resp = edge.post(
        "/v1/service/reviews",
        json=_FORGED,
        headers={"x-goog-iap-jwt-assertion": _assertion(_PRODUCER)},
    )
    assert resp.status_code == 201, resp.text


def test_the_allowlist_match_ignores_address_case(edge: TestClient) -> None:
    resp = edge.post(
        "/v1/service/reviews", json=_FORGED, headers=_through_portal(_PRODUCER.upper())
    )
    assert resp.status_code == 201, resp.text


def test_a_signed_in_human_is_refused_403_naming_the_allowlist(
    edge: TestClient, console: ConsoleService
) -> None:
    resp = edge.post(
        "/v1/service/reviews",
        json=_FORGED,
        headers=_through_portal(_HUMAN, hd="example-bank.test"),
    )
    assert resp.status_code == 403, resp.text
    assert IAP_SERVICE_CALLERS_ENV in resp.json()["detail"]
    assert _HUMAN in resp.json()["detail"]
    assert console.list_queue("reference-bank") == []


def test_a_service_account_the_allowlist_does_not_name_is_refused_403(edge: TestClient) -> None:
    resp = edge.post("/v1/service/reviews", json=_FORGED, headers=_through_portal(_OTHER_SA))
    assert resp.status_code == 403, resp.text
    assert "which does not name it" in resp.json()["detail"]


def test_the_portal_service_account_itself_is_not_a_machine_caller(edge: TestClient) -> None:
    resp = edge.post("/v1/service/reviews", json=_FORGED, headers=_through_portal(_PORTAL_SA))
    assert resp.status_code == 403, resp.text


def test_an_unset_allowlist_refuses_every_caller(
    edge: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app.state, "iap_service_callers", frozenset(), raising=False)
    resp = edge.post("/v1/service/reviews", json=_FORGED, headers=_through_portal(_PRODUCER))
    assert resp.status_code == 403, resp.text
    assert "unset, so no machine caller is admitted" in resp.json()["detail"]


# --------------------------------------------------------------------------------------------- #
# What does not authenticate
# --------------------------------------------------------------------------------------------- #
def test_no_assertion_is_401(edge: TestClient, console: ConsoleService) -> None:
    resp = edge.post("/v1/service/reviews", json=_FORGED, headers=_through_portal(None))
    assert resp.status_code == 401, resp.text
    assert console.list_queue("reference-bank") == []


def test_an_assertion_that_does_not_verify_is_401(edge: TestClient) -> None:
    resp = edge.post(
        "/v1/service/reviews", json=_FORGED, headers=_through_portal(_PRODUCER, signature="bad")
    )
    assert resp.status_code == 401, resp.text


def test_an_unsigned_assertion_is_401_before_any_verifier_runs(edge: TestClient) -> None:
    resp = edge.post(
        "/v1/service/reviews", json=_FORGED, headers=_through_portal(_PRODUCER, alg="none")
    )
    assert resp.status_code == 401, resp.text


def test_an_assertion_for_another_audience_is_401(edge: TestClient) -> None:
    resp = edge.post(
        "/v1/service/reviews",
        json=_FORGED,
        headers=_through_portal(_PRODUCER, aud="/projects/1/global/backendServices/other"),
    )
    assert resp.status_code == 401, resp.text


def test_an_assertion_from_another_issuer_is_401(edge: TestClient) -> None:
    resp = edge.post(
        "/v1/service/reviews",
        json=_FORGED,
        headers=_through_portal(_PRODUCER, iss="https://accounts.google.com"),
    )
    assert resp.status_code == 401, resp.text


def _install_accepting_oidc_verifier(monkeypatch: pytest.MonkeyPatch, email: str) -> None:
    """A Google SDK whose ID-token check accepts any bearer as ``email``.

    This is the most generous reading of the portal's bearer there is: a real Google-signed ID
    token for the portal's own service account, with the old S2S policy configured to admit it.
    """
    claims = {"iss": "https://accounts.google.com", "sub": "1", "exp": 4102444800}
    id_token = types.ModuleType("google.oauth2.id_token")
    id_token.verify_oauth2_token = lambda token, request, audience: {  # type: ignore[attr-defined]
        **claims,
        "aud": audience,
        "email": email,
    }
    requests_mod = types.ModuleType("google.auth.transport.requests")
    requests_mod.Request = lambda: None  # type: ignore[attr-defined]
    google = types.ModuleType("google")
    oauth2 = types.ModuleType("google.oauth2")
    auth = types.ModuleType("google.auth")
    transport = types.ModuleType("google.auth.transport")
    oauth2.id_token = id_token  # type: ignore[attr-defined]
    transport.requests = requests_mod  # type: ignore[attr-defined]
    auth.transport = transport  # type: ignore[attr-defined]
    google.oauth2 = oauth2  # type: ignore[attr-defined]
    google.auth = auth  # type: ignore[attr-defined]
    for name, module in {
        "google": google,
        "google.oauth2": oauth2,
        "google.oauth2.id_token": id_token,
        "google.auth": auth,
        "google.auth.transport": transport,
        "google.auth.transport.requests": requests_mod,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setenv("REVIEW_S2S_AUDIENCE", "https://review-console.example")
    monkeypatch.setenv("REVIEW_S2S_ALLOWED_CALLERS", email)


def test_the_portal_bearer_alone_is_refused_even_when_it_verifies(
    edge: TestClient, monkeypatch: pytest.MonkeyPatch, console: ConsoleService
) -> None:
    _install_accepting_oidc_verifier(monkeypatch, _PORTAL_SA)
    resp = edge.post("/v1/service/reviews", json=_FORGED, headers=_through_portal(None))
    assert resp.status_code == 401, resp.text
    assert console.list_queue("reference-bank") == []


def test_a_human_behind_a_verifying_portal_bearer_is_still_refused(
    edge: TestClient, monkeypatch: pytest.MonkeyPatch, console: ConsoleService
) -> None:
    """The executed forgery: a reviewer's browser request carries the portal's token."""
    _install_accepting_oidc_verifier(monkeypatch, _PORTAL_SA)
    resp = edge.post("/v1/service/reviews", json=_FORGED, headers=_through_portal(_HUMAN))
    assert resp.status_code == 403, resp.text
    assert console.list_queue("reference-bank") == []


def test_an_unconfigured_audience_is_503_not_a_caller_fault(
    edge: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "_identity", lambda: _iap_adapter(audience=""))
    resp = edge.post("/v1/service/reviews", json=_FORGED, headers=_through_portal(_PRODUCER))
    assert resp.status_code == 503, resp.text
    assert "REVIEW_IAP_AUDIENCE" in resp.json()["detail"]


def test_the_platform_profile_takes_the_same_path(
    edge: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert frozenset({"gcp", "platform"}) == IAP_EDGE_PROFILES
    monkeypatch.setattr(
        app.state, "profile_choice", ProfileChoice(profile="platform", explicit=True)
    )
    assert (
        edge.post("/v1/service/reviews", json=_FORGED, headers=_through_portal(_HUMAN)).status_code
        == 403
    )
    assert (
        edge.post(
            "/v1/service/reviews", json=_FORGED, headers=_through_portal(_PRODUCER)
        ).status_code
        == 201
    )


def test_the_audit_ping_shares_the_decision(edge: TestClient) -> None:
    assert edge.post("/v1/audit/ping", headers=_through_portal(_HUMAN)).status_code == 403
    assert edge.post("/v1/audit/ping", headers=_through_portal(_PRODUCER)).status_code == 200


def test_the_local_profile_keeps_the_shared_secret_path_and_ignores_assertions(
    monkeypatch: pytest.MonkeyPatch, console: ConsoleService
) -> None:
    monkeypatch.setattr(app_module, "_console", lambda: console)
    monkeypatch.setattr(app.state, "iap_service_callers", frozenset({_PRODUCER}), raising=False)
    monkeypatch.setenv("REVIEW_S2S_TOKEN", "shared-secret")
    client = TestClient(app, client=("127.0.0.1", 51234))
    refused = client.post(
        "/v1/service/reviews",
        json=_FORGED,
        headers={"x-portal-iap-assertion": _assertion(_PRODUCER)},
    )
    assert refused.status_code == 401
    accepted = client.post(
        "/v1/service/reviews",
        json=_FORGED,
        headers={"Authorization": "Bearer shared-secret"},
    )
    assert accepted.status_code == 201, accepted.text


# --------------------------------------------------------------------------------------------- #
# REVIEW_IAP_SERVICE_CALLERS_JSON in three states
# --------------------------------------------------------------------------------------------- #
def test_unset_admits_no_machine_caller() -> None:
    assert iap_service_callers({}) == frozenset()


@pytest.mark.parametrize("raw", ["", "   "])
def test_emptied_is_refused(raw: str) -> None:
    with pytest.raises(ConfiguredEmptyError, match=IAP_SERVICE_CALLERS_ENV):
        iap_service_callers({IAP_SERVICE_CALLERS_ENV: raw})


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        f'"{_PRODUCER}"',
        f'{{"{_PRODUCER}": true}}',
        "[]",
        f'["{_PRODUCER}", ""]',
        f'["{_PRODUCER}", 7]',
        f'["{_HUMAN}"]',
        '["*@example-project.iam.gserviceaccount.com"]',
    ],
)
def test_malformed_is_refused(raw: str) -> None:
    with pytest.raises(ValueError, match=IAP_SERVICE_CALLERS_ENV):
        iap_service_callers({IAP_SERVICE_CALLERS_ENV: raw})


def test_set_is_the_exact_lower_cased_service_accounts() -> None:
    raw = json.dumps([_PRODUCER.upper(), f" {_OTHER_SA} "])
    assert iap_service_callers({IAP_SERVICE_CALLERS_ENV: raw}) == frozenset({_PRODUCER, _OTHER_SA})


@pytest.mark.parametrize(("raw", "reason"), [("", "empty value"), ("[oops", "not valid JSON")])
def test_the_app_refuses_to_boot_on_an_emptied_or_malformed_allowlist(
    raw: str, reason: str
) -> None:
    probe = "import review_console.api.app"
    result = subprocess.run(  # noqa: S603 - fixed argv, this interpreter, in-repo source
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd=_ROOT,
        env={
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(_ROOT / "src"),
            "REVIEW_PROFILE": "gcp",
            IAP_SERVICE_CALLERS_ENV: raw,
        },
        check=False,
    )
    assert result.returncode != 0
    assert IAP_SERVICE_CALLERS_ENV in result.stderr
    assert reason in result.stderr
