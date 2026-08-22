"""FastAPI application for the Hrz7 Human-Review & Maker-Checker Console.

Import-safe (the Container is built at request time, never at import). Identity is a
server-verified Principal: the maker and the checker, their tenant and their groups all come from
the verified principal, and the client-asserted actor is discarded.

The profile is resolved ONCE, by ``config.resolve_profile``, and an absent ``REVIEW_PROFILE`` is
no choice rather than a silent ``local``. Every posture decision here keys off that one
resolution: S2S authentication, the CORS allowlist, the dev-persona header and the security-header
baseline. The exposure guard and the bind host key off it AND off the identity binding, for the
reason given below. An unknown or mis-capitalised value never gets this far: the
resolution below raises, so the process fails to boot rather than serving from a string nothing
binds. Detected and refused: an unauthenticated S2S submission when no profile was chosen (401,
so a forged maker/tenant cannot enter the queue). NOT authenticated, and deliberately so: an S2S
submission under a DELIBERATE ``REVIEW_PROFILE=local`` with ``REVIEW_S2S_TOKEN`` unset, which is
the zero-secret offline demo posture. That posture is bounded by EXPOSURE rather than by
authentication, and the bound is attached to the app OBJECT below, not to ``main()``: the
Dockerfile ``CMD`` and the ``make run-api`` target both serve ``review_console.api.app:app``
through uvicorn, so a guard reachable only from ``main()`` never runs in a shipped process. The
``main()`` bind guard is kept as a second layer for the one entry point that does call it.

The fail-closed network defaults come from the commons: the unauthenticated posture is refused
to any non-loopback (or proxied) peer unless explicitly opted out, a profile that cannot
authenticate an end user binds loopback, and CORS never falls back to ``*``.

WHAT SWITCHES THE EXPOSURE GUARD OFF is one thing and one thing only: the identity adapter bound
to the identity port declaring that it VERIFIES the end user (see ``ports/identity.py``). The
guard exists to bound routes that answer an end user with no credential, so the question it has
to settle is whether an end user CAN be authenticated here, and only the bound adapter knows.
Deriving it from the profile string plus the ABSENCE of ``REVIEW_S2S_TOKEN`` is wrong in the most
dangerous direction: that secret authenticates a calling SERVICE and no end user at all, so
SETTING it disables the guard for exactly the end-user routes it protects. A LAN peer with no
Authorization header then submits a maker-checker item as ``demo.approver@bank.example`` in
tenant ``demo-bank``, reads the tenant's queue back, and signs off another item as a checker:
four-eyes (P-06) defeated with no credential at all.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Sequence
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from hex_service_kit.identity import IdentityError, IdentityPort, Principal, RequestContext
from hex_service_kit.netdefaults import (
    EnvSetting,
    cors_allowlist,
    read_env_setting,
    resolve_bind_host,
)
from hex_service_kit.web import (
    add_loopback_exposure_guard,
    add_security_headers,
    make_require_service_caller,
)

from .. import __version__
from ..config import (
    Container,
    ProfileChoice,
    Settings,
    build_container,
    end_user_auth_kind,
    resolve_profile,
)
from ..domain.cases.sample_workflows import SAMPLE_DEFINITIONS
from ..domain.cases.workflow_service import (
    CaseNotFound,
    CaseWorkflowService,
    IllegalTransition,
    UnknownWorkflow,
)
from ..domain.console_service import AlreadyResolved, ConsoleService, ReviewNotFound
from ..domain.kernel import Citation
from ..ports.identity import VERIFIED, EndUserAuthUnavailableError
from .schemas import (
    AssessmentModel,
    CaseModel,
    CaseSummaryModel,
    DecisionRequest,
    DecisionResponse,
    HealthResponse,
    OpenCaseRequest,
    ReviewItemModel,
    ServiceSubmitRequest,
    SubmitRequest,
    TransitionRequest,
    WorkflowModel,
)

_CHOICE = resolve_profile()
# The workflow registry a deployment overrides per vertical; the platform ships a sample.
_DEFINITIONS = SAMPLE_DEFINITIONS


@lru_cache(maxsize=1)
def _container() -> Container:
    return build_container(Settings.load())


def _console() -> ConsoleService:
    # The SAME console the in-process review router submits into, so an escalated case and a
    # directly-submitted review land in one shared queue.
    return _container().console


def _case_service() -> CaseWorkflowService:
    c = _container()
    return CaseWorkflowService(
        c.case_store,
        c.audit,
        definitions=_DEFINITIONS,
        events=c.events,
        timers=c.timers,
        review_router=c.review_router,
    )


def _identity() -> IdentityPort:
    return _container().identity


def get_principal(request: Request) -> Principal:
    """Resolve the VERIFIED end-user principal, or refuse with a status AND a reason.

    The client-asserted actor in the request body is never read; identity flows from here.

    ``hex_service_kit.web.make_get_principal`` is not used, deliberately. It collapses every
    :class:`~hex_service_kit.identity.IdentityError` into a bare 401 carrying "authentication
    required", which is the right answer for a caller who could have authenticated and did not,
    and the wrong one for a deployment that can authenticate NOBODY. An operator reading that
    401 goes looking for a missing credential when the truth is that the bound adapter is an
    unimplemented placeholder or refused to construct at all, and no credential would have
    helped. Those cases raise ``ports/identity.py``'s
    :class:`EndUserAuthUnavailableError`, which carries its own status and its own message, and
    this is where the two are told apart.
    """
    try:
        identity = _identity()
        ctx = RequestContext(headers={k.lower(): v for k, v in request.headers.items()})
        return identity.resolve(ctx)
    except EndUserAuthUnavailableError as exc:
        raise HTTPException(status_code=exc.http_status, detail=str(exc)) from exc
    except IdentityError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required"
        ) from exc


_authenticate_service_caller = make_require_service_caller(
    lambda request: _request_choice(request).exposure_profile,
    token_env="REVIEW_S2S_TOKEN",
    allowed_callers_env="REVIEW_S2S_ALLOWED_CALLERS",
    audience_env="REVIEW_S2S_AUDIENCE",
)


def _request_choice(request: Request) -> ProfileChoice:
    choice = getattr(request.app.state, "profile_choice", None)
    return choice if isinstance(choice, ProfileChoice) else _CHOICE


def require_service_caller(request: Request) -> None:
    """Authenticate the calling SERVICE, refusing to decide at all without a chosen profile.

    The commons dependency picks its scheme from the profile string: a Google-signed OIDC ID
    token under a secure profile, the shared-secret bearer otherwise. The shared-secret path
    stays OPEN when ``REVIEW_S2S_TOKEN`` is unset (loopback dev with zero secrets), so an
    UNSET ``REVIEW_PROFILE`` must never be allowed to select it: that combination let an
    unauthenticated caller POST a forged maker and tenant into the maker-checker queue. When
    no profile was chosen, no scheme was chosen either, and the answer is 401.

    Known limit, stated rather than papered over: with ``REVIEW_PROFILE=local`` chosen
    DELIBERATELY and ``REVIEW_S2S_TOKEN`` unset, these endpoints remain unauthenticated. That
    is the offline demo posture, and it is bounded by EXPOSURE rather than by this dependency.
    The bound is the ``add_loopback_exposure_guard`` middleware registered on the app object
    below, so it holds however the app was started; the ``resolve_bind_host`` call in ``main()``
    is the same bound applied a second time, at start-up, for the one entry point that runs it.

    SETTING the secret closes this dependency and nothing else. It does not make the end-user
    routes authenticated and it does not relax the exposure guard, which reads the identity
    binding and never this variable. Under the ``local`` profile the guard therefore keeps the
    whole app, S2S routes included, on loopback: this token is a shared secret in a
    seeded-persona demo posture, not a reason to accept LAN callers. Choose a profile whose
    identity adapter verifies an assertion for that, or opt in with
    ``REVIEW_ALLOW_INSECURE_DEMO=1``.
    """
    if not _request_choice(request).service_auth_configured:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "service-to-service authentication is unconfigured: REVIEW_PROFILE is not set, "
                "so no authentication scheme has been chosen"
            ),
        )
    _authenticate_service_caller(request)


app = FastAPI(
    title="Hrz7 Human-Review & Maker-Checker Console",
    version=__version__,
    description="Tenant-partitioned review queue, four-eyes / SoD routing, WORM sign-off. "
    "The system enforcer for principle P-06. Also hosts the case, clock & workflow "
    "engine (state machine, SLA / regulatory clocks, in-process escalation). Region "
    "asia-southeast1.",
)
app.state.profile_choice = _CHOICE
app.state.profile = _CHOICE.profile

# Every relaxation below keys off ``exposure_profile``, never the raw profile: an unset
# REVIEW_PROFILE is not consent, so it gets no CORS allowlist, no dev-persona header and HSTS.
_EXPOSURE = _CHOICE.exposure_profile

# REVIEW_FRAME_ANCESTORS is the CSP frame-ancestors allowlist of parent origins permitted to
# frame the console. Terraform sets it on the Cloud Run service and .env.example documents it,
# so it is a real deploy-time input on both surfaces, not a local-only knob.
_FRAME_ANCESTORS_ENV = "REVIEW_FRAME_ANCESTORS"
_CORS_ORIGINS_ENV = "REVIEW_CORS_ORIGINS"


#: Entries that are a wildcard by BEHAVIOUR rather than by spelling, so the asterisk test below
#: cannot see them. ``null`` is the one that matters: a sandboxed iframe presents a null origin,
#: so ``frame-ancestors null`` admits framing from a document whose own origin the browser has
#: already decided not to trust, and a null CORS origin trusts the same document WITH
#: credentials. ``'*'`` is the quoted form CSP also honours and ``*.*`` is the subdomain
#: wildcard; both carry an asterisk, and both are named here so the set reads as the complete
#: refusal rather than as a list of leftovers. Matching is exact, so ``https://nullify.example``
#: remains a perfectly good origin. ``ui/lib/security-headers.mjs`` refuses the same set.
_WILDCARD_TOKENS = frozenset({"*", "'*'", "null", "*.*"})


def _refuse_wildcard(origins: Sequence[str], variable: str) -> None:
    """A wildcard in an origin policy is the policy switched off, so it never boots.

    Both allowlists resolved their unset and emptied states carefully and then passed the
    value on verbatim, so a wildcard reached ``CORSMiddleware(allow_origins=[...])`` and
    ``Content-Security-Policy: frame-ancestors ...``. On a console that shows tenant-partitioned
    review queues, and with ``allow_credentials=True``, that lets any page on the internet
    frame it and read its responses cross-origin. The prohibition was written down in a
    comment beside each variable, and in the shared kit's docstring for CORS, and enforced by
    neither.

    A check of ``"*" in origins`` is a MEMBERSHIP test over the sequence, not a
    test of each entry, so it sees an entry that IS an asterisk and nothing else. Every other
    spelling walks through. ``https://*.evil.example`` is the one that costs most, because CSP
    honours that host-source form, so every subdomain could frame the console, including one
    obtained by takeover or serving user content. So the rule is now a UNION over each entry:
    an asterisk ANYWHERE in it, or the whole entry being one of :data:`_WILDCARD_TOKENS`. A
    legitimate origin holds no asterisk, so the first half refuses nothing configurable, and
    the second half exists for the behavioural wildcards that carry none.

    Raised where the value is RESOLVED, which is module import, so an operator whose config
    template rendered a wildcard finds out when the service refuses to start rather than when
    a browser somewhere exercises it.
    """
    offending = [origin for origin in origins if "*" in origin or origin in _WILDCARD_TOKENS]
    if offending:
        raise ValueError(
            f"{variable} contains {offending[0]!r}: the origin policy must never contain a "
            "wildcard. Name the exact parent or caller origins instead, or unset the variable "
            "to keep the shipped default."
        )


def _cors_origins(exposure: str) -> list[str]:
    """The CORS allowlist for an exposure profile, resolved through the shared kit.

    The local refusal runs FIRST, on the raw configured value, rather than on what the kit
    hands back. ``cors_allowlist`` now refuses the same wildcards itself, so on the old order
    the kit raised its own ``InsecureCorsError`` before this module's rule was ever reached and
    the policy quietly changed owner. Refusing on the way in keeps :func:`_refuse_wildcard` the
    one authority over both allowlists: a single exception type and a single message naming the
    variable an operator must fix, whether the value came from CORS or from frame-ancestors.
    The kit's check stays as an unreachable backstop, which is what a backstop should be.
    """
    configured = read_env_setting(_CORS_ORIGINS_ENV).value
    _refuse_wildcard(
        [origin.strip() for origin in configured.split(",") if origin.strip()], _CORS_ORIGINS_ENV
    )
    return cors_allowlist(exposure, origins_env=_CORS_ORIGINS_ENV)


def _frame_ancestors(setting: EnvSetting) -> str:
    """Three-state read of ``REVIEW_FRAME_ANCESTORS``; an emptied value REFUSES to boot.

    Unset is not a member of the valid value set, so this resolves three states rather than
    two. Unset keeps the shipped ``'self'``. Set to a value naming no origin would reach
    ``add_security_headers`` as ``""`` and emit the header
    ``Content-Security-Policy: frame-ancestors`` with an EMPTY directive: browsers discard
    that as a parse error, and the ``== "'self'"`` branch that adds ``X-Frame-Options`` is
    skipped as well, so the clickjacking control would vanish from both channels at once with
    nothing in the response to show it.

    An empty string is not a usable value for this read, so it refuses at boot rather than
    serving a posture nobody chose. A total lockdown stays expressible: set the variable to
    ``'none'``. Refusing is loud and immediate (uvicorn imports this module at start-up).
    """
    if setting.is_unset:
        return "'self'"
    ancestors = " ".join(setting.value.split())
    if not ancestors:
        raise ValueError(
            f"{_FRAME_ANCESTORS_ENV} is set to an empty value: it names no parent origin, and "
            "an empty CSP frame-ancestors directive is a parse error that browsers discard, "
            "taking the clickjacking restriction with it. Unset it to keep the shipped "
            "'self' default, or set it to 'none' to refuse all framing."
        )
    _refuse_wildcard(ancestors.split(), _FRAME_ANCESTORS_ENV)
    return ancestors


# Until now this variable was set by infra/terraform and documented in .env.example and the
# README as honoured by BOTH surfaces, while the API passed no value at all and hard-coded the
# commons default. An operator who narrowed or widened the allowlist changed the document layer
# only, and had no way to tell from the API response that half the configuration was inert.
_FRAME_ANCESTORS = _frame_ancestors(read_env_setting(_FRAME_ANCESTORS_ENV))
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(_EXPOSURE),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"]
    + (["X-Dev-Persona"] if _EXPOSURE == "local" else []),
)
add_security_headers(app, frame_ancestors=_FRAME_ANCESTORS, profile=_EXPOSURE)

# A request arrives with nothing authenticating the END USER unless BOTH of these hold, and the
# guard bounds every case where either fails:
#
#   1. a profile was chosen. Absent that, nobody selected an identity scheme OR an S2S scheme;
#      the seeded-persona adapter refuses to construct and every S2S route answers 401, but
#      /healthz and /v1/workflows would still answer a stranger, and a deployment in that state
#      has no business being reachable at all. It is also the one case where a rebinding that
#      named a verifying adapter under ``local`` must NOT buy the relaxation: unset is not
#      consent, whatever the binding says;
#   2. the identity adapter the active binding names DECLARES that it verifies the end user.
#      Seeded personas arrive on a header the caller wrote (client-asserted) and the on-premises
#      placeholder resolves nobody at all (unimplemented); neither authenticates anyone, so
#      neither may switch this off.
#
# Note what is NOT in this expression: REVIEW_S2S_TOKEN. A service credential is evidence about
# a calling SERVICE and says nothing about the end-user routes, so setting one must not, and now
# cannot, disable their bound. The S2S routes are bounded by `require_service_caller` above,
# which is where a service credential belongs.
_END_USER_AUTH = end_user_auth_kind()
_END_USER_AUTHENTICATED = _CHOICE.explicit and _END_USER_AUTH == VERIFIED

# The RESTRICTION's profile string. `bind_profile` already reads an unconsented run as `local`
# (the confined case); this widens the same rule to every posture that cannot authenticate an
# end user, so the start-up bound in `main()` and the request-time guard below agree instead of
# one binding every interface while the other refuses every caller on it.
_BIND_PROFILE = _CHOICE.bind_profile if _END_USER_AUTHENTICATED else "local"

# Registered LAST, so it is the OUTERMOST middleware: an off-loopback caller is refused before
# CORS, before the header baseline and before any route or dependency runs. This is the bound
# that five documents attribute to the loopback bind guard, put where the service actually
# serves; ``main()`` keeps the start-up half for the entry point that calls it.
#
# ``posture`` is the EXPOSURE profile, so a run nobody configured names itself 'unconfigured' in
# the refusal rather than borrowing the name of a profile an operator never chose.
add_loopback_exposure_guard(
    app,
    unauthenticated=not _END_USER_AUTHENTICATED,
    insecure_demo_env="REVIEW_ALLOW_INSECURE_DEMO",
    posture=_EXPOSURE,
)


@app.post(
    "/v1/reviews",
    response_model=ReviewItemModel,
    status_code=status.HTTP_201_CREATED,
    tags=["reviews"],
)
def submit_review(
    request: SubmitRequest,
    principal: Annotated[Principal, Depends(get_principal)],
) -> ReviewItemModel:
    """Enqueue an item for human review. The maker and tenant are the verified principal."""
    item = _console().submit(
        review_id=uuid.uuid4().hex,
        maker=principal.actor,
        tenant=principal.tenant,
        action=request.action,
        subject=request.subject,
        summary=request.summary,
        severity=request.severity,
        required_approvals=request.required_approvals,
        sod_group=request.sod_group,
        case_ref=request.case_ref,
        citations=tuple(
            Citation(source_id=c.source_id, title=c.title, snippet=c.snippet)
            for c in request.citations
        ),
    )
    return ReviewItemModel.from_domain(item)


@app.post(
    "/v1/service/reviews",
    response_model=ReviewItemModel,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_service_caller)],
    tags=["reviews"],
)
def submit_review_service(request: ServiceSubmitRequest) -> ReviewItemModel:
    """Enqueue a review submitted by a trusted SERVICE (the S2S producer half of rule R8).

    Authenticated as the calling service (fail-closed S2S), not the end user, so the maker and
    tenant are taken from the (trusted) request body. This is the endpoint the built producers
    submit their ``requires_human_review`` escalations to via ``review-kit``.
    """
    # A producer may retry after its request reached Hrz7 but before it observed the response.
    # The store atomically returns the original item (including terminal state) rather than
    # creating a second review. Tenant is part of the unique key, preserving isolation.
    item = _console().submit_idempotent(
        review_id=uuid.uuid4().hex,
        maker=request.maker,
        tenant=request.tenant,
        action=request.action,
        subject=request.subject,
        summary=request.summary,
        severity=request.severity,
        required_approvals=request.required_approvals,
        sod_group=request.sod_group,
        case_ref=request.case_ref,
        citations=tuple(
            Citation(source_id=c.source_id, title=c.title, snippet=c.snippet)
            for c in request.citations
        ),
        source_key=request.source_key,
    )
    return ReviewItemModel.from_domain(item)


@app.get("/v1/reviews", response_model=list[ReviewItemModel], tags=["reviews"])
def list_reviews(
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[ReviewItemModel]:
    """The pending review queue for the caller's tenant only (fail-closed partition)."""
    items = _console().list_queue(principal.tenant)
    return [ReviewItemModel.from_domain(i) for i in items]


@app.get("/v1/reviews/{review_id}", response_model=ReviewItemModel, tags=["reviews"])
def get_review(
    review_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
) -> ReviewItemModel:
    """Fetch one item within the caller's tenant. A cross-tenant id is a 404, never a leak."""
    try:
        item = _console().get(principal.tenant, review_id)
    except ReviewNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="review not found") from exc
    return ReviewItemModel.from_domain(item)


@app.post("/v1/reviews/{review_id}/decision", response_model=DecisionResponse, tags=["reviews"])
def decide_review(
    review_id: str,
    request: DecisionRequest,
    principal: Annotated[Principal, Depends(get_principal)],
    response: Response,
) -> DecisionResponse:
    """Approve / reject / amend an item. The checker is the verified principal.

    Fail-closed: a self-approval, cross-tenant, missing-role, SoD or duplicate-approver attempt
    returns 403 with the findings and records a DENIED sign-off. Nothing auto-executes.
    """
    try:
        outcome = _console().dispose(
            review_id=review_id,
            checker=principal.actor,
            checker_tenant=principal.tenant,
            checker_groups=principal.principals,
            disposition=request.disposition,
            reason=request.reason,
            amendments=tuple(request.amendments),
        )
    except ReviewNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="review not found") from exc
    except AlreadyResolved as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if not outcome.allowed:
        response.status_code = status.HTTP_403_FORBIDDEN
    return DecisionResponse.from_outcome(outcome)


# ---- case, clock & workflow engine ---------------------------------------------------------
# Additive routes: no collision with the frozen review API. Cloud Tasks' OIDC callback POSTs
# /v1/cases/{id}/evaluate on this same service.


@app.post(
    "/v1/cases",
    response_model=CaseModel,
    status_code=status.HTTP_201_CREATED,
    tags=["cases"],
)
def open_case(
    request: OpenCaseRequest,
    principal: Annotated[Principal, Depends(get_principal)],
) -> CaseModel:
    """Open a case in the workflow's initial state; actor and tenant are the verified principal."""
    if request.case_type not in _DEFINITIONS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unknown case_type {request.case_type!r}",
        )
    case = _case_service().open_case(
        case_id=uuid.uuid4().hex,
        tenant=principal.tenant,
        case_type=request.case_type,
        actor=principal.actor,
        severity=request.severity,
        attributes=request.attributes,
        summary=request.summary,
    )
    return CaseModel.from_domain(case, _DEFINITIONS[case.case_type])


@app.get("/v1/cases", response_model=list[CaseSummaryModel], tags=["cases"])
def list_cases(
    principal: Annotated[Principal, Depends(get_principal)],
) -> list[CaseSummaryModel]:
    """List the caller's tenant's cases (fail-closed partition)."""
    return [CaseSummaryModel.from_domain(c) for c in _case_service().list_cases(principal.tenant)]


@app.get("/v1/cases/{case_id}", response_model=CaseModel, tags=["cases"])
def get_case(
    case_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
) -> CaseModel:
    """Fetch one case within the caller's tenant. A cross-tenant id is a 404, never a leak."""
    try:
        case = _case_service().get(principal.tenant, case_id)
    except CaseNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="case not found") from exc
    return CaseModel.from_domain(case, _DEFINITIONS[case.case_type])


@app.post("/v1/cases/{case_id}/transition", response_model=CaseModel, tags=["cases"])
def transition_case(
    case_id: str,
    request: TransitionRequest,
    principal: Annotated[Principal, Depends(get_principal)],
) -> CaseModel:
    """Advance a case to a new state; an illegal transition is refused with 409."""
    try:
        case = _case_service().transition_case(
            case_id=case_id,
            tenant=principal.tenant,
            to_state=request.to_state,
            actor=principal.actor,
            reason=request.reason,
        )
    except CaseNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="case not found") from exc
    except IllegalTransition as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except UnknownWorkflow as exc:  # pragma: no cover - guarded at open time
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return CaseModel.from_domain(case, _DEFINITIONS[case.case_type])


@app.post("/v1/cases/{case_id}/evaluate", response_model=AssessmentModel, tags=["cases"])
def evaluate_case(
    case_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
) -> AssessmentModel:
    """Assess the case's clocks and state now; a breach or stall escalates softly (in-process)."""
    try:
        assessment = _case_service().evaluate_case(
            case_id=case_id, tenant=principal.tenant, actor=principal.actor
        )
    except CaseNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="case not found") from exc
    return AssessmentModel.from_domain(assessment)


@app.get("/v1/workflows", response_model=list[WorkflowModel], tags=["ops"])
def workflows() -> list[WorkflowModel]:
    """The registered workflow definitions (case types the engine knows about)."""
    return [WorkflowModel.from_domain(d) for d in _DEFINITIONS.values()]


@app.post("/v1/audit/ping", dependencies=[Depends(require_service_caller)], tags=["ops"])
def audit_ping() -> dict[str, bool]:
    """A stand-in S2S endpoint, guarded by fail-closed calling-service authentication."""
    return {"ok": True}


@app.get("/healthz", response_model=HealthResponse, tags=["ops"])
def healthz() -> HealthResponse:
    settings = _container().settings
    return HealthResponse(status="ok", profile=settings.profile, region=settings.region)


@app.get("/v1/personas", tags=["ops"])
def personas() -> list[dict[str, str]]:
    """List seeded dev personas for the local persona picker (empty outside local).

    The seeded-persona adapter REFUSES to construct when the local profile was inherited rather
    than chosen, so this reports that refusal as a 503 with its reason instead of a bare 500: a
    picker that silently shows nothing looks like a UI bug, not the configuration error it is.
    """
    try:
        identity = _container().identity
    except IdentityError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    lister = getattr(identity, "personas", None)
    if lister is None:
        return []
    return [dict(p) for p in lister()]


def main() -> None:
    """Run the API locally with uvicorn; fail-closed loopback bind whenever no end user can auth.

    The SECOND layer, not the only one. This refuses to BIND a non-loopback interface, which is
    the earlier and clearer failure, but it runs only when the process is started through this
    function. The shipped entry points are not: the Dockerfile ``CMD`` and ``make run-api`` both
    hand ``review_console.api.app:app`` to uvicorn. The bound that always applies is the
    ``add_loopback_exposure_guard`` middleware registered on the app object above.
    """
    import uvicorn

    # ``_BIND_PROFILE``, not ``exposure_profile``: this guard treats ``local`` as the RESTRICTIVE
    # case (loopback only), so an unconsented run, and any other posture with no verified
    # end-user identity, must look like ``local`` here even though an unconsented one looks like
    # ``unconfigured`` to every relaxation above.
    host = resolve_bind_host(
        _BIND_PROFILE,
        host_env="REVIEW_API_HOST",
        insecure_demo_env="REVIEW_ALLOW_INSECURE_DEMO",
    )
    uvicorn.run(app, host=host, port=int(os.environ.get("PORT", "8087")))


if __name__ == "__main__":
    main()
