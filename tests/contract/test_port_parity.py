"""Port-set drift guard: the port registry, the binding tables and the profile registry agree.

This console keeps its deployment map in code rather than in a settings file, so the three
registries that describe its hexagon are:

* the runtime_checkable Protocols exported by :mod:`review_console.ports` (what a port IS),
* :data:`review_console.config._BINDINGS` and :data:`review_console.config._IDENTITY_BINDINGS`
  (which class fills each port, per profile), and
* :data:`review_console.config.RUNTIME_PROFILES` (which profiles may be selected at all).

Nothing at runtime compares them. A port bound in the table but absent from the protocol map
below is unenforced with a green build: today ``_BINDINGS`` coverage is checked against a literal
set of port NAMES, which a new entry satisfies by being added to that literal, with no Protocol
ever named for it and therefore no conformance check anywhere. A Protocol added to ``ports/`` and
never bound is a hexagon edge nobody can reach. A profile admitted to ``RUNTIME_PROFILES`` with
nothing bound to it validates at boot and then raises ``KeyError`` at the first port access.

Every assertion here is set equality in BOTH directions for that reason: one direction alone lets
a new port ship with no sovereign binding, which is the omission that quietly reaches for the
managed stack, and the other lets an orphan adapter overstate coverage.

Two facts specific to this repository shape the file:

* there are FOUR runtime profiles, not three. ``platform`` is a reviewed alias to the managed
  adapters because this service IS the Hrz7 platform horizontal, so it must be bound as
  completely as ``gcp`` and is swept here alongside it rather than assumed to follow.
* the case engine put ``review_router`` on the same hexagon, and it is deliberately
  wired OUTSIDE ``_BINDINGS`` (``InProcessReviewRouter`` needs the live ``ConsoleService``, not
  just ``Settings``). That exception is named explicitly below so it stays a reviewed exception
  rather than becoming the hole through which the next unbound port slips.

Scope note. This file guards the SETS and the constructibility of every binding. The behavioural
contracts (``onprem`` fails fast, the local stack really queues and disposes) are proven in
``tests/test_contract_parity.py`` and ``tests/test_case_contract_parity.py``.
"""

from __future__ import annotations

from typing import Protocol, get_type_hints

import pytest
from hex_service_kit.identity import IdentityPort

from review_console import ports
from review_console.config import (
    _BINDINGS,
    _IDENTITY_BINDINGS,
    RUNTIME_PROFILES,
    Container,
    Settings,
)

#: Every port name in ``_BINDINGS`` mapped to its Protocol. Hand maintained on purpose: the tests
#: below fail loudly when it stops matching either registry it straddles.
PORT_PROTOCOLS: dict[str, type] = {
    "review_store": ports.ReviewStorePort,
    "case_store": ports.CaseStorePort,
    "timers": ports.TimerPort,
    "events": ports.EventPublisherPort,
    "audit": ports.AuditSinkPort,
}

#: Port name -> the :class:`Container` attribute that serves it. A port with a binding and no
#: accessor is bound to something the service can never ask for.
PORT_ACCESSORS: dict[str, str] = {
    "review_store": "review_store",
    "case_store": "case_store",
    "timers": "timers",
    "events": "events",
    "audit": "audit",
}

#: Protocols the ports package exports that are deliberately NOT in ``_BINDINGS``, each with the
#: reason it is an exception. Written as data so a new unbound Protocol has to be argued for here
#: rather than simply not noticed.
EXEMPT_FROM_BINDINGS: dict[str, str] = {
    "ReviewRouterPort": (
        "wired in-process as Container.review_router: InProcessReviewRouter needs the LIVE "
        "ConsoleService so a routed case lands in the very queue the review API serves, which "
        "a Settings-only binding table cannot express"
    ),
}


def _settings(profile: str) -> Settings:
    """Ephemeral settings for ``profile``: both stores in memory, nothing written to disk."""
    return Settings(profile=profile, audit_path=":memory:", review_db_path=":memory:")


def _protocol_members(protocol: type) -> set[str]:
    """The attribute names a Protocol declares (methods + properties), no dunders."""
    members = set(getattr(protocol, "__protocol_attrs__", set()))
    if not members:  # pragma: no cover - fallback for older typing internals
        members |= set(get_type_hints(protocol).keys())
    return {m for m in members if not m.startswith("_")}


def _exported_protocols() -> dict[str, type]:
    """Every runtime_checkable Protocol :mod:`review_console.ports` exports, by name.

    The ports package also exports the end-user-authentication vocabulary and an error type,
    which declare no Protocol. Filtering on ``_is_runtime_protocol`` keeps those out without a
    hand-written exemption list that would need editing every time the vocabulary grows.
    """
    found: dict[str, type] = {}
    for name in ports.__all__:
        obj = getattr(ports, name)
        if isinstance(obj, type) and getattr(obj, "_is_runtime_protocol", False):
            found[name] = obj
    return found


# --------------------------------------------------------------------------- #
# The port set: protocol map <-> binding table, both directions
# --------------------------------------------------------------------------- #
def test_protocol_map_and_binding_table_name_the_same_ports() -> None:
    bound = set(_BINDINGS)
    declared = set(PORT_PROTOCOLS)

    unmapped = bound - declared
    assert not unmapped, (
        f"ports bound in config._BINDINGS but absent from PORT_PROTOCOLS (so they get NO "
        f"conformance or profile-coverage enforcement): {sorted(unmapped)}. Add them to the "
        "parity map with the Protocol they are supposed to satisfy."
    )
    unbound = declared - bound
    assert not unbound, (
        f"ports in PORT_PROTOCOLS with no entry in config._BINDINGS: {sorted(unbound)}. "
        "Either bind them or drop them; an entry with no adapter overstates what this hexagon "
        "actually covers."
    )


def test_every_exported_protocol_is_bound_or_a_named_exception() -> None:
    """A Protocol in ``ports/`` is either in the binding table or an argued-for exception."""
    exported = _exported_protocols()
    mapped = set(PORT_PROTOCOLS.values())

    orphans = {
        name
        for name, proto in exported.items()
        if proto not in mapped and name not in EXEMPT_FROM_BINDINGS
    }
    assert not orphans, (
        f"runtime_checkable Protocols exported by review_console.ports that are neither bound in "
        f"config._BINDINGS nor listed in EXEMPT_FROM_BINDINGS: {sorted(orphans)}. Bind them, or "
        "record here why this one cannot be built from Settings alone."
    )
    stale = set(EXEMPT_FROM_BINDINGS) - set(exported)
    assert not stale, (
        f"EXEMPT_FROM_BINDINGS names Protocols review_console.ports no longer exports: "
        f"{sorted(stale)}. A stale exemption is a hole nobody is watching."
    )
    foreign = {
        port for port, proto in PORT_PROTOCOLS.items() if proto not in set(exported.values())
    }
    assert not foreign, (
        f"ports mapped to a Protocol that review_console.ports does not export: {sorted(foreign)}. "
        "The ports package is the port registry; a look-alike declared elsewhere is how two "
        "copies of one interface drift apart while isinstance stays green."
    )


def test_the_exempt_port_really_is_reachable_another_way() -> None:
    """An exemption is only honest if the port is still bound, just not from the table."""
    container = Container(_settings("local"))
    assert isinstance(container.review_router, ports.ReviewRouterPort), (
        "review_router is exempt from _BINDINGS on the grounds that Container wires it "
        "in-process; if that wiring stops conforming, the exemption is covering a gap"
    )
    assert "review_router" not in _BINDINGS, (
        "review_router now HAS a table binding, so it must move into PORT_PROTOCOLS and out of "
        "EXEMPT_FROM_BINDINGS rather than being checked in two different ways"
    )


def test_every_bound_port_is_reachable_through_the_container() -> None:
    assert set(PORT_ACCESSORS) == set(PORT_PROTOCOLS), (
        "PORT_ACCESSORS and PORT_PROTOCOLS must cover the same ports"
    )
    for port_name, attribute in PORT_ACCESSORS.items():
        assert hasattr(Container, attribute), (
            f"port '{port_name}' has a binding but Container exposes no '{attribute}' accessor, "
            "so nothing in the service can obtain it"
        )


# --------------------------------------------------------------------------- #
# The profile set: binding tables <-> the profile registry, both directions
# --------------------------------------------------------------------------- #
def test_every_port_binds_every_runtime_profile() -> None:
    """Every declared port has a binding in every profile ``RUNTIME_PROFILES`` admits.

    The expected set is READ from ``config.RUNTIME_PROFILES``. This service has FOUR profiles,
    and ``platform`` is the one a literal written from habit would omit: it is a reviewed alias
    to the managed adapters, so a port that quietly lacks it selects nothing at all rather than
    falling back.
    """
    for port_name in PORT_PROTOCOLS:
        binding = _BINDINGS.get(port_name, {})
        missing = set(RUNTIME_PROFILES) - set(binding)
        assert not missing, (
            f"port '{port_name}' has no adapter bound for profile(s) {sorted(missing)}; "
            f"config.RUNTIME_PROFILES admits {sorted(RUNTIME_PROFILES)}"
        )


def test_no_binding_names_a_profile_nothing_may_select() -> None:
    for port_name, binding in _BINDINGS.items():
        stray = set(binding) - set(RUNTIME_PROFILES)
        assert not stray, (
            f"port '{port_name}' binds profile(s) {sorted(stray)} that config.RUNTIME_PROFILES "
            "refuses, so the adapter is dead weight and its coverage is imaginary"
        )


def test_the_identity_table_covers_exactly_the_runtime_profiles() -> None:
    """Identity has its own table, and it is the one an end-user route cannot do without."""
    assert set(_IDENTITY_BINDINGS) == set(RUNTIME_PROFILES), (
        f"config._IDENTITY_BINDINGS covers {sorted(_IDENTITY_BINDINGS)} but "
        f"config.RUNTIME_PROFILES admits {sorted(RUNTIME_PROFILES)}; a profile with no identity "
        "adapter is a profile whose end-user routes cannot establish who is calling"
    )


# --------------------------------------------------------------------------- #
# Structural conformance of every binding, in every profile
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("profile", sorted(RUNTIME_PROFILES))
@pytest.mark.parametrize("port_name", sorted(PORT_PROTOCOLS))
def test_bound_adapter_satisfies_its_protocol(profile: str, port_name: str) -> None:
    """Every family constructs offline: the managed adapters import their SDKs lazily."""
    protocol = PORT_PROTOCOLS[port_name]
    dotted = _BINDINGS.get(port_name, {}).get(profile, "")
    assert dotted, (
        f"port '{port_name}' has no '{profile}' binding, so there is no adapter to hold to "
        f"{protocol.__name__}"
    )

    # Bound through the container's own import path, so this is about the mechanism the
    # running service uses rather than a second implementation of it.
    adapter = Container(_settings(profile))._bind(port_name)

    assert isinstance(adapter, protocol), (
        f"{dotted} does not structurally satisfy {protocol.__name__}"
    )

    # Every declared Protocol member exists. Looked up on the CLASS via the MRO, not the
    # instance: the fail-fast onprem placeholders raise when invoked, so ``hasattr`` on a
    # property would wrongly report it missing.
    declared = set().union(*(vars(klass) for klass in type(adapter).__mro__))
    for member in _protocol_members(protocol):
        assert member in declared, (
            f"{dotted} is missing port method '{member}' of {protocol.__name__}"
        )


@pytest.mark.parametrize("profile", sorted(RUNTIME_PROFILES))
def test_bound_identity_adapter_satisfies_the_commons_protocol(profile: str) -> None:
    adapter = Container(_settings(profile))._bind_identity()
    assert isinstance(adapter, IdentityPort), (
        f"{_IDENTITY_BINDINGS[profile]} does not structurally satisfy IdentityPort"
    )
    declared = set().union(*(vars(klass) for klass in type(adapter).__mro__))
    for member in _protocol_members(IdentityPort):
        assert member in declared, (
            f"{_IDENTITY_BINDINGS[profile]} is missing IdentityPort member '{member}'"
        )


def test_all_mapped_protocols_are_runtime_checkable() -> None:
    """``isinstance`` above is meaningless against a Protocol that is not runtime_checkable."""
    checked = {**PORT_PROTOCOLS, "identity": IdentityPort}
    for port_name, protocol in checked.items():
        assert issubclass(protocol, Protocol)  # type: ignore[arg-type]
        assert getattr(protocol, "_is_runtime_protocol", False), (
            f"{protocol.__name__} (port '{port_name}') must be @runtime_checkable"
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
