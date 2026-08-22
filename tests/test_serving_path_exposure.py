"""The residual limit must be enforced where the service actually serves, not in ``main()``.

Five documents bounded the zero-secret S2S opening with "the loopback bind guard". That guard
is one call to ``hex_service_kit.netdefaults.resolve_bind_host`` inside
``review_console.api.app.main()``, and NOTHING ships that entry point: the Dockerfile ``CMD``
and the ``make run-api`` target both run ``uvicorn review_console.api.app:app``, which imports
the app object and never calls ``main``. The executed attack, with ``REVIEW_S2S_TOKEN`` unset
and ``REVIEW_PROFILE=local``, was ``uvicorn ... --host 0.0.0.0`` plus a POST to
``/v1/service/reviews`` from another host on the LAN: 201 CREATED, ``maker`` and ``tenant``
attacker-chosen, a forged maker-checker item with no token.

Two further holes were executed alongside it:

* the limit named ``REVIEW_PROFILE=local``, but ``onprem`` (a valid profile) also took the
  shared-secret path, which is open when the secret is unset: ``POST /v1/audit/ping`` answered
  200 unauthenticated;
* an INVALID profile value never reached validation, because ``Settings`` is only built at
  request time. ``REVIEW_PROFILE=bogus`` and the capitalisation typo ``REVIEW_PROFILE=Local``
  both served, and both bound ``0.0.0.0``.

The profile is read at IMPORT time, so every profile-dependent case here runs the committed app
in a SUBPROCESS with the real environment rather than monkeypatching an imported module.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from review_console.api.app import app

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"

_FORGED = {
    "maker": "attacker@evil.example",
    "tenant": "demo-bank",
    "action": "payout.release",
    "subject": "acct-4471",
    "summary": "forged submission from a LAN peer, no bearer token",
    "severity": "high",
    "source_key": "lan-attack-1",
}


# --------------------------------------------------------------------------- #
# The executed attack: a non-loopback peer against the no-auth posture
# --------------------------------------------------------------------------- #
def test_a_lan_peer_cannot_forge_a_maker_checker_item(monkeypatch: pytest.MonkeyPatch) -> None:
    """The exact executed attack, against the app object uvicorn is pointed at."""
    monkeypatch.delenv("REVIEW_ALLOW_INSECURE_DEMO", raising=False)
    client = TestClient(app, client=("192.168.1.37", 51234))
    resp = client.post("/v1/service/reviews", json=_FORGED)
    assert resp.status_code != 201, (
        "an off-loopback caller created a review with an attacker-chosen maker and tenant; the "
        "loopback bound is claimed by five documents but enforced only in main()"
    )
    assert resp.status_code == 503
    assert "loopback" in resp.json()["detail"]


def test_the_same_bound_covers_the_browser_facing_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Seeded personas are the whole authentication story under ``local``, so the bound is
    about exposure of the service, not about the S2S routes alone."""
    monkeypatch.delenv("REVIEW_ALLOW_INSECURE_DEMO", raising=False)
    client = TestClient(app, client=("10.1.2.3", 40000))
    assert client.get("/healthz").status_code == 503
    assert client.get("/v1/queue").status_code == 503


def test_a_loopback_peer_still_gets_the_offline_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REVIEW_ALLOW_INSECURE_DEMO", raising=False)
    client = TestClient(app, client=("127.0.0.1", 51234))
    assert client.post("/v1/service/reviews", json=_FORGED).status_code == 201


def test_the_documented_opt_out_is_the_only_way_to_expose_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REVIEW_ALLOW_INSECURE_DEMO", "1")
    client = TestClient(app, client=("192.168.1.37", 51234))
    assert client.post("/v1/service/reviews", json=_FORGED).status_code == 201


def test_the_shipped_entry_points_serve_the_app_object_not_main() -> None:
    """Why the guard cannot live in ``main()``: nothing shipped calls it."""
    dockerfile = (_ROOT / "Dockerfile").read_text(encoding="utf-8")
    makefile = (_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "uvicorn review_console.api.app:app" in dockerfile
    assert "uvicorn review_console.api.app:app" in makefile


# --------------------------------------------------------------------------- #
# Profile values: valid-but-not-local, invalid, and a capitalisation typo
# --------------------------------------------------------------------------- #
_PROBE = f"""
import json, os
for name in ("REVIEW_S2S_TOKEN", "REVIEW_S2S_ALLOWED_CALLERS", "REVIEW_S2S_AUDIENCE"):
    os.environ.pop(name, None)
os.environ["REVIEW_DB_PATH"] = ":memory:"
os.environ["REVIEW_AUDIT_PATH"] = ":memory:"

from fastapi.testclient import TestClient
from review_console.api.app import app

client = TestClient(app, client=("127.0.0.1", 51234))
print(json.dumps({{
    "ping_status": client.post("/v1/audit/ping").status_code,
    "submit_status": client.post("/v1/service/reviews", json={_FORGED!r}).status_code,
}}))
"""


def _probe(profile: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, this interpreter, in-repo source
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        cwd=_ROOT,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(_SRC), "REVIEW_PROFILE": profile},
        check=False,
    )


def test_a_valid_but_non_local_profile_is_not_unauthenticated() -> None:
    """Executed: ``REVIEW_PROFILE=onprem`` with no token answered POST /v1/audit/ping with 200."""
    result = _probe("onprem")
    assert result.returncode == 0, f"probe failed:\n{result.stderr}"
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["ping_status"] != 200, (
        "onprem took the shared-secret path, which is open when REVIEW_S2S_TOKEN is unset: the "
        "stated limit named only 'local' but every non-secure profile inherited the opening"
    )
    assert payload["ping_status"] == 503
    assert payload["submit_status"] != 201


# --------------------------------------------------------------------------- #
# The bound is derived from the IDENTITY BINDING, so a service credential cannot lift it
# --------------------------------------------------------------------------- #
# The second executed attack. The guard's posture used to require "... and REVIEW_S2S_TOKEN is
# unset", so SETTING a service credential switched the bound off for the END-USER routes it was
# protecting. With REVIEW_PROFILE=local chosen deliberately, the token set and uvicorn bound to
# 0.0.0.0, a peer at another address on the LAN with no Authorization header POSTed /v1/reviews
# as ``demo.approver@bank.example`` in tenant ``demo-bank``, read that tenant's queue back, and
# signed off a second item as the checker: four-eyes, the control this service exists to
# enforce, defeated with no credential at all.
#
# Every cell below is run in a SUBPROCESS with the real environment, because the profile and the
# posture are resolved at import; monkeypatching an already-imported module would test a
# configuration the shipped process can never be in.
_LAN_PROBE = """
import json, os
os.environ["REVIEW_DB_PATH"] = ":memory:"
os.environ["REVIEW_AUDIT_PATH"] = ":memory:"

from fastapi.testclient import TestClient
from review_console.api.app import app

client = TestClient(app, client=("192.168.1.37", 51234))
persona = {"X-Dev-Persona": "approver"}
submit = {
    "action": "payout.release",
    "subject": "acct-4471",
    "summary": "forged by a LAN peer holding no credential",
    "severity": "high",
}
print(json.dumps({
    "healthz": client.get("/healthz").status_code,
    "personas": client.get("/v1/personas", headers=persona).status_code,
    "queue": client.get("/v1/reviews", headers=persona).status_code,
    "workflows": client.get("/v1/workflows", headers=persona).status_code,
    "submit": client.post("/v1/reviews", json=submit, headers=persona).status_code,
}))
"""


def _lan_probe(profile: str | None, token: str | None) -> dict[str, int]:
    """Every route a LAN peer can reach, under ``profile`` with ``token``, as {name: status}."""
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(_SRC)}
    if profile is not None:
        env["REVIEW_PROFILE"] = profile
    if token is not None:
        env["REVIEW_S2S_TOKEN"] = token
    result = subprocess.run(  # noqa: S603 - fixed argv, this interpreter, in-repo source
        [sys.executable, "-c", _LAN_PROBE],
        capture_output=True,
        text=True,
        cwd=_ROOT,
        env=env,
        check=False,
    )
    assert result.returncode == 0, f"probe failed:\n{result.stderr}"
    statuses: dict[str, int] = json.loads(result.stdout.strip().splitlines()[-1])
    return statuses


def test_setting_the_service_token_does_not_lift_the_bound() -> None:
    """The executed defect, as a regression guard.

    An assertion reading "setting a token lifts the bound because callers are then
    authenticated" would PIN the fail-open: a green test asserting it, so a repo owner who
    closed the guard would break the build. The token
    authenticates a calling SERVICE. It authenticates no end user, and the routes below are
    end-user routes.
    """
    statuses = _lan_probe("local", "not-a-real-secret")
    assert statuses["submit"] != 201, (
        "a LAN peer with no credential created a maker-checker item as the seeded approver "
        "persona: setting REVIEW_S2S_TOKEN switched off the bound on the END-USER routes, which "
        "that credential has nothing to say about"
    )
    assert set(statuses.values()) == {503}, statuses


def test_the_zero_secret_posture_stays_bounded_as_well() -> None:
    """The zero-secret cell the guard covers, pinned so no other rule narrows the bound."""
    assert set(_lan_probe("local", None).values()) == {503}


def test_an_unconsented_profile_is_bounded_too() -> None:
    """Unset is not consent, whatever else is configured.

    With REVIEW_PROFILE absent ``service_auth_configured`` is False, and EXCLUDING that run
    from the guard's posture answers a LAN peer 200 on ``/healthz`` and the whole workflow
    catalogue, on a deployment nobody has configured at all.
    """
    assert set(_lan_probe(None, "not-a-real-secret").values()) == {503}


def test_the_onprem_placeholder_is_bounded_too() -> None:
    """A binding that resolves NOBODY cannot authenticate an end user, so it is confined.

    A guard that looks only at ``local`` answers a LAN peer 200 under ``REVIEW_PROFILE=onprem``
    on ``/healthz``, ``/v1/personas`` and ``/v1/workflows``, and 500 on the end-user routes. An
    adopter who binds a verifying IdP adapter under ``_IDENTITY_BINDINGS['onprem']`` lifts this
    bound by that fact alone.
    """
    assert set(_lan_probe("onprem", "not-a-real-secret").values()) == {503}


def test_a_verifying_identity_binding_stands_the_guard_DOWN() -> None:
    """The control, without which "everything refuses" is satisfied by an always-on guard.

    ``gcp`` binds the IAP adapter, which verifies a signed assertion before reading a claim, so
    the guard steps aside and the ROUTES do the refusing: a fronted deployment stays
    health-checkable while every end-user route answers 401 to a peer with no assertion.
    """
    statuses = _lan_probe("gcp", "not-a-real-secret")
    assert statuses["healthz"] == 200, "a fronted deployment must stay health-checkable"
    assert statuses["personas"] == 200, "no seeded personas exist outside the local profile"
    assert statuses["queue"] == 401, "no IAP assertion, so no principal, so no queue"
    assert statuses["submit"] == 401, "no IAP assertion, so nothing enters the queue"


_IMPORT_PROBE = """
import os
os.environ["REVIEW_DB_PATH"] = ":memory:"
os.environ["REVIEW_AUDIT_PATH"] = ":memory:"
from review_console.api.app import app
print("imported")
"""


@pytest.mark.parametrize("profile", ["bogus", "Local", "GCP", "LOCAL"])
def test_an_unknown_profile_value_refuses_to_boot(profile: str) -> None:
    """An unknown value, including a capitalisation typo, must fail at BOOT, not at the first
    request that happens to build the container, and must never produce a serving app."""
    result = subprocess.run(  # noqa: S603 - fixed argv, this interpreter, in-repo source
        [sys.executable, "-c", _IMPORT_PROBE],
        capture_output=True,
        text=True,
        cwd=_ROOT,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(_SRC), "REVIEW_PROFILE": profile},
        check=False,
    )
    assert result.returncode != 0, (
        f"REVIEW_PROFILE={profile!r} produced a serving app; profile validation ran only when "
        "the container was first built at request time, so an invalid value never failed closed"
    )
    assert "REVIEW_PROFILE" in result.stderr
    assert "imported" not in result.stdout


# --------------------------------------------------------------------------- #
# The secure profile: the S2S check must not authenticate on an unset policy
# --------------------------------------------------------------------------- #
def test_the_secure_profile_refuses_an_unconfigured_service_identity_policy() -> None:
    """With ``REVIEW_S2S_AUDIENCE`` and ``REVIEW_S2S_ALLOWED_CALLERS`` both unset (nothing sets
    them: not the Terraform, not any doc), the pinned commons asked google-auth to verify with
    ``audience=None``, which skips the ``aud`` check, and matched the caller against an empty
    allowlist, which admits everyone. The application-layer S2S check contributed nothing."""
    result = _probe("gcp")
    assert result.returncode == 0, f"probe failed:\n{result.stderr}"
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["submit_status"] == 503
    assert payload["ping_status"] == 503
