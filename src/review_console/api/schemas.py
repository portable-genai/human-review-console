"""API request / response schemas (Pydantic) mapped to / from the pure-domain models.

None of the request models carry a ``maker``, ``checker``, ``tenant`` or ``actor`` field: those
come only from the server-verified principal, never the request body, so a caller can never
assert an identity, a tenant or an entitlement they do not hold.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..domain.cases.models import Case, CaseAssessment, WorkflowDefinition
from ..domain.cases.state_machine import legal_next_states
from ..domain.kernel import Disposition, Severity
from ..domain.maker_checker_service import DispositionOutcome
from ..domain.models import ReviewItem


class CitationModel(BaseModel):
    source_id: str
    title: str
    snippet: str = ""


class SubmitRequest(BaseModel):
    """A maker submits an item for review. Maker + tenant are stamped from the principal."""

    action: str = Field(..., description="What is being approved, e.g. 'disburse_loan'.")
    subject: str
    summary: str = ""
    severity: Severity = Severity.MEDIUM
    required_approvals: int = Field(1, ge=1, le=8)
    sod_group: str = Field("", description="The maker's segregation-of-duties group (policy).")
    case_ref: str = Field("", description="Optional link to a case.")
    citations: list[CitationModel] = []


class ServiceSubmitRequest(SubmitRequest):
    """A trusted SERVICE (an authenticated S2S caller) submits on a maker's behalf.

    Unlike the per-user submit, this path carries the ``maker`` and ``tenant`` in the body: the
    intake is authenticated as the calling SERVICE (not the end user), so the service asserts on
    whose behalf the review is raised. Per-hop OBO token-exchange is the deferred next layer.
    """

    maker: str = Field(..., description="The identity that originated the underlying decision.")
    tenant: str = Field(..., description="The tenant the review belongs to.")
    source_key: str = Field(
        "",
        max_length=255,
        description="Stable producer-owned idempotency key, unique within this tenant.",
    )


class DecisionRequest(BaseModel):
    """A checker's disposition. Checker identity + groups + tenant come from the principal."""

    disposition: Disposition
    reason: str = ""
    amendments: list[str] = []


class ApprovalModel(BaseModel):
    checker: str
    reason: str


class ReviewItemModel(BaseModel):
    review_id: str
    tenant: str
    source_key: str
    action: str
    maker: str
    subject: str
    summary: str
    severity: str
    required_approvals: int
    sod_group: str
    case_ref: str
    state: str
    approvals_count: int
    approvals: list[ApprovalModel]
    citations: list[CitationModel]

    @classmethod
    def from_domain(cls, item: ReviewItem) -> ReviewItemModel:
        req = item.request
        return cls(
            review_id=req.review_id,
            tenant=req.tenant,
            source_key=req.source_key,
            action=req.action,
            maker=req.maker,
            subject=req.subject,
            summary=req.summary,
            severity=req.severity.value,
            required_approvals=req.required_approvals,
            sod_group=req.sod_group,
            case_ref=req.case_ref,
            state=item.state.value,
            approvals_count=item.approvals_count,
            approvals=[ApprovalModel(checker=a.checker, reason=a.reason) for a in item.approvals],
            citations=[
                CitationModel(source_id=c.source_id, title=c.title, snippet=c.snippet)
                for c in req.citations
            ],
        )


class DecisionResponse(BaseModel):
    decision: str
    findings: list[str]
    item: ReviewItemModel

    @classmethod
    def from_outcome(cls, outcome: DispositionOutcome) -> DecisionResponse:
        return cls(
            decision=outcome.decision.value,
            findings=[f.value for f in outcome.findings],
            item=ReviewItemModel.from_domain(outcome.item),
        )


class HealthResponse(BaseModel):
    status: str
    profile: str
    #: Provenance the UI banner states on every page: where the runtime sits and which
    #: model answers. Derived server-side so the console never guesses (org decision,
    #: 2026-08-30).
    runtime: str = "local"  # "gcp" | "local"
    generator_model: str = "no-model"
    region: str


# ---- case, clock & workflow engine schemas --------------------------------------------------
# Additive: no request model carries an ``actor`` / ``tenant`` (those come from the principal).


class OpenCaseRequest(BaseModel):
    case_type: str
    severity: Severity = Severity.MEDIUM
    summary: str = ""
    attributes: dict[str, str] = {}


class TransitionRequest(BaseModel):
    to_state: str
    reason: str = ""


class TransitionModel(BaseModel):
    seq: int
    from_state: str
    to_state: str
    actor: str
    reason: str
    at: str


class CaseModel(BaseModel):
    case_id: str
    tenant: str
    case_type: str
    state: str
    severity: str
    opened_at: str
    history: list[TransitionModel]
    attributes: dict[str, str]
    legal_next_states: list[str]

    @classmethod
    def from_domain(cls, case: Case, definition: WorkflowDefinition) -> CaseModel:
        return cls(
            case_id=case.case_id,
            tenant=case.tenant,
            case_type=case.case_type,
            state=case.state,
            severity=case.severity.value,
            opened_at=case.opened_at.isoformat(),
            history=[
                TransitionModel(
                    seq=t.seq,
                    from_state=t.from_state,
                    to_state=t.to_state,
                    actor=t.actor,
                    reason=t.reason,
                    at=t.at.isoformat(),
                )
                for t in case.history
            ],
            attributes=dict(case.attributes),
            legal_next_states=list(legal_next_states(case, definition)),
        )


class DeadlineModel(BaseModel):
    clock: str
    kind: str
    due_at: str | None
    remaining_days: int
    breached: bool
    approaching: bool


class AssessmentModel(BaseModel):
    case_id: str
    state: str
    severity: str
    deadlines: list[DeadlineModel]
    findings: list[str]
    requires_human_review: bool

    @classmethod
    def from_domain(cls, a: CaseAssessment) -> AssessmentModel:
        return cls(
            case_id=a.case_id,
            state=a.state,
            severity=a.severity.value,
            deadlines=[
                DeadlineModel(
                    clock=d.clock,
                    kind=d.kind,
                    due_at=d.due_at.isoformat() if d.due_at else None,
                    remaining_days=d.remaining_days,
                    breached=d.breached,
                    approaching=d.approaching,
                )
                for d in a.deadlines
            ],
            findings=[f.value for f in a.findings],
            requires_human_review=a.requires_human_review,
        )


class CaseSummaryModel(BaseModel):
    case_id: str
    case_type: str
    state: str
    severity: str

    @classmethod
    def from_domain(cls, case: Case) -> CaseSummaryModel:
        return cls(
            case_id=case.case_id,
            case_type=case.case_type,
            state=case.state,
            severity=case.severity.value,
        )


class WorkflowModel(BaseModel):
    case_type: str
    states: list[str]
    initial: str
    terminal: list[str]

    @classmethod
    def from_domain(cls, d: WorkflowDefinition) -> WorkflowModel:
        return cls(
            case_type=d.case_type,
            states=list(d.states),
            initial=d.initial,
            terminal=sorted(d.terminal),
        )
