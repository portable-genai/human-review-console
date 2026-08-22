"""A wildcard in either origin policy refuses to boot, rather than being passed through.

Two allowlists decide who may call this console from a browser and who may frame it:
``REVIEW_CORS_ORIGINS`` and ``REVIEW_FRAME_ANCESTORS``. Both were resolved carefully in three
states and then handed on verbatim, so ``*`` travelled straight through to
``CORSMiddleware(allow_origins=["*"])`` and to ``Content-Security-Policy: frame-ancestors *``.
The prohibition existed only as a comment beside the variable and, for CORS, as a sentence in
the shared kit's own docstring. A comment is not a control.

A wildcard in either place is the whole origin policy switched off, on a console that shows
tenant-partitioned review queues: any page on the internet could frame it and, with
``allow_credentials=True``, read cross-origin responses. Both values are resolved at module
import, so refusing there makes this a BOOT failure an operator sees immediately rather than a
surprise on some later request.

This file owns the one control across both variables. The three-state reads it sits on top of
are unchanged and asserted here too, because the wildcard case must not quietly alter what
unset or emptied means: ``tests/test_image_and_headers.py`` owns the rest of that story.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from hex_service_kit.netdefaults import EnvSetting

from review_console.api.app import (
    _CORS_ORIGINS_ENV,
    _FRAME_ANCESTORS_ENV,
    _WILDCARD_TOKENS,
    _cors_origins,
    _frame_ancestors,
)

_ROOT = Path(__file__).resolve().parents[1]

#: Every spelling an operator could reach, asterisk-bearing and not. Only the FIRST was refused
#: before: the check was ``"*" in origins``, a membership test over the sequence rather than over
#: each entry, so it matched an entry that IS an asterisk and let the other six through.
_WILDCARD_SPELLINGS = ["*", "'*'", "null", "*.*", "https://*.example", "*.example", "https://*"]


def _setting(name: str, raw: str | None) -> EnvSetting:
    """The same EnvSetting ``read_env_setting`` would build, so the test drives the real states."""
    return EnvSetting(name=name, raw=raw, value="" if raw is None else raw.strip())


def _boot(**overrides: str) -> subprocess.CompletedProcess[str]:
    """Import the API module in a fresh interpreter, the way uvicorn does at start-up."""
    env = dict(os.environ)
    env.pop(_FRAME_ANCESTORS_ENV, None)
    env.pop(_CORS_ORIGINS_ENV, None)
    env["REVIEW_PROFILE"] = "local"
    env.update(overrides)
    env["PYTHONPATH"] = os.pathsep.join([str(_ROOT / "src"), env.get("PYTHONPATH", "")])
    # S603: the argv is this interpreter and a literal written here, never caller input.
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", "import review_console.api.app"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )


# --------------------------------------------------------------------------- #
# The refusal
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("spelling", _WILDCARD_SPELLINGS)
def test_a_wildcard_frame_ancestor_is_refused(spelling: str) -> None:
    with pytest.raises(ValueError, match="wildcard"):
        _frame_ancestors(_setting(_FRAME_ANCESTORS_ENV, spelling))


@pytest.mark.parametrize("spelling", _WILDCARD_SPELLINGS)
def test_a_wildcard_hidden_among_real_origins_is_refused(spelling: str) -> None:
    """The dangerous shape in practice: an allowlist that looks specific and is not.

    An operator reviewing a config template sees the named origins and stops reading. One
    permissive entry anywhere in the list widens the whole policy to everybody, and the
    membership test cannot see a permissive entry unless it is the bare
    asterisk and nothing else.
    """
    with pytest.raises(ValueError, match="wildcard"):
        _frame_ancestors(
            _setting(_FRAME_ANCESTORS_ENV, f"'self' https://host-app.example {spelling}")
        )


@pytest.mark.parametrize("spelling", _WILDCARD_SPELLINGS)
def test_a_wildcard_cors_origin_is_refused(spelling: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_CORS_ORIGINS_ENV, spelling)
    with pytest.raises(ValueError, match="wildcard"):
        _cors_origins("local")


@pytest.mark.parametrize("spelling", _WILDCARD_SPELLINGS)
def test_a_wildcard_among_real_cors_origins_is_refused(
    spelling: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_CORS_ORIGINS_ENV, f"https://host-app.example,{spelling}")
    with pytest.raises(ValueError, match="wildcard"):
        _cors_origins("local")


@pytest.mark.parametrize("variable", [_FRAME_ANCESTORS_ENV, _CORS_ORIGINS_ENV])
@pytest.mark.parametrize("spelling", ["*", "null", "https://*.example"])
def test_a_wildcard_refuses_at_boot_and_not_on_a_later_request(
    variable: str, spelling: str
) -> None:
    """uvicorn imports this module at start-up, which is where an operator can still act.

    Three spellings rather than one: the bare asterisk that the old membership test caught,
    the subdomain host-source that it did not, and the behavioural ``null`` that no asterisk
    test of any shape could ever catch.
    """
    result = _boot(**{variable: spelling})
    assert result.returncode != 0, f"{variable}={spelling} must refuse to boot"
    assert variable in result.stderr
    assert "wildcard" in result.stderr


def test_the_rule_is_the_union_of_an_asterisk_test_and_an_exact_token_set() -> None:
    """Neither half is sufficient alone, which is the whole reason this file grew.

    The asterisk half cannot see ``null``; the token half cannot see ``https://*.example``,
    because a set matches an entry exactly and nothing else. The fleet reference and the UI
    module both hold the same union.
    """
    assert sorted(_WILDCARD_TOKENS) == ["'*'", "*", "*.*", "null"]
    assert "*" not in "null"
    assert "https://*.example" not in _WILDCARD_TOKENS


# --------------------------------------------------------------------------- #
# What must NOT change
# --------------------------------------------------------------------------- #
def test_a_legitimate_allowlist_still_boots(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refusal that also turns away valid configuration is an outage, not a control.

    The rule widened from a membership test to a per-entry one, which is exactly the direction
    that can start refusing real origins, so the two shapes most likely to trip a careless rule
    are named here: an explicit PORT (the colon and digits) and a HYPHENATED host label, which
    is legal in DNS and common in tenant-specific origins.
    """
    named = "'self' https://host-app.example:8443 https://a-b-c.host-app.example"
    assert _frame_ancestors(_setting(_FRAME_ANCESTORS_ENV, named)) == named
    monkeypatch.setenv(
        _CORS_ORIGINS_ENV, "https://host-app.example:8443,https://a-b-c.admin.example"
    )
    assert _cors_origins("gcp") == [
        "https://host-app.example:8443",
        "https://a-b-c.admin.example",
    ]

    result = _boot(**{_FRAME_ANCESTORS_ENV: named})
    assert result.returncode == 0, result.stderr


def test_a_host_containing_the_word_null_is_not_a_wildcard() -> None:
    """Exact matching, not substring: ``null`` is a token, and hosts may legitimately spell it."""
    assert _frame_ancestors(_setting(_FRAME_ANCESTORS_ENV, "https://nullify.example")) == (
        "https://nullify.example"
    )


def test_the_unset_and_emptied_states_are_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the wildcard case is new; the two states this repo already resolved must hold.

    Unset frame-ancestors keeps the shipped ``'self'`` and emptied still refuses for its own
    reason (an empty CSP directive is a parse error browsers discard), which is a different
    refusal from this one and must not be swallowed by it. Unset CORS keeps the local dev
    fallback, is withheld from an unconsented run, and emptied still denies every origin.
    """
    assert _frame_ancestors(_setting(_FRAME_ANCESTORS_ENV, None)) == "'self'"
    with pytest.raises(ValueError, match=_FRAME_ANCESTORS_ENV):
        _frame_ancestors(_setting(_FRAME_ANCESTORS_ENV, ""))

    monkeypatch.delenv(_CORS_ORIGINS_ENV, raising=False)
    assert _cors_origins("local") == ["http://localhost:3000", "http://127.0.0.1:3000"]
    assert _cors_origins("unconfigured") == []
    monkeypatch.setenv(_CORS_ORIGINS_ENV, "")
    assert _cors_origins("local") == []


def test_a_total_lockdown_is_still_expressible() -> None:
    """``'none'`` is the way to forbid all framing, and refusing ``*`` must not remove it."""
    assert _frame_ancestors(_setting(_FRAME_ANCESTORS_ENV, "'none'")) == "'none'"


def test_the_ui_builder_refuses_a_wildcard_too() -> None:
    """The document a browser frames is served by Next.js, never through the API middleware.

    Fixing only the API would leave the more directly exploitable surface open: the console
    page's own CSP comes from ``ui/lib/security-headers.mjs``, which refused an emptied value
    and passed a wildcard straight into the directive. The behavioural half of this lives in
    ``ui/scripts/security-headers.test.mjs`` (``make ui-headers-test``); this is the drift
    guard the Python gate can run, since the gate does not shell out to node.

    The two surfaces must refuse the SAME UNION, and each held only one half of it. The UI had
    the exact-token set and no asterisk test, so ``https://*.evil.example`` was emitted verbatim
    and CSP honoured it as every subdomain; the API had the asterisk test as a MEMBERSHIP check
    over the whole list, so it saw only a lone bare asterisk. Asserting both halves of the UI
    rule here is what stops one surface being narrowed again without the other.
    """
    module = (_ROOT / "ui" / "lib" / "security-headers.mjs").read_text(encoding="utf-8")
    for spelling in sorted(_WILDCARD_TOKENS):
        assert f'"{spelling}"' in module, f"the UI policy does not name {spelling}"
    assert "FRAME_ANCESTOR_WILDCARDS.has(part)" in module
    assert 'part.includes("*")' in module
    assert "isWildcard(part)" in module
    assert "never " in module and "contain a wildcard" in module


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
