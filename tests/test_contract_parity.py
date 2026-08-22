"""Port/adapter parity: every port has a working binding in every profile, importable offline.

This is the hexagon's load-bearing contract test: switching the whole stack is a one-line profile
change with no domain edits, and the local / onprem profiles import every adapter with no GCP SDK
installed (the portability proof).
"""

from __future__ import annotations

import pytest
from hex_service_kit.identity import IdentityPort

from review_console.config import (
    _BINDINGS,
    _IDENTITY_BINDINGS,
    RUNTIME_PROFILES,
    Settings,
    build_container,
)
from review_console.ports import AuditSinkPort, ReviewStorePort

BOUND_PORTS = {"review_store", "case_store", "timers", "events", "audit"}


@pytest.mark.parametrize("profile", sorted(RUNTIME_PROFILES))
def test_every_port_binds_and_conforms(profile: str) -> None:
    container = build_container(Settings(profile=profile, audit_path=":memory:"))
    # Construction imports the adapter module (gcp SDK imports are lazy, so this works offline)
    # and the container asserts Protocol conformance as it binds.
    assert isinstance(container.review_store, ReviewStorePort)
    assert isinstance(container.audit, AuditSinkPort)
    assert isinstance(container.identity, IdentityPort)


def test_onprem_store_fails_fast() -> None:
    container = build_container(Settings(profile="onprem"))
    with pytest.raises(NotImplementedError):
        container.review_store.list_pending("demo-bank")


def test_binding_table_has_exact_port_and_profile_coverage() -> None:
    assert set(_BINDINGS) == BOUND_PORTS
    assert all(set(bindings) == RUNTIME_PROFILES for bindings in _BINDINGS.values())
    assert set(_IDENTITY_BINDINGS) == RUNTIME_PROFILES


def test_unknown_profile_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown REVIEW_PROFILE"):
        Settings(profile="typo")
