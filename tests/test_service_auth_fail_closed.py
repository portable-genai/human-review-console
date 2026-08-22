"""An UNSET ``REVIEW_PROFILE`` must not authenticate an S2S caller by omission.

The persona half of this fail-open was closed in the identity adapter, but the SAME class
survived at a second site: ``api/app.py`` re-derived the profile with its own
``os.environ.get("REVIEW_PROFILE", "local")``, so an unset variable was read as consent to the
local profile, and the local profile selects the shared-secret S2S path, which is OPEN when the
secret is unset. The executed attack was an unauthenticated ``POST /v1/service/reviews``
returning 201 with an attacker-chosen ``maker`` and ``tenant``: a forged item in the
maker-checker queue of a control plane.

These tests run the app in a SUBPROCESS with the variable genuinely absent. The app reads the
profile at import time and the test session's ``conftest`` sets ``REVIEW_PROFILE=local`` for
every other test, so an in-process monkeypatch would assert against an already-imported module.

The probe declares a LOOPBACK ASGI peer. What is under test here is the S2S dependency's
refusal and the header posture of an unconfigured run, and the exposure guard now (correctly)
refuses an unconsented profile to any NON-loopback peer before either of those runs. Starlette's
default test peer is the literal ``"testclient"``, which is not loopback, so leaving it implicit
would replace both assertions with a 503 from a different layer and quietly stop testing the
layer this file is named for. ``tests/test_serving_path_exposure.py`` is where the LAN peer
belongs.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"

_PROBE = """
import json, os, sys
for name in (
    "REVIEW_PROFILE",
    "REVIEW_S2S_TOKEN",
    "REVIEW_S2S_ALLOWED_CALLERS",
    "REVIEW_S2S_AUDIENCE",
    "REVIEW_CORS_ORIGINS",
):
    os.environ.pop(name, None)
os.environ["REVIEW_DB_PATH"] = ":memory:"
os.environ["REVIEW_AUDIT_PATH"] = ":memory:"

from fastapi.testclient import TestClient
from review_console.api.app import app

client = TestClient(app, client=("127.0.0.1", 51234))
forged = {
    "maker": "attacker@evil.example",
    "tenant": "demo-bank",
    "action": "payout.release",
    "subject": "acct-4471",
    "summary": "forged submission with no bearer token",
    "severity": "high",
    "source_key": "attack-1",
}
submit = client.post("/v1/service/reviews", json=forged)
ping = client.post("/v1/audit/ping")
cors = [
    m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware"
][0]
print(json.dumps({
    "submit_status": submit.status_code,
    "ping_status": ping.status_code,
    "cors_origins": list(cors.kwargs["allow_origins"]),
    "cors_headers": list(cors.kwargs["allow_headers"]),
    "hsts": ping.headers.get("strict-transport-security", ""),
}))
"""


@pytest.fixture(scope="module")
def unset_profile_probe() -> dict[str, object]:
    """Exercise the committed app with ``REVIEW_PROFILE`` and ``REVIEW_S2S_TOKEN`` both absent."""
    result = subprocess.run(  # noqa: S603 - fixed argv, this interpreter, in-repo source
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        cwd=_ROOT,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(_SRC)},
        check=False,
    )
    assert result.returncode == 0, f"probe failed:\n{result.stderr}"
    payload: dict[str, object] = json.loads(result.stdout.strip().splitlines()[-1])
    return payload


def test_an_unauthenticated_service_submission_is_refused_when_the_profile_is_unset(
    unset_profile_probe: dict[str, object],
) -> None:
    """The exact executed attack: no bearer token, no profile, must NOT create a review."""
    status_code = unset_profile_probe["submit_status"]
    assert status_code != 201, (
        "POST /v1/service/reviews accepted an unauthenticated forged maker/tenant while "
        "REVIEW_PROFILE was unset; an unset variable was read as consent"
    )
    assert status_code == 401


def test_the_other_service_endpoint_is_refused_on_the_same_decision(
    unset_profile_probe: dict[str, object],
) -> None:
    assert unset_profile_probe["ping_status"] == 401


def test_an_unset_profile_gets_no_cors_allowlist_and_no_dev_persona_header(
    unset_profile_probe: dict[str, object],
) -> None:
    assert unset_profile_probe["cors_origins"] == []
    assert "X-Dev-Persona" not in unset_profile_probe["cors_headers"]


def test_an_unset_profile_gets_the_non_local_security_header_posture(
    unset_profile_probe: dict[str, object],
) -> None:
    assert "max-age=31536000" in str(unset_profile_probe["hsts"])
