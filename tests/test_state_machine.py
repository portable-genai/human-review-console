"""The state machine: legal transitions, refused illegal transitions, append-only history."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from review_console.domain.cases.models import new_case
from review_console.domain.cases.sample_workflows import COMPLAINT_WORKFLOW
from review_console.domain.cases.state_machine import (
    IllegalTransition,
    legal_next_states,
    transition,
)

_AS_OF = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)


def _case():
    return new_case(case_id="c1", tenant="demo-bank", definition=COMPLAINT_WORKFLOW)


def test_initial_state_and_legal_next_states() -> None:
    case = _case()
    assert case.state == "received"
    assert legal_next_states(case, COMPLAINT_WORKFLOW) == ("under_review",)


def test_legal_transition_appends_history() -> None:
    case = _case()
    moved = transition(
        case,
        "under_review",
        actor="a",
        reason="triage",
        as_of=_AS_OF,
        definition=COMPLAINT_WORKFLOW,
    )
    assert moved.state == "under_review"
    assert len(moved.history) == 1
    entry = moved.history[0]
    assert entry.from_state == "received" and entry.to_state == "under_review"
    assert entry.seq == 1
    # The original case is unchanged (immutability).
    assert case.state == "received"


def test_illegal_transition_is_refused() -> None:
    case = _case()
    with pytest.raises(IllegalTransition):
        transition(
            case, "resolved", actor="a", reason="skip", as_of=_AS_OF, definition=COMPLAINT_WORKFLOW
        )


def test_history_sequences_increment() -> None:
    case = _case()
    a = transition(
        case, "under_review", actor="a", reason="", as_of=_AS_OF, definition=COMPLAINT_WORKFLOW
    )
    b = transition(
        a, "awaiting_customer", actor="a", reason="", as_of=_AS_OF, definition=COMPLAINT_WORKFLOW
    )
    assert [t.seq for t in b.history] == [1, 2]
    assert b.state == "awaiting_customer"


def test_terminal_states() -> None:
    assert COMPLAINT_WORKFLOW.is_terminal("resolved")
    assert COMPLAINT_WORKFLOW.is_terminal("closed")
    assert not COMPLAINT_WORKFLOW.is_terminal("under_review")
