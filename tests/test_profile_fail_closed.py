"""D4: the shipped image defaults to the SECURE profile, and dev personas fail closed.

Two independent guards, because the first alone is a posture claim about a text file:

1. The runtime stage of the Dockerfile selects the secure profile explicitly, so an image run
   anywhere the Cloud Run environment is not applied does NOT serve the seeded-persona identity.
2. The seeded-persona adapter itself refuses to construct unless the local profile was chosen
   deliberately, so a profile misconfiguration cannot silently hand out ``group:approver``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from hex_service_kit.identity import IdentityError

from review_console.adapters.local.identity import LocalIdentityAdapter
from review_console.config import Settings, build_container

_ROOT = Path(__file__).resolve().parents[1]
_DOCKERFILE = (_ROOT / "Dockerfile").read_text(encoding="utf-8")
_SECURE_PROFILES = {"gcp", "platform"}


def _runtime_stage() -> str:
    return _DOCKERFILE.split("AS runtime", 1)[1]


def _runtime_env(name: str) -> str | None:
    """The last value ``name`` is given in the runtime stage, across ENV continuations."""
    matches = re.findall(rf"^\s*(?:ENV\s+)?{name}=(\S+)", _runtime_stage(), flags=re.MULTILINE)
    return matches[-1] if matches else None


def test_the_image_selects_the_secure_profile_explicitly() -> None:
    profile = _runtime_env("REVIEW_PROFILE")
    assert profile is not None, "the runtime stage must select REVIEW_PROFILE explicitly"
    assert profile in _SECURE_PROFILES, (
        f"the image default profile is {profile!r}; a serving image must not default to a "
        "profile whose identity adapter is seeded dev personas"
    )


def test_the_seeded_persona_adapter_refuses_a_non_local_profile() -> None:
    with pytest.raises(IdentityError, match="local-profile only"):
        LocalIdentityAdapter(Settings(profile="gcp"))


def test_the_seeded_persona_adapter_refuses_an_inherited_local_profile() -> None:
    """An unset REVIEW_PROFILE is not a choice; personas are refused rather than granted."""
    with pytest.raises(IdentityError, match="REVIEW_PROFILE is not set"):
        LocalIdentityAdapter(Settings(profile="local", profile_explicit=False))


def test_settings_load_marks_an_absent_profile_as_not_deliberate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REVIEW_PROFILE", raising=False)
    assert Settings.load().profile_explicit is False

    monkeypatch.setenv("REVIEW_PROFILE", "local")
    assert Settings.load().profile_explicit is True


def test_the_container_refuses_personas_when_the_profile_was_inherited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REVIEW_PROFILE", raising=False)
    container = build_container(Settings.load())
    with pytest.raises(IdentityError):
        _ = container.identity


def test_a_deliberate_local_profile_still_serves_the_demo_personas() -> None:
    """The guard closes the fail-open without breaking the offline demo path."""
    adapter = LocalIdentityAdapter(Settings(profile="local"))
    subjects = {persona["subject"] for persona in adapter.personas()}
    assert "demo.approver@bank.example" in subjects
