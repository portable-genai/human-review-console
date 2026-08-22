"""The profile has ONE source of truth, and it fails closed on an unset variable.

The first remediation of this fail-open fixed the identity adapter but left ``api/app.py``
re-deriving the same decision with its own raw fallback, which is how the S2S write path stayed
open. A drift guard is therefore part of the defence: any module that reads ``REVIEW_PROFILE``
directly can reintroduce the whole class, so only ``config.resolve_profile`` may read it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from hex_service_kit.netdefaults import ConfiguredEmptyError

from review_console.config import RUNTIME_PROFILES, UNCONSENTED_PROFILE, resolve_profile

_SRC = Path(__file__).resolve().parents[1] / "src" / "review_console"
_CONFIG = _SRC / "config.py"


def _python_sources() -> list[Path]:
    return sorted(p for p in _SRC.rglob("*.py") if p != _CONFIG)


def test_only_the_resolver_reads_the_profile_variable_from_the_environment() -> None:
    offenders = []
    for path in _python_sources():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if re.search(r"(os\.environ|os\.getenv)[^\n]*PROFILE", line):
                offenders.append(f"{path.relative_to(_SRC)}:{number}: {line.strip()}")
    assert not offenders, (
        "these modules re-derive the profile instead of calling config.resolve_profile, "
        "so an unset REVIEW_PROFILE can again be read as consent:\n" + "\n".join(offenders)
    )


def test_the_resolver_treats_an_ABSENT_variable_as_no_choice() -> None:
    choice = resolve_profile({})
    assert choice.explicit is False
    assert choice.service_auth_configured is False


def test_an_EMPTIED_variable_refuses_rather_than_inheriting_the_unset_default() -> None:
    """An assertion that PINS the defect is how the defect survives.

    The test read ``({}, {"REVIEW_PROFILE": ""}, {"REVIEW_PROFILE": "   "})`` as one case and
    asserted all three were "no choice", so the resolver's ``env.get(name, "").strip()`` plus
    ``raw or "local"`` collapse was not a bug the suite could see: it was the behaviour the suite
    required. An operator who deliberately emptied the variable expressed an intent that names no
    profile, which is not the same as never having chosen, so it refuses instead.
    """
    for environ in ({"REVIEW_PROFILE": ""}, {"REVIEW_PROFILE": "   "}):
        with pytest.raises(ConfiguredEmptyError):
            resolve_profile(environ)


def test_an_unconsented_run_is_not_the_local_profile_for_any_relaxation() -> None:
    choice = resolve_profile({})
    assert choice.exposure_profile == UNCONSENTED_PROFILE
    assert choice.exposure_profile != "local"
    assert UNCONSENTED_PROFILE not in RUNTIME_PROFILES


def test_an_unconsented_run_still_binds_loopback() -> None:
    """The bind guard fails closed in the opposite direction: local is the restrictive case."""
    assert resolve_profile({}).bind_profile == "local"


def test_a_deliberate_profile_is_carried_through_unchanged() -> None:
    choice = resolve_profile({"REVIEW_PROFILE": "gcp"})
    assert (choice.profile, choice.explicit) == ("gcp", True)
    assert choice.exposure_profile == "gcp"
    assert choice.bind_profile == "gcp"
    assert choice.service_auth_configured is True
