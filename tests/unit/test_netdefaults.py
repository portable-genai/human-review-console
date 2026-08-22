"""Fail-closed network defaults (C5): the no-auth local profile never binds off loopback.

The console serves a persona-picker UI with no real auth under the local profile, so exposing it
on 0.0.0.0 would be an open door. The bind guard from the commons refuses that unless an explicit
insecure-demo opt-out is set.
"""

from __future__ import annotations

import pytest
from hex_service_kit.netdefaults import InsecureBindError, cors_allowlist, resolve_bind_host

_HOST_ENV = "REVIEW_API_HOST"
_INSECURE_ENV = "REVIEW_ALLOW_INSECURE_DEMO"
_CORS_ENV = "REVIEW_CORS_ORIGINS"


def test_local_defaults_to_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_HOST_ENV, raising=False)
    monkeypatch.delenv(_INSECURE_ENV, raising=False)
    assert resolve_bind_host("local", host_env=_HOST_ENV, insecure_demo_env=_INSECURE_ENV) == (
        "127.0.0.1"
    )


def test_local_refuses_non_loopback_without_optout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_HOST_ENV, "0.0.0.0")
    monkeypatch.delenv(_INSECURE_ENV, raising=False)
    with pytest.raises(InsecureBindError):
        resolve_bind_host("local", host_env=_HOST_ENV, insecure_demo_env=_INSECURE_ENV)


def test_local_allows_non_loopback_with_explicit_optout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_HOST_ENV, "0.0.0.0")
    monkeypatch.setenv(_INSECURE_ENV, "1")
    assert resolve_bind_host("local", host_env=_HOST_ENV, insecure_demo_env=_INSECURE_ENV) == (
        "0.0.0.0"
    )


def test_cors_never_wildcards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_CORS_ENV, raising=False)
    # gcp with no configured origins: empty allowlist, never "*".
    assert cors_allowlist("gcp", origins_env=_CORS_ENV) == []
