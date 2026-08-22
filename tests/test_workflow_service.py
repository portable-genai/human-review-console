"""The orchestrator: open / transition / evaluate, tenant partition, redact-before-audit, timers.

The R8 escalation tests assert against the console's own review queue: the review router is
``InProcessReviewRouter``, wired to the live ``ConsoleService`` in this service, so an escalation
lands directly in the store the API serves rather than in a stand-alone router outbox.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from review_console.adapters.local.audit import LocalAuditAdapter
from review_console.adapters.local.case_store import LocalCaseStore
from review_console.adapters.local.events import LocalEventPublisher
from review_console.adapters.local.review_store import LocalReviewStore
from review_console.adapters.local.timers import LocalTimerAdapter
from review_console.adapters.review_router import InProcessReviewRouter
from review_console.config import Settings
from review_console.domain.cases.kernel import CaseDecision
from review_console.domain.cases.sample_workflows import SAMPLE_DEFINITIONS
from review_console.domain.cases.state_machine import IllegalTransition
from review_console.domain.cases.workflow_service import CaseNotFound, CaseWorkflowService
from review_console.domain.console_service import ConsoleService

MON = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)


def _service() -> tuple[
    CaseWorkflowService, LocalAuditAdapter, LocalTimerAdapter, LocalEventPublisher
]:
    store = LocalCaseStore(Settings(profile="local"))
    audit = LocalAuditAdapter(Settings(profile="local", audit_path=":memory:"))
    timers = LocalTimerAdapter(Settings(profile="local"))
    events = LocalEventPublisher(None)
    service = CaseWorkflowService(
        store, audit, definitions=SAMPLE_DEFINITIONS, events=events, timers=timers
    )
    return service, audit, timers, events


def _service_with_console() -> tuple[CaseWorkflowService, ConsoleService]:
    """A workflow service whose review router hands escalations to a live in-process console."""
    store = LocalCaseStore(Settings(profile="local"))
    audit = LocalAuditAdapter(Settings(profile="local", audit_path=":memory:"))
    console = ConsoleService(LocalReviewStore(Settings(profile="local")), audit)
    router = InProcessReviewRouter(console)
    service = CaseWorkflowService(
        store, audit, definitions=SAMPLE_DEFINITIONS, review_router=router
    )
    return service, console


def test_escalation_routes_a_review_to_the_console() -> None:
    """Rule R8: a case that breaches is routed in-process into the console's review queue."""
    service, console = _service_with_console()
    service.open_case(case_id="c1", tenant="demo-bank", case_type="complaint", actor="a", as_of=MON)
    fri = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)  # past the 2-business-day ack deadline

    # Before evaluation, nothing is routed.
    assert console.list_queue("demo-bank") == []

    assessment = service.evaluate_case(case_id="c1", tenant="demo-bank", as_of=fri)
    assert assessment.requires_human_review

    routed = console.list_queue("demo-bank")
    assert len(routed) == 1
    review = routed[0].request
    assert review.tenant == "demo-bank"
    assert review.case_ref == "c1"
    assert review.action == "case_review:complaint"


def test_no_escalation_routes_nothing() -> None:
    """A case within its deadline is not routed: the R8 hand-off fires only on escalation."""
    service, console = _service_with_console()
    service.open_case(case_id="c1", tenant="demo-bank", case_type="complaint", actor="a", as_of=MON)
    service.evaluate_case(case_id="c1", tenant="demo-bank", as_of=MON)  # same day, on track
    assert console.list_queue("demo-bank") == []


def test_open_schedules_clocks_and_emits_event() -> None:
    service, audit, timers, events = _service()
    case = service.open_case(
        case_id="c1", tenant="demo-bank", case_type="complaint", actor="a", as_of=MON
    )
    assert case.state == "received"
    # Both clocks (acknowledgement, resolution) start in "received", so both are scheduled.
    assert {clock for (_, _, clock) in timers.scheduled()} == {"acknowledgement", "resolution"}
    assert [e.event_type for e in events.published()] == ["case.opened"]
    assert audit.log.verify_chain().ok


def test_transition_records_and_cancels_clocks_on_terminal() -> None:
    service, _, timers, events = _service()
    service.open_case(case_id="c1", tenant="demo-bank", case_type="complaint", actor="a", as_of=MON)
    service.transition_case(
        case_id="c1",
        tenant="demo-bank",
        to_state="under_review",
        actor="a",
        reason="triage",
        as_of=MON,
    )
    service.transition_case(
        case_id="c1", tenant="demo-bank", to_state="resolved", actor="a", reason="done", as_of=MON
    )
    # Terminal reached: clocks cancelled.
    assert timers.scheduled() == {}
    assert [e.event_type for e in events.published()] == [
        "case.opened",
        "case.transitioned",
        "case.transitioned",
    ]


def test_illegal_transition_records_a_rejected_audit_and_raises() -> None:
    service, audit, _, _ = _service()
    service.open_case(case_id="c1", tenant="demo-bank", case_type="complaint", actor="a", as_of=MON)
    with pytest.raises(IllegalTransition):
        service.transition_case(
            case_id="c1",
            tenant="demo-bank",
            to_state="resolved",
            actor="a",
            reason="skip",
            as_of=MON,
        )
    rejected = [r for r in audit.log.read_all() if r.get("decision") == CaseDecision.REJECTED.value]
    assert rejected, "an illegal transition must leave a REJECTED audit record"


def test_cross_tenant_get_is_not_found() -> None:
    service, _, _, _ = _service()
    service.open_case(case_id="c1", tenant="demo-bank", case_type="complaint", actor="a", as_of=MON)
    with pytest.raises(CaseNotFound):
        service.get("other-bank", "c1")


def test_evaluate_escalates_on_breach() -> None:
    service, _, _, events = _service()
    service.open_case(case_id="c1", tenant="demo-bank", case_type="complaint", actor="a", as_of=MON)
    fri = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    assessment = service.evaluate_case(case_id="c1", tenant="demo-bank", as_of=fri)
    assert assessment.requires_human_review
    # Soft escalation emitted a case.escalated event (routes to the console).
    assert "case.escalated" in [e.event_type for e in events.published()]


def test_pii_in_attributes_is_redacted_before_audit() -> None:
    service, audit, _, _ = _service()
    service.open_case(
        case_id="c1",
        tenant="demo-bank",
        case_type="complaint",
        actor="a",
        attributes={"borrower": "NRIC S1234567D on file"},
        as_of=MON,
    )
    for record in audit.log.read_all():
        assert "S1234567D" not in str(record.get("redacted_summary", ""))
    assert audit.log.verify_chain().ok
