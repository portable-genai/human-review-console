"""Settings + Container: profile-driven dependency injection (the hexagon wiring).

One env var (``REVIEW_PROFILE``) selects the adapter family for every runtime and data port.
``local`` is the SDK-free offline default (dev / test / CI); ``gcp`` is the managed cloud stack;
``platform`` is an explicit deployment of this shared platform service on the same managed
adapters; ``onprem`` is the fail-fast portability placeholder. Identity is selected from its own
exact map so a channel or identity choice cannot silently change the runtime/data profile.

The merged service hosts two co-resident hexagons: the review console (``review_store``) and the
case-workflow engine (``case_store`` / ``timers`` / ``events``), plus the shared
``audit`` / ``identity`` ports serving both. The ``review_router`` seam is wired IN-PROCESS (a
direct call to the console) rather than through the binding table, since its adapter needs the
live ``ConsoleService`` rather than just settings.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from hex_service_kit.identity import IdentityPort
from hex_service_kit.netdefaults import ConfiguredEmptyError, EnvSetting, read_env_setting

from .adapters.review_router import InProcessReviewRouter
from .domain.console_service import ConsoleService
from .domain.maker_checker_service import DEFAULT_ROUTING, RoutingPolicy
from .ports.audit import AuditSinkPort
from .ports.case_store import CaseStorePort
from .ports.events import EventPublisherPort
from .ports.identity import CLIENT_ASSERTED, declared_end_user_auth
from .ports.review_router import ReviewRouterPort
from .ports.review_store import ReviewStorePort
from .ports.timers import TimerPort

_PROFILE_ENV = "REVIEW_PROFILE"
REGION = "asia-southeast1"
RUNTIME_PROFILES = frozenset({"local", "gcp", "platform", "onprem"})

#: The profile string handed to every INTERNET-FACING posture decision when ``REVIEW_PROFILE``
#: was never set. It is deliberately NOT a member of :data:`RUNTIME_PROFILES` and never reaches
#: :class:`Settings`: it exists so that "no choice was made" is a distinct input to the security
#: layers rather than being indistinguishable from a chosen ``local``.
UNCONSENTED_PROFILE = "unconfigured"

#: The in-country residency allowlist. This is the SAME list Terraform validates at plan time
#: (``infra/terraform/variables.tf`` ``region`` validation and ``locals.tf`` ``allowed_locations``),
#: asserted identical by ``tests/test_residency_parity.py``. Residency is therefore enforced twice:
#: a plan that names an out-of-country region is rejected before apply, and a process started with
#: one refuses to boot rather than serving from the wrong jurisdiction.
RESIDENCY_ALLOWLIST = frozenset({"asia-southeast1", "asia-southeast2"})

#: The shipped bank-owned policy document (B4): every tunable routing number lives here, not in
#: engine code. The defaults equal the reference constants in ``domain.maker_checker_service``.
DEFAULT_POLICY_PATH = "config/policy.json"

# port -> profile -> "module:Class". Every runtime/data port has an explicit binding for every
# profile. This service is itself the Hrz7 platform horizontal, so the ``platform`` profile is a
# reviewed alias to its managed adapters, not an outbound delegate to another Hrz7 instance.
_BINDINGS: dict[str, dict[str, str]] = {
    "review_store": {
        "local": "review_console.adapters.local.review_store:LocalReviewStore",
        "gcp": "review_console.adapters.gcp.review_store:FirestoreReviewStore",
        "platform": "review_console.adapters.gcp.review_store:FirestoreReviewStore",
        "onprem": "review_console.adapters.onprem.review_store:OnPremReviewStore",
    },
    "case_store": {
        "local": "review_console.adapters.local.case_store:LocalCaseStore",
        "gcp": "review_console.adapters.gcp.case_store:FirestoreCaseStore",
        "platform": "review_console.adapters.gcp.case_store:FirestoreCaseStore",
        "onprem": "review_console.adapters.onprem.case_store:OnPremCaseStore",
    },
    "timers": {
        "local": "review_console.adapters.local.timers:LocalTimerAdapter",
        "gcp": "review_console.adapters.gcp.timers:CloudTasksTimerAdapter",
        "platform": "review_console.adapters.gcp.timers:CloudTasksTimerAdapter",
        "onprem": "review_console.adapters.onprem.timers:OnPremTimerAdapter",
    },
    "events": {
        "local": "review_console.adapters.local.events:LocalEventPublisher",
        "gcp": "review_console.adapters.gcp.events:PubSubEventPublisher",
        "platform": "review_console.adapters.gcp.events:PubSubEventPublisher",
        "onprem": "review_console.adapters.onprem.events:OnPremEventPublisher",
    },
    "audit": {
        "local": "review_console.adapters.local.audit:LocalAuditAdapter",
        "gcp": "review_console.adapters.gcp.audit:CloudAuditAdapter",
        "platform": "review_console.adapters.gcp.audit:CloudAuditAdapter",
        "onprem": "review_console.adapters.onprem.audit:OnPremAuditAdapter",
    },
}

_IDENTITY_BINDINGS: dict[str, str] = {
    "local": "review_console.adapters.local.identity:LocalIdentityAdapter",
    "gcp": "review_console.adapters.gcp.identity:IapIdentityAdapter",
    "platform": "review_console.adapters.gcp.identity:IapIdentityAdapter",
    "onprem": "review_console.adapters.onprem.identity:OnPremIdentityAdapter",
}


def _validate_profile(profile: str) -> str:
    """Fail closed on a profile string nothing binds, INCLUDING a capitalisation typo.

    The comparison is exact and case-sensitive on purpose: every posture decision downstream
    matches the profile string exactly, so ``Local`` selects none of the relaxations but also
    none of the restrictions. Normalising the case here would turn a typo into a silent choice;
    refusing it turns the typo into a boot failure.
    """
    if profile not in RUNTIME_PROFILES:
        expected = ", ".join(sorted(RUNTIME_PROFILES))
        raise ValueError(f"unknown {_PROFILE_ENV} {profile!r}; expected one of: {expected}")
    return profile


def _validate_region(region: str) -> str:
    """Fail closed on an out-of-country region: residency is a boot condition, not a warning."""
    if region not in RESIDENCY_ALLOWLIST:
        allowed = ", ".join(sorted(RESIDENCY_ALLOWLIST))
        raise ValueError(
            f"region {region!r} is outside the residency allowlist; expected one of: {allowed}"
        )
    return region


#: The profiles whose runtime is a managed cloud, for :attr:`Settings.runtime`. ``onprem`` is
#: NOT one -- running on the adopter's own iron is its entire point, and "on GCP" is the one
#: sentence that deployment must never print at the top of a page.
_MANAGED_PROFILES: frozenset[str] = frozenset({"gcp", "platform"})


@dataclass(frozen=True, slots=True)
class ProfileChoice:
    """The ONE resolution of ``REVIEW_PROFILE``, and what each consumer must key off.

    Every module that needs the profile calls :func:`resolve_profile` and reads one of the
    members below. No module may re-derive the profile with its own
    ``os.environ.get("REVIEW_PROFILE", "local")``: that fallback reads an UNSET variable as
    consent, which is the fail-open this type exists to remove
    (``tests/test_profile_single_source.py`` fails the build if one reappears).

    The two derived profile strings differ because the two decisions fail closed in OPPOSITE
    directions, so a single "effective profile" string would harden one and weaken the other.
    """

    #: Which adapter family to bind. Absent consent this is still ``local`` (the SDK-free
    #: adapters), because the alternative would import cloud SDKs that are not installed; the
    #: local IDENTITY adapter refuses to construct when :attr:`explicit` is False, so an
    #: unconsented run has data adapters but no end-user identity.
    profile: str = "local"
    #: Was the profile named DELIBERATELY (``REVIEW_PROFILE`` present and non-empty)?
    explicit: bool = True

    @property
    def exposure_profile(self) -> str:
        """The profile every *relaxation* keys off: CORS origins, dev-persona header, HSTS.

        These decisions grant something extra to ``local``, so an unconsented run must NOT
        look like ``local``: it gets :data:`UNCONSENTED_PROFILE`, which is no origin's
        allowlist, no ``X-Dev-Persona`` and HSTS on.
        """
        return self.profile if self.explicit else UNCONSENTED_PROFILE

    @property
    def bind_profile(self) -> str:
        """The profile the bind guard keys off, where ``local`` is the RESTRICTIVE case.

        ``resolve_bind_host`` confines ``local`` to loopback and lets fronted profiles take
        ``0.0.0.0``, so here an unconsented run must look like ``local`` and stay on loopback.
        """
        return self.profile if self.explicit else "local"

    @property
    def service_auth_configured(self) -> bool:
        """May S2S callers be authenticated at all, or is the decision unconfigured?

        False means no profile was chosen, so neither S2S scheme has been selected and the
        request cannot be authenticated. The API turns this into a 401 rather than letting the
        shared-secret path's loopback-dev opening apply (see ``api/app.py``).
        """
        return self.explicit


def _profile_setting(environ: Mapping[str, str] | None) -> EnvSetting:
    """``REVIEW_PROFILE`` in its three states, from the real environment or an injected mapping.

    The injected form builds the SAME :class:`~hex_service_kit.netdefaults.EnvSetting` the commons
    would, so a test drives the identical three states rather than a second, kinder implementation
    of them.
    """
    if environ is None:
        return read_env_setting(_PROFILE_ENV)
    raw = environ.get(_PROFILE_ENV)
    return EnvSetting(name=_PROFILE_ENV, raw=raw, value="" if raw is None else raw.strip())


def resolve_profile(environ: Mapping[str, str] | None = None) -> ProfileChoice:
    """Read ``REVIEW_PROFILE`` once, resolving THREE states rather than two.

    A value that IS present is validated here, not later: ``api/app.py`` resolves the profile at
    module scope, so raising makes an unknown or mis-capitalised value a BOOT failure. Validation
    used to happen only in :meth:`Settings.__post_init__`, which the API builds lazily at the
    first request, so ``REVIEW_PROFILE=bogus`` and the typo ``REVIEW_PROFILE=Local`` both produced
    a serving app: an app that had already chosen its CORS, persona-header and bind postures from
    a string nothing binds.

    The read goes through the commons rather than ``env.get(name, "").strip()``, because that
    hand-rolled form collapses UNSET and SET-AND-EMPTY into one branch BEFORE any logic here
    runs, and the ``raw or "local"`` that followed it then handed a variable an operator
    deliberately emptied the offline default.
    """
    setting = _profile_setting(environ)
    if setting.is_configured_empty:
        raise ConfiguredEmptyError(
            f"{_PROFILE_ENV} is set to an empty value, which is not a profile. Unset it to leave "
            f"the choice unmade, or set it to one of {', '.join(sorted(RUNTIME_PROFILES))}."
        )
    if setting.is_unset:
        return ProfileChoice(profile="local", explicit=False)
    _validate_profile(setting.value)
    return ProfileChoice(profile=setting.value, explicit=True)


def _setting(name: str, default: str) -> str:
    """Three-state read of ``name``: unset takes ``default``, EMPTIED refuses, a value wins.

    ``os.environ.get(name, "").strip() or default`` hands a variable an operator deliberately
    emptied exactly what it hands one nobody set, and for these reads that default is the
    permissive branch: emptying ``REVIEW_AUDIT_PATH`` silently selected the ``:memory:`` log,
    which loses the durable audit trail with nothing in the response to show it, and emptying
    ``REVIEW_IAP_ENTITLEMENTS_JSON`` silently restored the built-in entitlement map. An emptied
    value expressed an intent and it names nothing, so it refuses at load rather than inheriting.
    """
    setting = read_env_setting(name)
    if setting.is_configured_empty:
        raise ConfiguredEmptyError(
            f"{name} is set to an empty value, which names nothing. Unset it to take the "
            f"documented default, or give it a value."
        )
    return setting.value if setting.has_value else default


@dataclass(frozen=True, slots=True)
class Settings:
    """Deployment settings, resolved from the environment."""

    profile: str = "local"
    region: str = REGION
    audit_path: str = ":memory:"
    # External head anchor for the local hash-chained audit log (C9). A valid but TRUNCATED chain
    # is still internally consistent; only a head anchor kept outside the database exposes it.
    # Empty means "derive from audit_path" (see ``resolved_audit_anchor_path``); an on-disk log
    # therefore gets truncation detection by default rather than only when an adopter opts in.
    audit_anchor_path: str = ""
    policy_path: str = DEFAULT_POLICY_PATH
    iap_audience: str = ""
    iap_entitlements_json: str = ""
    # A local review queue must survive a process restart so a producer retry cannot create a
    # second maker-checker item.  This database belongs to Hrz7 only; producers keep their own
    # outboxes and never write it directly.
    # Explicit Settings construction remains ephemeral for unit tests and embedders. The running
    # local application uses ``load`` below, whose default is the durable on-disk database.
    review_db_path: str = ":memory:"
    # Was the profile chosen DELIBERATELY, or merely inherited from the fallback? ``load`` sets
    # this False when ``REVIEW_PROFILE`` is absent from the environment. Direct construction is
    # deliberate by definition (a caller named the profile in code), so the default is True.
    # The seeded-persona identity adapter refuses to serve when this is False: a maker-checker
    # control plane must never hand out an approver persona because an env var went missing.
    profile_explicit: bool = True

    def __post_init__(self) -> None:
        _validate_profile(self.profile)
        _validate_region(self.region)

    @property
    def runtime(self) -> str:
        """Where this process is running, as the UI banner states it: ``gcp`` or ``local``.

        Derived from the profile, never sniffed from the environment. A console that read
        its runtime from ``window.location`` would be right until the deployment served
        through a proxy and wrong silently after that, so the service is the one asked.
        """
        return "gcp" if self.profile in _MANAGED_PROFILES else "local"

    @property
    def generator_model(self) -> str:
        """Which model answers, for the UI banner (org decision, 2026-08-30).

        None does, and saying so is the point. This console declares no ``llm`` port at
        all: routing, SLA clocks and quorum are deterministic, and a reviewer's decision
        is a human's. ``no-model`` is materially different from
        ``deterministic-offline-stub``, which means a model-shaped port is bound to a
        stub, and a reviewer approving an escalation is entitled to know which of the two
        they are looking at.

        It is a constant here because the absence is structural rather than configured:
        there is no binding table to read it from. If this console ever grows an ``llm``
        port, this property has to be rewritten to read that binding -- which is the right
        amount of friction for adding a model to a human-review surface.
        """
        return "no-model"

    @property
    def resolved_audit_anchor_path(self) -> str:
        """Where the external chain-head anchor lives, or "" when anchoring cannot apply.

        An in-memory log has no tail to truncate between runs, so it needs no anchor. For an
        on-disk log the default is a sibling ``<audit_path>.anchor`` file, which an adopter
        SHOULD relocate to a different volume or trust domain (``REVIEW_AUDIT_ANCHOR_PATH``):
        an attacker who can rewrite both files can still rewrite both.
        """
        if self.audit_anchor_path:
            return self.audit_anchor_path
        if not self.audit_path or self.audit_path == ":memory:":
            return ""
        return f"{self.audit_path}.anchor"

    @classmethod
    def load(cls) -> Settings:
        choice = resolve_profile()
        return cls(
            profile=choice.profile,
            profile_explicit=choice.explicit,
            region=_setting("REVIEW_REGION", REGION),
            review_db_path=_setting("REVIEW_DB_PATH", "review-console.sqlite3"),
            audit_path=_setting("REVIEW_AUDIT_PATH", ":memory:"),
            audit_anchor_path=_setting("REVIEW_AUDIT_ANCHOR_PATH", ""),
            policy_path=_setting("REVIEW_POLICY_PATH", DEFAULT_POLICY_PATH),
            iap_audience=_setting("REVIEW_IAP_AUDIENCE", ""),
            iap_entitlements_json=_setting("REVIEW_IAP_ENTITLEMENTS_JSON", ""),
        )


class Container:
    """Lazy DI container: one ``cached_property`` per port, bound by the active profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _bind(self, port: str) -> object:
        table = _BINDINGS[port]
        target = table[self.settings.profile]
        module_path, _, cls_name = target.partition(":")
        adapter_cls = getattr(importlib.import_module(module_path), cls_name)
        return adapter_cls(self.settings)

    def _bind_identity(self) -> object:
        target = _IDENTITY_BINDINGS[self.settings.profile]
        module_path, _, cls_name = target.partition(":")
        adapter_cls = getattr(importlib.import_module(module_path), cls_name)
        return adapter_cls(self.settings)

    @cached_property
    def review_store(self) -> ReviewStorePort:
        adapter = self._bind("review_store")
        assert isinstance(adapter, ReviewStorePort)
        return adapter

    @cached_property
    def case_store(self) -> CaseStorePort:
        adapter = self._bind("case_store")
        assert isinstance(adapter, CaseStorePort)
        return adapter

    @cached_property
    def timers(self) -> TimerPort:
        adapter = self._bind("timers")
        assert isinstance(adapter, TimerPort)
        return adapter

    @cached_property
    def events(self) -> EventPublisherPort:
        adapter = self._bind("events")
        assert isinstance(adapter, EventPublisherPort)
        return adapter

    @cached_property
    def audit(self) -> AuditSinkPort:
        adapter = self._bind("audit")
        assert isinstance(adapter, AuditSinkPort)
        return adapter

    @cached_property
    def identity(self) -> IdentityPort:
        adapter = self._bind_identity()
        assert isinstance(adapter, IdentityPort)
        return adapter

    @cached_property
    def routing_policy(self) -> RoutingPolicy:
        """The bank-owned routing policy (B4), parsed from ``settings.policy_path``.

        A missing file means "ship the reference defaults"; a present file must parse, and an
        unreadable or invalid policy raises rather than silently downgrading the approval floors.
        """
        path = Path(self.settings.policy_path)
        if not path.is_file():
            return DEFAULT_ROUTING
        document = json.loads(path.read_text(encoding="utf-8"))
        section = document.get("policy", {}).get("routing", {})
        return RoutingPolicy.from_mapping(section)

    @cached_property
    def console(self) -> ConsoleService:
        """The review orchestrator, shared by the review API and the in-process router."""
        return ConsoleService(self.review_store, self.audit, policy=self.routing_policy)

    @cached_property
    def review_router(self) -> ReviewRouterPort:
        """R8 escalation seam, wired in-process to the SAME console the review API serves."""
        return InProcessReviewRouter(self.console)


def build_container(settings: Settings | None = None) -> Container:
    return Container(settings or Settings.load())


def identity_adapter_class(settings: Settings) -> type:
    """The identity adapter CLASS the active binding names, resolved WITHOUT constructing it.

    Reads the SAME :data:`_IDENTITY_BINDINGS` table :meth:`Container._bind_identity` binds from,
    so a deployment that rebound the identity port (the documented on-premises path: swap the
    placeholder for the client's own IdP adapter, ``docs/onprem-migration.md``) is answered about
    the adapter it ACTUALLY runs, not about the one the profile name suggests.

    Constructing is deliberately avoided: the seeded-persona adapter refuses to construct under
    an inherited profile, so a posture computed from an instance would be unobtainable in one of
    the exact cases it has to describe.
    """
    target = _IDENTITY_BINDINGS[settings.profile]
    module_path, _, cls_name = target.partition(":")
    resolved = getattr(importlib.import_module(module_path), cls_name)
    if not isinstance(resolved, type):
        raise TypeError(f"identity binding {target!r} does not name a class")
    return resolved


def end_user_auth_kind(settings: Settings | None = None) -> str:
    """What the BOUND identity adapter declares it does for end-user authentication.

    This is the one question "are this service's end-user routes authenticated?" reduces to.
    See :mod:`review_console.ports.identity` for why neither the profile string nor the presence
    of a service-to-service secret can answer it.

    Any failure to establish the answer resolves to
    :data:`~review_console.ports.identity.CLIENT_ASSERTED`. A guard that switches OFF because a
    lookup raised is a guard that fails open, and nothing is lost by failing closed here: the
    same failure surfaces loudly at the first request, when the container resolves the identical
    binding for real.
    """
    try:
        return declared_end_user_auth(identity_adapter_class(settings or Settings.load()))
    except Exception:  # noqa: BLE001 - a guard that fails open on a lookup error is no guard
        return CLIENT_ASSERTED
