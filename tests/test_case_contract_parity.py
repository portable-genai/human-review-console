"""Case-port parity: the case ports bind and conform in every profile, offline.

The case-workflow engine sits on the review console's hexagon, so its ports (``case_store`` /
``timers`` / ``events``) must obey the SAME load-bearing contract as the review ports: switching
the whole stack is a one-line profile change with no domain edits, and the local / onprem profiles
import every adapter with no GCP SDK installed (the portability proof).

The ``review_router`` port is the one deliberate exception to the binding-table rule (see the
``test_review_router_is_wired_outside_bindings`` docstring): it is wired in-process to the live
console rather than from settings, so it is asserted here via the container attribute but excluded
from the ``_BINDINGS`` coverage check.
"""

from __future__ import annotations

import pytest

from review_console.config import _BINDINGS, RUNTIME_PROFILES, Settings, build_container
from review_console.ports import (
    CaseStorePort,
    EventPublisherPort,
    ReviewRouterPort,
    TimerPort,
)


@pytest.mark.parametrize("profile", sorted(RUNTIME_PROFILES))
def test_every_case_port_binds_and_conforms(profile: str) -> None:
    container = build_container(Settings(profile=profile, audit_path=":memory:"))
    # Construction imports the adapter module (gcp SDK imports are lazy, so this works offline)
    # and the container asserts Protocol conformance as it binds.
    assert isinstance(container.case_store, CaseStorePort)
    assert isinstance(container.timers, TimerPort)
    assert isinstance(container.events, EventPublisherPort)
    # review_router is built in-process (not from _BINDINGS) but must still conform per profile.
    assert isinstance(container.review_router, ReviewRouterPort)


@pytest.mark.parametrize("port", ["case_store", "timers", "events"])
def test_case_ports_have_a_binding_in_every_profile(port: str) -> None:
    # Each case port carries a local / gcp / onprem entry in the binding table, so a
    # profile switch never leaves it unbound.
    assert set(_BINDINGS[port]) == RUNTIME_PROFILES


def test_review_router_is_wired_outside_bindings() -> None:
    # review_router is INTENTIONALLY absent from _BINDINGS. Unlike every other port it is not built
    # from settings alone: InProcessReviewRouter needs the LIVE ConsoleService so a routed case
    # lands in the very review queue the console's own API serves. config.py therefore wires it as
    # a cached_property outside the binding table. Excluding it here keeps the _BINDINGS-coverage
    # assertion from failing falsely; its Protocol conformance is proven by
    # test_every_case_port_binds_and_conforms above (container.review_router).
    assert "review_router" not in _BINDINGS


def test_onprem_case_store_fails_fast() -> None:
    container = build_container(Settings(profile="onprem"))
    with pytest.raises(NotImplementedError):
        container.case_store.list_by_tenant("demo-bank")
