"""D4 (hardened container) and C6 (security-header baseline) asserted from the offline gate.

These read the shipped Dockerfile and the UI header module rather than a running container or a
running browser: the offline gate has neither. They are drift guards over the posture, and the
UI half is paired with a behavioral unit test of the same builder in
``ui/scripts/security-headers.test.mjs`` and, for the part no string assertion can decide, by
``ui/scripts/assert-hydratable.mjs`` (both run by ``make ui-check`` and CI).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from hex_service_kit.netdefaults import EnvSetting

_ROOT = Path(__file__).resolve().parents[1]
_DOCKERFILE = (_ROOT / "Dockerfile").read_text(encoding="utf-8")
_HEADERS_MODULE = (_ROOT / "ui" / "lib" / "security-headers.mjs").read_text(encoding="utf-8")
_NEXT_CONFIG = (_ROOT / "ui" / "next.config.mjs").read_text(encoding="utf-8")
_PROXY = (_ROOT / "ui" / "proxy.ts").read_text(encoding="utf-8")
_LAYOUT = (_ROOT / "ui" / "app" / "layout.tsx").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# D4: multi-stage, non-root, healthchecked
# --------------------------------------------------------------------------- #
def _stages() -> list[str]:
    return re.findall(r"^FROM\s+\S+\s+AS\s+(\w+)", _DOCKERFILE, flags=re.MULTILINE)


def test_the_image_is_multi_stage_with_a_separate_runtime() -> None:
    stages = _stages()
    assert len(stages) >= 2, f"expected a builder and a runtime stage, found {stages}"
    assert stages[-1] == "runtime"
    assert "COPY --from=builder /opt/venv /opt/venv" in _DOCKERFILE


def test_the_build_toolchain_never_reaches_the_runtime_stage() -> None:
    runtime_stage = _DOCKERFILE.split("AS runtime", 1)[1]
    assert "apt-get install" not in runtime_stage
    assert "git" not in runtime_stage
    assert "pip install" not in runtime_stage


def test_the_image_runs_as_a_dedicated_non_root_user() -> None:
    users = re.findall(r"^USER\s+(\S+)", _DOCKERFILE, flags=re.MULTILINE)
    assert users and users[-1] == "app"
    assert "useradd --system" in _DOCKERFILE


def test_the_image_healthchecks_itself_against_the_real_endpoint() -> None:
    match = re.search(r"^HEALTHCHECK(.*?)^CMD", _DOCKERFILE, flags=re.MULTILINE | re.DOTALL)
    assert match is not None, "the Dockerfile declares no HEALTHCHECK"
    healthcheck = match.group(1)
    assert "/healthz" in healthcheck
    assert "--interval" in healthcheck and "--retries" in healthcheck
    assert "EXPOSE 8087" in _DOCKERFILE


def test_the_healthchecked_endpoint_exists_and_answers() -> None:
    """The HEALTHCHECK above is only real if /healthz is served; prove it, do not assume it."""
    from review_console.api.app import app

    # A loopback peer: the container's own HEALTHCHECK curls 127.0.0.1, and the app object's
    # exposure guard refuses Starlette's default non-loopback ``testclient`` peer.
    with TestClient(app, client=("127.0.0.1", 51234)) as client:
        response = client.get("/healthz")
    assert response.status_code == 200


# --------------------------------------------------------------------------- #
# C6: the document CSP is complete, and the API keeps its own baseline
# --------------------------------------------------------------------------- #
def test_the_ui_policy_is_default_deny_with_every_required_directive() -> None:
    for directive in (
        "default-src 'self'",
        "script-src ",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src ",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors ",
    ):
        assert directive in _HEADERS_MODULE, f"UI CSP is missing {directive!r}"
    assert "Strict-Transport-Security" in _HEADERS_MODULE
    assert "max-age=31536000; includeSubDomains" in _HEADERS_MODULE
    assert "X-Content-Type-Options" in _HEADERS_MODULE
    assert "Referrer-Policy" in _HEADERS_MODULE


def test_the_connect_src_is_scoped_to_the_configured_api_origin() -> None:
    # Only the ORIGIN of the configured API base may widen connect-src, never a wildcard.
    assert "new URL(apiBaseUrl).origin" in _HEADERS_MODULE
    # The builder BODY only: the surrounding JSDoc is full of asterisks and says nothing about
    # what the policy emits.
    builder = _HEADERS_MODULE.split("export function contentSecurityPolicy", 1)[1]
    builder = builder.split("\n}\n", 1)[0]
    assert "*" not in builder, "the header builder must never widen a directive to a wildcard"


def test_the_csp_is_emitted_by_exactly_one_layer() -> None:
    """Two layers emitting a CSP is the defect, not a belt-and-braces.

    The browser intersects the policies it is given and the stricter directive wins, per
    directive, so a leftover static CSP would quietly re-impose the un-nonced ``script-src`` on a
    console whose scripts now carry a nonce and nothing else.
    """
    code = "\n".join(
        line for line in _NEXT_CONFIG.splitlines() if not line.lstrip().startswith("//")
    )
    assert "Content-Security-Policy" not in code
    assert "X-Frame-Options" not in code
    assert "staticSecurityHeaders" in _NEXT_CONFIG
    assert "documentSecurityHeaders" in _PROXY


def test_the_document_policy_carries_a_per_request_nonce_and_no_inline_escape() -> None:
    """script-src takes a nonce plus strict-dynamic, and never 'unsafe-inline'.

    Shipping ``script-src 'self' 'unsafe-inline'`` with a comment calling the inline allowance
    an unavoidable limit of Next.js is wrong: it is avoidable with a per-request nonce, which a
    static ``headers()`` table cannot express, which is why the policy lives in ``proxy.ts``.
    """
    assert "'strict-dynamic'" in _HEADERS_MODULE
    assert "`'nonce-${nonce}'`" in _HEADERS_MODULE
    script_src = _HEADERS_MODULE.split("const script = nonce", 1)[1].split("return [", 1)[0]
    assert "unsafe-inline" not in script_src
    assert "generateNonce()" in _PROXY
    # Both header sets are load-bearing: the REQUEST header is where Next reads the nonce it
    # stamps onto its script tags, the RESPONSE header is what the browser enforces.
    assert 'requestHeaders.set("Content-Security-Policy"' in _PROXY
    assert "response.headers.set(name, value)" in _PROXY


def test_the_nonce_route_is_actually_rendered_dynamically() -> None:
    """A nonce on a statically prerendered route blocks MORE than no nonce at all.

    Nothing in the prerendered HTML carries the per-request nonce, and ``'strict-dynamic'``
    switches off the ``'self'`` fallback that had at least been loading the chunk scripts. The
    build refuses this combination; ``ui/scripts/assert-hydratable.mjs`` proves the served bytes.
    """
    assert 'export const dynamic = "force-dynamic"' in _LAYOUT
    assert "assertHydratableCsp(" in _NEXT_CONFIG
    assert (_ROOT / "ui" / "scripts" / "assert-hydratable.mjs").is_file()


def test_the_api_still_carries_its_own_header_baseline() -> None:
    from review_console.api.app import app

    with TestClient(app, client=("127.0.0.1", 51234)) as client:
        headers = client.get("/healthz").headers
    assert "frame-ancestors" in headers["content-security-policy"]
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "no-referrer"


# --------------------------------------------------------------------------- #
# Three-state REVIEW_FRAME_ANCESTORS, on both surfaces
# --------------------------------------------------------------------------- #
_BOOT_AND_REPORT = """
from fastapi.testclient import TestClient
from review_console.api.app import app

with TestClient(app, client=("127.0.0.1", 51234)) as client:
    response = client.get("/healthz")
print("CSP=" + str(response.headers.get("content-security-policy")))
print("XFO=" + str(response.headers.get("x-frame-options")))
"""


def _boot(frame_ancestors: str | None) -> subprocess.CompletedProcess[str]:
    """Import and drive the app in a child process, since the variable is read at import."""
    env = dict(os.environ)
    env.pop("REVIEW_FRAME_ANCESTORS", None)
    if frame_ancestors is not None:
        env["REVIEW_FRAME_ANCESTORS"] = frame_ancestors
    env["REVIEW_PROFILE"] = "local"
    env["PYTHONPATH"] = os.pathsep.join([str(_ROOT / "src"), env.get("PYTHONPATH", "")])
    return subprocess.run(
        [sys.executable, "-c", _BOOT_AND_REPORT],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_frame_ancestors_resolves_three_states_not_two() -> None:
    from review_console.api.app import _FRAME_ANCESTORS_ENV, _frame_ancestors

    def setting(raw: str | None) -> EnvSetting:
        """The same EnvSetting read_env_setting would build, so the test drives the real states."""
        return EnvSetting(
            name=_FRAME_ANCESTORS_ENV, raw=raw, value="" if raw is None else raw.strip()
        )

    assert _frame_ancestors(setting(None)) == "'self'"
    assert _frame_ancestors(setting("https://host-app.example")) == "https://host-app.example"
    assert (
        _frame_ancestors(setting(" 'self'  https://host-app.example "))
        == "'self' https://host-app.example"
    )
    with pytest.raises(ValueError, match=_FRAME_ANCESTORS_ENV):
        _frame_ancestors(setting(""))
    with pytest.raises(ValueError, match=_FRAME_ANCESTORS_ENV):
        _frame_ancestors(setting("   "))


def test_the_api_honours_the_frame_ancestors_variable_terraform_actually_sets() -> None:
    """RED before: the API passed no value and hard-coded the commons default.

    ``infra/terraform/cloud_run.tf`` sets ``REVIEW_FRAME_ANCESTORS`` on the service and
    ``.env.example`` and the README both say the API honours it, but the middleware was
    registered with no ``frame_ancestors`` argument, so every API response said
    ``frame-ancestors 'self'`` whatever the deployment configured. Half the embedding
    configuration was inert with nothing in the response to show it.
    """
    result = _boot("'self' https://host-app.example")
    assert result.returncode == 0, result.stderr
    assert "CSP=frame-ancestors 'self' https://host-app.example" in result.stdout
    # No legacy header can express a multi-origin allowlist, so the CSP directive owns this case.
    assert "XFO=None" in result.stdout


def test_an_emptied_frame_ancestors_refuses_to_boot_rather_than_dropping_the_control() -> None:
    """An empty directive is a parse error browsers discard, and it also skips X-Frame-Options."""
    result = _boot("")
    assert result.returncode != 0, "an emptied frame-ancestors allowlist must refuse to boot"
    assert "REVIEW_FRAME_ANCESTORS" in result.stderr
    assert "'none'" in result.stderr, "the refusal must name the way to express a lockdown"


def test_an_unset_frame_ancestors_keeps_the_shipped_default() -> None:
    result = _boot(None)
    assert result.returncode == 0, result.stderr
    assert "CSP=frame-ancestors 'self'" in result.stdout
    assert "XFO=SAMEORIGIN" in result.stdout


def test_the_ui_builder_refuses_an_empty_frame_ancestors_too() -> None:
    """The document layer emits the policy a browser actually enforces, so it gets the same rule.

    A JavaScript default parameter only covers ``undefined``, so an explicitly empty value used
    to flow straight into the directive. The behavioural half of this lives in
    ``ui/scripts/security-headers.test.mjs``; this is the drift guard the Python gate can run.
    """
    assert "export function resolveFrameAncestors" in _HEADERS_MODULE
    assert "const ancestors = resolveFrameAncestors(frameAncestors)" in _HEADERS_MODULE
    assert "frameAncestors: process.env.NEXT_PUBLIC_FRAME_ANCESTORS," in _PROXY
    assert "NEXT_PUBLIC_FRAME_ANCESTORS ||" not in _PROXY


def test_terraform_refuses_an_empty_frame_ancestors_at_plan_time() -> None:
    """Defence in depth: the value must not even reach the container as an empty string."""
    variables = (_ROOT / "infra" / "terraform" / "variables.tf").read_text(encoding="utf-8")
    block = variables.split('variable "frame_ancestors"', 1)[1].split("\nvariable ", 1)[0]
    assert "validation" in block
    assert 'trimspace(var.frame_ancestors) != ""' in block
